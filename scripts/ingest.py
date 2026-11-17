"""
建立資料表 → 匯入商品 / 使用者 / 訂單 → 產生 embedding → 計算使用者偏好向量

用法：python scripts/ingest.py
"""
import json
import math
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from psycopg.types.json import Jsonb  # noqa: E402
from pgvector.psycopg import register_vector  # noqa: E402

from app.config import EMBED_DIM, EMBED_MODEL, EMBED_PROVIDER  # noqa: E402
from app.db import connect_raw  # noqa: E402
from app.embeddings import embed_batch  # noqa: E402
from app.tokenizer import tokenize  # noqa: E402

TODAY = date(2026, 11, 16)


def summary_text(p):
    return (f"{p['title']}\n"
            f"類型：{p['product_type']}｜地區：{p['region']}・{p['country']}｜城市：{'、'.join(p['cities'])}\n"
            f"天數：{p['days']}天｜價格：{p['price']}元起｜出發地：{p['departure_airport']}｜住宿：{p['hotel_level']}\n"
            f"行程特色：{'；'.join(p['highlights'])}\n"
            f"標籤：{'、'.join(p['tags'])}｜適合：{'、'.join(p['suitable_for'])}｜季節：{'、'.join(p['seasons'])}\n"
            f"{p['description']}")


def itinerary_text(p):
    return p["title"] + "\n" + "\n".join(f"第{d['day']}天 {d['title']}：{d['content']}" for d in p["itinerary"])


def profile_text(u):
    if not (u["styles"] or u["orders"]):
        return None
    return (f"{u['age']}歲{u['gender']}性，{u['household']}，住在{u['city']}。"
            f"旅遊偏好：{'、'.join(u['styles'])}。{u['note']}")


def main():
    t0 = time.time()
    products = json.loads((ROOT / "data/products.json").read_text(encoding="utf-8"))
    users = json.loads((ROOT / "data/users.json").read_text(encoding="utf-8"))
    print(f"Embedding provider = {EMBED_PROVIDER} / {EMBED_MODEL} / dim={EMBED_DIM}")

    conn = connect_raw()
    schema = (ROOT / "sql/schema.sql").read_text(encoding="utf-8").replace("vector(1536)", f"vector({EMBED_DIM})")
    conn.execute(schema)
    conn.commit()
    register_vector(conn)
    print("✓ 建立資料表")

    # ── 商品 embedding ──
    sums = [summary_text(p) for p in products]
    itins = [itinerary_text(p) for p in products]
    print(f"… 產生 {len(products) * 2} 筆商品 embedding")
    emb_s = embed_batch(sums)
    emb_i = embed_batch(itins)
    pemb = {p["id"]: e for p, e in zip(products, emb_s)}

    with conn.cursor() as cur:
        for p, s, it, es, ei in zip(products, sums, itins, emb_s, emb_i):
            t_title = " ".join(tokenize(p["title"]))
            t_mid = " ".join(tokenize(" ".join(p["tags"] + p["highlights"] + p["cities"] + [p["country"], p["region"], p["product_type"]])))
            t_rest = " ".join(tokenize(p["description"] + " " + " ".join(d["content"] for d in p["itinerary"])))
            cur.execute("""
                INSERT INTO products (id,title,product_type,region,country,cities,days,price,airline,departure_airport,hotel_level,
                    highlights,itinerary,tags,suitable_for,seasons,departures,popularity,rating,review_count,description,
                    doc_summary,doc_itinerary,jieba_tokens,tsv,emb_summary,emb_itinerary,embedding_model)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    setweight(to_tsvector('simple', %s),'A') || setweight(to_tsvector('simple', %s),'B') || setweight(to_tsvector('simple', %s),'C'),
                    %s,%s,%s)""",
                (p["id"], p["title"], p["product_type"], p["region"], p["country"], p["cities"], p["days"], p["price"],
                 p["airline"], p["departure_airport"], p["hotel_level"], p["highlights"], Jsonb(p["itinerary"]), p["tags"],
                 p["suitable_for"], p["seasons"], Jsonb(p["departures"]), p["popularity"], p["rating"], p["review_count"],
                 p["description"], s, it, f"{t_title} {t_mid} {t_rest}", t_title, t_mid, t_rest, es, ei,
                 f"{EMBED_PROVIDER}:{EMBED_MODEL}"))
    conn.commit()
    print(f"✓ 匯入商品 {len(products)} 筆")

    # ── 使用者偏好向量 ──
    # 加權平均：買過的商品（評分 × 時間衰減）＋ 收藏 ＋ 近期搜尋 ＋ 個人描述
    texts, owners = [], []
    for u in users:
        for q in u["recent_searches"]:
            texts.append(q); owners.append((u["id"], "search"))
        pt = profile_text(u)
        if pt:
            texts.append(pt); owners.append((u["id"], "profile"))
    extra = dict()
    for (uid, kind), e in zip(owners, embed_batch(texts) if texts else []):
        extra.setdefault(uid, []).append((kind, e))

    with conn.cursor() as cur:
        for u in users:
            vecs, ws = [], []
            for o in u["orders"]:
                days_ago = (TODAY - date.fromisoformat(o["departure_date"])).days
                vecs.append(pemb[o["product_id"]]); ws.append((o["rating"] / 5) * math.exp(-days_ago / 540))
            for pid in u["wishlist"]:
                vecs.append(pemb[pid]); ws.append(0.6)
            for kind, e in extra.get(u["id"], []):
                vecs.append(e); ws.append(0.4 if kind == "search" else 0.8)
            prof = None
            if vecs:
                v = np.average(np.stack(vecs), axis=0, weights=ws)
                prof = (v / np.linalg.norm(v)).astype(np.float32)
            cur.execute("""INSERT INTO users (id,name,age,gender,city,home_airport,household,member_tier,budget_min,budget_max,
                    preferred_days,styles,note,recent_searches,wishlist,profile_emb,profile_updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())""",
                        (u["id"], u["name"], u["age"], u["gender"], u["city"], u["home_airport"], u["household"], u["member_tier"],
                         u["budget_min"], u["budget_max"], u["preferred_days"], u["styles"], u["note"], u["recent_searches"],
                         u["wishlist"], prof))
            for o in u["orders"]:
                cur.execute("INSERT INTO orders VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (o["order_id"], u["id"], o["product_id"], o["departure_date"], o["pax"], o["amount"], o["rating"], o["review"]))
    conn.commit()
    print(f"✓ 匯入使用者 {len(users)} 位、訂單 {sum(len(u['orders']) for u in users)} 筆")
    print(f"完成，耗時 {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
