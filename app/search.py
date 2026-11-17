"""
三種搜尋方式：
  1. keyword  : Jieba 斷詞 + Postgres 全文檢索（舊方法 baseline）
  2. vector   : 原始 query 的 embedding 與商品 embedding 做 cosine（純語意）
  3. hybrid   : LLM 解析條件 → 結構化過濾 → 關鍵字 + 向量 RRF 融合 → 個人化 & 商業因素重新排序
"""
import json
import time
from datetime import date

import numpy as np
from psycopg.types.json import Jsonb

from . import llm
from .config import DATA_DIR
from .db import conn
from .embeddings import embed_query
from .tokenizer import to_tsquery_str, tokenize

TODAY = date(2026, 11, 16)
RRF_K = 60
CAND_LIMIT = 60
COLS = ("p.id, p.title, p.product_type, p.region, p.country, p.cities, p.days, p.price, p.departure_airport, "
        "p.hotel_level, p.highlights, p.tags, p.suitable_for, p.seasons, p.departures, p.popularity, p.rating, "
        "p.review_count, p.jieba_tokens")

_EVAL = {}
_eval_path = DATA_DIR / "eval_queries.json"
if _eval_path.exists():
    _EVAL = {e["query"]: set(e["relevant"]) for e in json.loads(_eval_path.read_text(encoding="utf-8"))}


# ─────────────────────────── 共用 ───────────────────────────
def _vec(x):
    """pgvector 回傳的 Vector 物件 / ndarray / list 統一轉成 numpy。"""
    if x is None:
        return None
    if hasattr(x, "to_numpy"):
        x = x.to_numpy()
    return np.asarray(x, dtype=float)


def _minmax(xs):
    xs = np.asarray(xs, dtype=float)
    if len(xs) == 0:
        return xs
    lo, hi = xs.min(), xs.max()
    return np.ones_like(xs) if hi - lo < 1e-9 else (xs - lo) / (hi - lo)


def _available_departures(p, months=None):
    out = []
    for d in p["departures"] or []:
        dd = date.fromisoformat(d["date"])
        if dd >= TODAY and d["seats_left"] > 0 and (not months or dd.month in months):
            out.append(d)
    return sorted(out, key=lambda d: d["date"])


def _card(p):
    nxt = _available_departures(p)
    return {k: p[k] for k in ("id", "title", "product_type", "region", "country", "cities", "days", "price",
                              "departure_airport", "hotel_level", "tags", "rating", "popularity", "review_count")} | {
        "next_departure": nxt[0] if nxt else None}


def build_filters(parsed: dict | None, level: int):
    """level 0＝全部條件；1＝只保留目的地與商品類型；2＝不過濾。回傳 (sql, params, 套用的條件描述)"""
    where, params, applied = ["TRUE"], [], []
    if not parsed or level >= 2:
        return " AND ".join(where), params, applied
    dests = parsed.get("destinations") or []
    if dests:
        where.append("EXISTS (SELECT 1 FROM unnest(%s::text[]) x WHERE p.country = x OR p.region = x OR x = ANY(p.cities) OR p.title LIKE '%%' || x || '%%')")
        params.append(dests); applied.append(f"目的地 ∈ {dests}")
    if parsed.get("product_types"):
        where.append("p.product_type = ANY(%s)"); params.append(parsed["product_types"]); applied.append(f"類型 ∈ {parsed['product_types']}")
    if level == 0:
        if parsed.get("max_price"):
            where.append("p.price <= %s"); params.append(parsed["max_price"]); applied.append(f"價格 ≤ {parsed['max_price']:,}")
        if parsed.get("min_price"):
            where.append("p.price >= %s"); params.append(parsed["min_price"]); applied.append(f"價格 ≥ {parsed['min_price']:,}")
        if parsed.get("min_days"):
            where.append("p.days >= %s"); params.append(parsed["min_days"]); applied.append(f"天數 ≥ {parsed['min_days']}")
        if parsed.get("max_days"):
            where.append("p.days <= %s"); params.append(parsed["max_days"]); applied.append(f"天數 ≤ {parsed['max_days']}")
        if parsed.get("departure_airport"):
            where.append("p.departure_airport = %s"); params.append(parsed["departure_airport"]); applied.append(f"出發地 = {parsed['departure_airport']}")
        if parsed.get("months"):
            where.append("EXISTS (SELECT 1 FROM jsonb_array_elements(p.departures) d WHERE extract(month FROM (d->>'date')::date) = ANY(%s))")
            params.append(parsed["months"]); applied.append(f"出發月份 ∈ {parsed['months']}")
    return " AND ".join(where), params, applied


def keyword_search(tokens, where="TRUE", params=(), limit=CAND_LIMIT):
    if not tokens:
        return []
    tsq = to_tsquery_str(tokens)
    sql = f"""SELECT {COLS}, ts_rank_cd(p.tsv, to_tsquery('simple', %s)) AS kw
              FROM products p WHERE p.tsv @@ to_tsquery('simple', %s) AND {where}
              ORDER BY kw DESC, p.popularity DESC LIMIT %s"""
    with conn() as c:
        return c.execute(sql, [tsq, tsq, *params, limit]).fetchall()


def vector_search(qvec, where="TRUE", params=(), limit=CAND_LIMIT):
    # 摘要向量 70% + 每日行程向量 30%：細節需求（例如「看合掌村」）也能被行程內容命中
    sql = f"""SELECT {COLS}, 1 - (p.emb_summary <=> %s) AS s1, 1 - (p.emb_itinerary <=> %s) AS s2
              FROM products p WHERE {where}
              ORDER BY p.emb_summary <=> %s LIMIT %s"""
    with conn() as c:
        rows = c.execute(sql, [qvec, qvec, *params, qvec, limit]).fetchall()
    for r in rows:
        r["vec"] = 0.7 * float(r["s1"]) + 0.3 * float(r["s2"])
    rows.sort(key=lambda r: r["vec"], reverse=True)
    return rows


# ─────────────────────────── 使用者 ───────────────────────────
def get_user(uid: str | None):
    if not uid:
        return None
    with conn() as c:
        u = c.execute("SELECT * FROM users WHERE id = %s", [uid]).fetchone()
        if not u:
            return None
        u["orders"] = c.execute("""SELECT o.*, p.title, p.region, p.tags, p.emb_summary FROM orders o
                                   JOIN products p ON p.id = o.product_id WHERE o.user_id = %s ORDER BY o.departure_date DESC""",
                                [uid]).fetchall()
        u["wishlist_items"] = c.execute("SELECT id, title FROM products WHERE id = ANY(%s)", [u["wishlist"] or []]).fetchall()
    return u


def public_user(u):
    if not u:
        return None
    out = {k: v for k, v in u.items() if k not in ("profile_emb", "orders")}
    out["has_profile_vector"] = u.get("profile_emb") is not None
    out["orders"] = [{k: v for k, v in o.items() if k != "emb_summary"} for o in u["orders"]]
    for o in out["orders"]:
        o["departure_date"] = str(o["departure_date"])
    out["profile_updated_at"] = str(u.get("profile_updated_at") or "")
    return out


# ─────────────────────────── 個人化 / 商業分數 ───────────────────────────
def personal_scores(user, cands, embs):
    """回傳 (分數陣列 0~1, 每筆的理由)。冷啟動回傳 None。"""
    if not user or (user.get("profile_emb") is None and not user["orders"]):
        return None, [[] for _ in cands]
    prof = _vec(user["profile_emb"])
    pref = _minmax(embs @ prof)
    bought = {o["product_id"] for o in user["orders"]}
    hist = [(o["title"], _vec(o["emb_summary"])) for o in user["orders"]]
    hist_sims = np.stack([embs @ h for _, h in hist], axis=1) if hist else None
    sim_cut = np.percentile(hist_sims.max(axis=1), 75) if hist_sims is not None else None

    scores, reasons = [], []
    hh = user.get("household") or ""
    for i, p in enumerate(cands):
        rules, why = [], []
        bmin, bmax = user.get("budget_min"), user.get("budget_max")
        if bmax:
            if p["price"] <= bmax and p["price"] >= (bmin or 0) * 0.8:
                rules.append(1.0); why.append("符合預算")
            elif p["price"] > bmax:
                rules.append(max(0.0, 1 - (p["price"] - bmax) / bmax)); why.append("⚠ 超出平常預算")
            else:
                rules.append(0.7)
        pdays = user.get("preferred_days")
        if pdays:
            lo, hi = pdays
            dist = 0 if lo <= p["days"] <= hi else min(abs(p["days"] - lo), abs(p["days"] - hi))
            rules.append(1 - min(dist, 5) / 5)
            if dist == 0:
                why.append(f"{p['days']}天符合假期長度")
        if user.get("home_airport") and user["home_airport"] != "TPE":
            hit = p["departure_airport"] == user["home_airport"]
            rules.append(1.0 if hit else 0.3)
            if hit:
                why.append(f"{p['departure_airport']} 在地出發")
        if "小孩" in hh:
            hit = "親子" in p["tags"]; rules.append(1.0 if hit else 0.3)
            if hit:
                why.append("親子友善")
        if "退休" in hh or (user.get("age") or 0) >= 60:
            hit = "長輩友善" in p["tags"] or "慢遊" in p["tags"]; rules.append(1.0 if hit else 0.4)
            if hit:
                why.append("長輩友善")
        if "新婚" in hh:
            hit = bool({"蜜月", "情侶", "浪漫"} & set(p["tags"])); rules.append(1.0 if hit else 0.4)
            if hit:
                why.append("適合兩人旅行")
        styles = user.get("styles") or []
        if styles:
            ov = [s for s in styles if s in p["tags"]]
            rules.append(min(1.0, len(ov) / min(3, len(styles))))
            if ov:
                why.append("符合你的風格：" + "、".join(ov))
        rule = float(np.mean(rules)) if rules else 0.5
        s = 0.5 * pref[i] + 0.5 * rule
        if hist_sims is not None and hist_sims[i].max() >= sim_cut and p["id"] not in bought:
            why.append(f"和你去過的「{hist[int(hist_sims[i].argmax())][0][:18]}…」相似")
        if p["id"] in (user.get("wishlist") or []):
            s = min(1.0, s + 0.1); why.append("❤ 在你的收藏清單")
        if p["id"] in bought:
            why.append("⚠ 你已購買過此商品")
        scores.append(s); reasons.append(why)
    return np.array(scores), reasons


def business_scores(cands, months=None):
    scores, reasons = [], []
    for p in cands:
        avail = _available_departures(p, months)
        why = []
        urgency = 0.0
        if avail:
            left = min(d["seats_left"] for d in avail[:3])
            if left <= 6:
                urgency = 1.0; why.append(f"名額有限：剩 {left} 位")
        else:
            why.append("⚠ 近期無可售團位")
        if p["popularity"] >= 0.6:
            why.append("熱銷商品")
        s = 0.5 * p["popularity"] + 0.3 * max(0.0, min(1.0, (p["rating"] - 4.0))) + 0.2 * urgency
        scores.append(s if avail else s * 0.3); reasons.append(why)
    return np.array(scores), reasons


# ─────────────────────────── 三種模式 ───────────────────────────
def run_keyword(query, top_n):
    tokens = tokenize(query)
    rows = keyword_search(tokens, limit=top_n)
    qset = set(tokens)
    out = []
    for r in rows:
        doc = set(r["jieba_tokens"].split())
        out.append(_card(r) | {"scores": {"keyword": round(float(r["kw"]), 4)}, "matched_tokens": [t for t in qset if t in doc]})
    return out, tokens


def run_vector(query, top_n):
    rows = vector_search(embed_query(query), limit=top_n)
    return [_card(r) | {"scores": {"cosine": round(r["vec"], 4)}} for r in rows]


def run_hybrid(query, user, parsed, top_n, weights, timings):
    t = time.perf_counter()
    tokens = tokenize(query) + [x.lower() for x in (parsed or {}).get("tags", [])]
    sem_text = (parsed or {}).get("semantic_query") or query
    qvec = embed_query(sem_text)
    timings["embed_ms"] = round((time.perf_counter() - t) * 1000, 1)

    t = time.perf_counter()
    # 先用全部條件；不足 top_n 時逐步放寬，「補位」的商品會降權並標示，嚴格符合的永遠排前面
    rrf, rows, level_of, kw_rank, vs_rank = {}, {}, {}, {}, {}
    applied, relaxed = [], 0
    for level in (0, 1, 2):
        where, params, appl = build_filters(parsed, level)
        if level == 0:
            applied = appl
        kw = keyword_search(tokens, where, params)
        vs = vector_search(qvec, where, params)
        for lst, rmap in ((kw, kw_rank), (vs, vs_rank)):
            for rank, r in enumerate(lst):
                if level_of.get(r["id"], level) != level:
                    continue  # 已在更嚴格的層級出現過
                level_of[r["id"]] = level
                rmap.setdefault(r["id"], rank + 1)
                rrf[r["id"]] = rrf.get(r["id"], 0) + 1 / (RRF_K + rank + 1)
                rows.setdefault(r["id"], r)
        relaxed = level
        if len(rrf) >= top_n or not parsed or not appl:
            break
    timings["retrieve_ms"] = round((time.perf_counter() - t) * 1000, 1)

    t = time.perf_counter()
    cids = list(rrf)
    if not cids:
        return [], {"applied_filters": applied, "relaxed_level": relaxed}
    with conn() as c:
        emap = {r["id"]: _vec(r["emb_summary"])
                for r in c.execute("SELECT id, emb_summary FROM products WHERE id = ANY(%s)", [cids]).fetchall()}
    cands = [rows[i] for i in cids]
    embs = np.stack([emap[i] for i in cids])

    cos = embs @ _vec(qvec)
    want_tags = (parsed or {}).get("tags") or []
    tag_match = np.array([sum(t in p["tags"] for t in want_tags) / len(want_tags) for p in cands]) if want_tags else None
    rrf_n = _minmax([rrf[i] for i in cids])
    cos_n = _minmax(cos)
    relevance = (0.5 * rrf_n + 0.3 * cos_n + 0.2 * tag_match) if tag_match is not None else (0.6 * rrf_n + 0.4 * cos_n)

    pers, p_why = personal_scores(user, cands, embs)
    biz, b_why = business_scores(cands, (parsed or {}).get("months"))

    a, b, g = weights.get("relevance", 0.6), weights.get("personal", 0.25), weights.get("business", 0.15)
    cold = pers is None
    if cold:
        b = 0.0
        pers = np.zeros(len(cands))
    tot = (a + b + g) or 1.0
    a, b, g = a / tot, b / tot, g / tot
    final = a * relevance + b * pers + g * biz

    bought = {o["product_id"] for o in user["orders"]} if user else set()
    for i, p in enumerate(cands):
        if p["id"] in bought:
            final[i] *= 0.6
    order = sorted(range(len(cands)), key=lambda i: (level_of[cands[i]["id"]], -final[i]))[:top_n]
    timings["rerank_ms"] = round((time.perf_counter() - t) * 1000, 1)

    results = []
    for i in order:
        p = cands[i]
        q_why = []
        if want_tags:
            hit = [t for t in want_tags if t in p["tags"]]
            if hit:
                q_why.append("符合需求：" + "、".join(hit))
        if level_of[p["id"]] > 0:
            q_why.append("⚠ 不完全符合條件（放寬後補位）")
        results.append(_card(p) | {
            "scores": {"final": round(float(final[i]), 4),
                       "relevance": round(float(relevance[i]), 4), "personal": round(float(pers[i]), 4), "business": round(float(biz[i]), 4),
                       "w_relevance": round(a * float(relevance[i]), 4), "w_personal": round(b * float(pers[i]), 4), "w_business": round(g * float(biz[i]), 4),
                       "cosine": round(float(cos[i]), 4), "kw_rank": kw_rank.get(p["id"]), "vec_rank": vs_rank.get(p["id"]),
                       "filter_level": level_of[p["id"]]},
            "reasons": q_why + p_why[i] + b_why[i],
        })
        nxt = _available_departures(p, (parsed or {}).get("months"))
        if nxt:
            results[-1]["next_departure"] = nxt[0]
    meta = {"applied_filters": applied, "relaxed_level": relaxed, "semantic_text": sem_text, "candidates": len(cands),
            "cold_start": cold, "weights_used": {"relevance": round(a, 3), "personal": round(b, 3), "business": round(g, 3)}}
    return results, meta


def search(query, user_id=None, top_n=10, modes=("keyword", "vector", "hybrid"), use_llm_parse=True,
           use_llm_explain=False, weights=None):
    timings, out = {}, {"query": query}
    t0 = time.perf_counter()
    user = get_user(user_id)
    out["user_id"] = user_id

    if "keyword" in modes:
        t = time.perf_counter()
        out["keyword"], out["tokens"] = run_keyword(query, top_n)
        timings["keyword_total_ms"] = round((time.perf_counter() - t) * 1000, 1)
    else:
        out["tokens"] = tokenize(query)

    if "vector" in modes:
        t = time.perf_counter()
        out["vector"] = run_vector(query, top_n)
        timings["vector_total_ms"] = round((time.perf_counter() - t) * 1000, 1)

    parsed = None
    if "hybrid" in modes:
        if use_llm_parse:
            t = time.perf_counter()
            parsed = llm.parse_query(query)
            timings["llm_parse_ms"] = round((time.perf_counter() - t) * 1000, 1)
            if parsed and parsed.get("error"):
                out["llm_error"] = parsed["error"]; parsed = None
        out["parsed"] = parsed
        out["hybrid"], out["hybrid_meta"] = run_hybrid(query, user, parsed, top_n, weights or {}, timings)
        if use_llm_explain and out["hybrid"]:
            t = time.perf_counter()
            exp = llm.explain(user, query, out["hybrid"])
            timings["llm_explain_ms"] = round((time.perf_counter() - t) * 1000, 1)
            for r in out["hybrid"]:
                if r["id"] in exp:
                    r["explanation"] = exp[r["id"]]
            if "_error" in exp:
                out["llm_error"] = exp["_error"]

    timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    out["timings"] = timings
    out["relevant_ids"] = sorted(_EVAL.get(query.strip(), []))
    try:
        with conn() as c:
            c.execute("INSERT INTO search_logs (user_id, query, params, parsed, result_ids, timings_ms) VALUES (%s,%s,%s,%s,%s,%s)",
                      [user_id, query, Jsonb({"top_n": top_n, "modes": list(modes), "llm_parse": use_llm_parse, "weights": weights}),
                       Jsonb(parsed), Jsonb({m: [r["id"] for r in out.get(m, [])] for m in ("keyword", "vector", "hybrid")}), Jsonb(timings)])
    except Exception:
        pass
    return out


def get_product(pid):
    with conn() as c:
        return c.execute(f"SELECT {COLS}, p.itinerary, p.description, p.airline FROM products p WHERE p.id = %s", [pid]).fetchone()
