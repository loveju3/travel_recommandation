"""
產生 demo 用的假資料：
  data/products.json   旅遊商品
  data/users.json      使用者（含訂單、搜尋紀錄、收藏）
  data/eval_queries.json  評估用 query 與標註的相關商品
  data/userdict.txt    Jieba 自訂詞典（地名、標籤）

用法：python scripts/generate_data.py
"""
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from catalog import DESTINATIONS, THEMES, SEASON_LABEL, HANDCRAFTED  # noqa: E402

random.seed(42)
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

TODAY = date(2026, 11, 16)
DEP_START, DEP_END = date(2026, 11, 25), date(2027, 10, 31)
AIRPORT_NAME = {"TPE": "桃園機場", "KHH": "高雄小港機場", "RMQ": "台中機場"}
SEASON_OF = {12: "冬", 1: "冬", 2: "冬", 3: "春", 4: "春", 5: "春", 6: "夏", 7: "夏", 8: "夏", 9: "秋", 10: "秋", 11: "秋"}
SUITABLE = {"family": ["家庭"], "honeymoon": ["情侶"], "senior": ["長輩"], "outdoor": ["年輕族群"],
            "budget": ["年輕族群", "學生"], "luxury": ["情侶", "長輩"]}
TAG_WHITELIST = {"文化", "古蹟", "自然", "攝影", "美食", "購物", "親子", "動物", "主題樂園", "溫泉", "慢遊", "浪漫",
                 "海島", "浮潛", "冒險", "健行", "鐵道", "夜景", "SPA", "藝術", "奢華", "賞楓", "賞櫻", "雪景",
                 "滑雪", "花季", "極光", "節慶", "秘境"}


def price_round(p):
    return max(990, int(round(p / 1000.0)) * 1000 - 100)


def dates_in_months(months, n):
    """在出發區間內挑 n 個落在指定月份的日期。"""
    pool, d = [], DEP_START
    while d <= DEP_END:
        if months is None or d.month in months:
            pool.append(d)
        d += timedelta(days=1)
    return sorted(random.sample(pool, min(n, len(pool))))


def build_product(pid, dest, theme_key, season_tag=None):
    th = THEMES[theme_key]
    lo, hi = dest["days"]
    if theme_key in ("budget", "package", "fit"):
        days = lo
    elif theme_key in ("luxury", "deep"):
        days = hi
    else:
        days = random.randint(lo, hi)

    # ── 挑景點 ──
    forced, months = [], None
    if season_tag:
        seasonal = [s for s in dest["spots"] if season_tag in s["tags"] and s["months"]]
        forced = [random.choice(seasonal)]
        months = forced[0]["months"]
    candidates = [s for s in dest["spots"] if s not in forced and (
        s["months"] is None
        or (theme_key == "outdoor" and "健行" in s["tags"])
        or (months and set(s["months"]) & set(months)))]

    def score(s):
        return 2 * len(set(s["tags"]) & set(th["prefer"])) + random.random() * 1.5
    candidates.sort(key=score, reverse=True)
    n_spots = max(2, int(days * (0.9 if theme_key == "senior" else 1.5)))
    spots = forced + candidates[: n_spots - len(forced)]
    for s in spots:
        if s["months"] and months is None:
            months = s["months"]

    label = th["label"]
    tags = list(th["tags"])
    if season_tag:
        label = f"{SEASON_LABEL[season_tag]}季" if season_tag not in ("滑雪", "極光") else f"{SEASON_LABEL[season_tag]}之旅"
        tags.append(season_tag)
    for s in spots:
        tags += [t for t in s["tags"] if t in TAG_WHITELIST and (t != "親子" or theme_key == "family")]
    tags += dest["base_tags"]
    ptype = th["type"]
    if dest["region"] == "國內":
        ptype = "國內旅遊"
    if ptype in ("自由行", "機加酒"):
        tags.append("自由行")
    tags = list(dict.fromkeys(tags))  # 去重保序

    airport = random.choice(dest["airports"])
    airline = random.choice(dest["airlines"])
    if theme_key == "budget" and dest["region"] not in ("國內",):
        lcc = [a for a in dest["airlines"] if "虎航" in a or "樂桃" in a or "濟州" in a or "越捷" in a or "宿霧" in a or "泰獅" in a]
        airline = random.choice(lcc) if lcc else airline

    price = price_round(dest["per_day"] * days * th["mult"] * random.uniform(0.88, 1.12))

    # ── 標題 ──
    hook = random.choice(th["hooks"])
    title_spots = "．".join(s["name"] for s in spots[:2])
    title = f"【{label}】{dest['name']} {title_spots} {days}日｜{hook}"

    # ── 每日行程 ──
    cities = dest["cities"]
    itinerary = []
    body = spots[:]
    if days == 1:
        itinerary.append({"day": 1, "title": "一日遊", "content": "；".join(s["desc"] for s in body[:3])})
    else:
        per_day = max(1, -(-len(body) // max(1, days - 1)))
        dep = AIRPORT_NAME.get(airport, airport)
        for d in range(1, days + 1):
            city = cities[min(d - 1, len(cities) - 1)] if d < days else cities[0]
            todays = body[(d - 1) * per_day: d * per_day] if d < days else []
            if ptype in ("自由行", "機加酒"):
                if d == 1:
                    content = f"{dep}出發，抵達{city}後專車接送至飯店。" + (f"推薦傍晚前往：{todays[0]['desc']}。" if todays else "")
                elif d == days:
                    content = "睡到自然醒，整理行李後專車送往機場，返抵溫暖的家。"
                else:
                    content = "全日自由活動。推薦：" + "；".join(s["desc"] for s in todays) if todays else "全日自由活動。"
            else:
                if d == 1:
                    head = f"{dep}集合出發前往{city}。" if dest["region"] != "國內" else f"{dep}集合出發前往{city}。"
                    content = head + "；".join(s["desc"] for s in todays)
                elif d == days:
                    content = "早餐後前往機場，搭機返回台灣，結束愉快的旅程。" if dest["region"] != "國內" else "早餐後悠閒啟程返回，結束愉快旅程。"
                else:
                    content = "；".join(s["desc"] for s in todays) or f"{city}自由活動。"
                if theme_key == "senior" and 1 < d < days:
                    content += "（今日步行量少，午後回飯店休息）"
            itinerary.append({"day": d, "title": f"{city}｜" + ("．".join(s["name"] for s in todays) or ("返程" if d == days else "自由活動")), "content": content})

    highlights = [s["desc"] for s in spots[:3]] + [hook]
    desc = th["blurb"].format(name=dest["name"]) + f" 行程亮點包含{'、'.join(s['name'] for s in spots[:4])}。住宿{th['hotel']}，搭乘{airline}。"

    dep_dates = dates_in_months(months, random.randint(4, 6))
    departures = [{"date": d.isoformat(), "price": price_round(price * random.uniform(0.95, 1.15)),
                   "seats_left": random.choice([0, 2, 4, 6, 8, 10, 12, 15, 18, 22, 26])} for d in dep_dates]
    seasons = sorted({SEASON_OF[d.month] for d in dep_dates}, key="春夏秋冬".index)

    popularity = round(min(1.0, random.betavariate(2, 4) + (0.15 if theme_key in ("classic", "family") else 0)), 3)
    return dict(
        id=pid, title=title, product_type=ptype, region=dest["region"], country=dest["country"],
        cities=[c for c in cities], days=days, price=price, airline=airline,
        departure_airport=airport, hotel_level=th["hotel"], highlights=highlights,
        itinerary=itinerary, tags=tags, suitable_for=SUITABLE.get(theme_key, ["所有人"]), seasons=seasons,
        departures=departures, popularity=popularity, rating=round(random.uniform(4.1, 4.95), 1),
        review_count=int(20 + popularity * random.randint(50, 900)), description=desc,
        theme=theme_key,
    )


def gen_products():
    products, n = [], 1
    for dest in DESTINATIONS:
        season_tags = []
        for s in dest["spots"]:
            for t in s["tags"]:
                if t in SEASON_LABEL and s["months"] and t not in season_tags:
                    season_tags.append(t)
        si = 0
        for th in dest["themes"]:
            st = None
            if th == "seasonal":
                if not season_tags:
                    continue
                st = season_tags[si % len(season_tags)]
                si += 1
            products.append(build_product(f"P{n:04d}", dest, th, st))
            n += 1
    for h in HANDCRAFTED:
        price = h["price"]
        dep = dates_in_months({"春": [3, 4, 5], "夏": [6, 7, 8], "秋": [9, 10, 11], "冬": [12, 1, 2], "四季": None}.get(h["seasons"][0]) if len(h["seasons"]) == 1 else None, 5)
        products.append(dict(
            id=f"P{n:04d}", title=h["title"], product_type=h["product_type"], region=h["region"], country=h["country"],
            cities=h["cities"], days=h["days"], price=price, airline=h["airline"], departure_airport=h["departure_airport"],
            hotel_level=h["hotel_level"], highlights=h["highlights"],
            itinerary=[{"day": i + 1, "title": t[:12], "content": t} for i, t in enumerate(h["itinerary"])],
            tags=h["tags"], suitable_for=h["suitable_for"], seasons=h["seasons"],
            departures=[{"date": d.isoformat(), "price": price_round(price * random.uniform(0.95, 1.1)), "seats_left": random.choice([3, 8, 15, 30])} for d in dep],
            popularity=round(random.uniform(0.3, 0.8), 3), rating=round(random.uniform(4.3, 4.9), 1),
            review_count=random.randint(30, 400), description="；".join(h["highlights"]) + "。", theme="handcrafted"))
        n += 1
    return products


# ─────────────────────────── 使用者 ───────────────────────────
def has(p, *tags):
    return all(t in p["tags"] for t in tags)


PERSONAS = [
    dict(id="U01", name="王建國", age=63, gender="男", city="台北市", home_airport="TPE", household="夫妻兩人（退休）", member_tier="鑽石卡",
         budget_min=30000, budget_max=70000, preferred_days=[5, 8], styles=["溫泉", "慢遊", "文化"],
         note="退休公務員，膝蓋不好不能走太多，最討厭購物站和每天換飯店。", recent_searches=["日本溫泉 不換飯店", "郵輪 長輩"],
         buys=[(lambda p: has(p, "長輩友善") and p["region"] == "日本", 2), (lambda p: has(p, "溫泉") and p["region"] == "國內", 1)]),
    dict(id="U02", name="林佳穎", age=36, gender="女", city="新北市", home_airport="TPE", household="夫妻＋兩個小孩（5歲、8歲）", member_tier="金卡",
         budget_min=20000, budget_max=45000, preferred_days=[4, 6], styles=["親子", "主題樂園", "海島"],
         note="上班族媽媽，寒暑假一定帶小孩出國，重視飯店舒適與孩子玩得開心。", recent_searches=["寒假 親子", "沖繩 水族館"],
         buys=[(lambda p: has(p, "親子") and p["region"] in ("日本", "東南亞"), 3)]),
    dict(id="U03", name="陳柏翰", age=28, gender="男", city="台中市", home_airport="RMQ", household="單身", member_tier="一般會員",
         budget_min=15000, budget_max=60000, preferred_days=[5, 10], styles=["健行", "冒險", "自然"],
         note="戶外運動愛好者，喜歡登山健行與極限運動，不喜歡走馬看花的團。", recent_searches=["健行", "潛水"],
         buys=[(lambda p: has(p, "健行"), 2), (lambda p: has(p, "冒險") and p["region"] == "東南亞", 1)]),
    dict(id="U04", name="張雅婷", age=31, gender="女", city="台北市", home_airport="TPE", household="新婚夫妻", member_tier="金卡",
         budget_min=60000, budget_max=150000, preferred_days=[5, 10], styles=["浪漫", "奢華", "海島"],
         note="剛結婚，重視拍照與質感住宿，年底想規劃第二次旅行紀念日。", recent_searches=["蜜月 villa", "結婚紀念日 旅行"],
         buys=[(lambda p: has(p, "蜜月") and has(p, "海島"), 1)]),
    dict(id="U05", name="黃志明", age=45, gender="男", city="高雄市", home_airport="KHH", household="夫妻兩人", member_tier="白金卡",
         budget_min=25000, budget_max=55000, preferred_days=[4, 5], styles=["美食", "購物"],
         note="科技公司主管，只能請短假，出國就是為了吃。偏好高雄出發。", recent_searches=["高雄出發 美食", "螃蟹"],
         buys=[(lambda p: has(p, "美食") and p["region"] in ("日本", "韓國"), 3)]),
    dict(id="U06", name="李美華", age=56, gender="女", city="台南市", home_airport="TPE", household="與姊妹結伴", member_tier="鑽石卡",
         budget_min=80000, budget_max=160000, preferred_days=[9, 13], styles=["藝術", "文化", "古蹟"],
         note="退休美術老師，每年一趟歐洲深度旅行，偏好有專業導覽的行程。", recent_searches=["歐洲 美術館", "深度旅遊"],
         buys=[(lambda p: p["region"] == "歐洲" and has(p, "藝術"), 2)]),
    dict(id="U07", name="劉宇軒", age=22, gender="男", city="台北市", home_airport="TPE", household="學生（與同學結伴）", member_tier="一般會員",
         budget_min=8000, budget_max=25000, preferred_days=[3, 5], styles=["小資", "購物", "美食"],
         note="大學生，打工存錢出國，追求 CP 值，喜歡自由行。", recent_searches=["便宜 機加酒", "首爾 自由行"],
         buys=[(lambda p: has(p, "小資") and p["region"] in ("韓國", "東南亞"), 2)]),
    dict(id="U08", name="吳淑芬", age=42, gender="女", city="新竹市", home_airport="TPE", household="單身", member_tier="白金卡",
         budget_min=40000, budget_max=120000, preferred_days=[5, 11], styles=["攝影", "季節限定", "自然"],
         note="業餘攝影師，專門追季節限定的風景：櫻花、楓葉、雪景、極光。", recent_searches=["賞楓 攝影", "雪景"],
         buys=[(lambda p: has(p, "賞楓") and p["region"] == "日本", 1), (lambda p: has(p, "雪景") and has(p, "季節限定") and p["region"] == "日本", 1)]),
    dict(id="U09", name="蔡家豪", age=37, gender="男", city="台北市", home_airport="TPE", household="夫妻＋一個小孩（10歲）", member_tier="金卡",
         budget_min=40000, budget_max=90000, preferred_days=[5, 9], styles=["滑雪", "雪景", "冒險"],
         note="每年冬天都要去滑雪，最近開始帶孩子一起學。", recent_searches=["滑雪 教練", "雪地 親子"],
         buys=[(lambda p: has(p, "滑雪"), 1)]),
    dict(id="U10", name="鄭小姐（新會員）", age=30, gender="女", city="台北市", home_airport="TPE", household="未填寫", member_tier="新會員",
         budget_min=None, budget_max=None, preferred_days=None, styles=[],
         note="剛註冊的新會員，沒有任何消費紀錄（冷啟動情境）。", recent_searches=[], buys=[]),
]
REVIEWS = {5: ["非常滿意，領隊很專業，下次還會再參加！", "行程安排得很好，家人都很開心。", "飯店和餐食都超出預期。"],
           4: ["整體不錯，有一天行程稍微趕了一點。", "景點很美，餐食普通。", "CP 值高，推薦。"],
           3: ["還可以，但飯店離市區有點遠。", "行程和預期有落差，購物站太多。"]}


def gen_users(products):
    users, oid = [], 1
    for per in PERSONAS:
        orders, used = [], set()
        for fn, cnt in per["buys"]:
            cands = [p for p in products if fn(p) and p["id"] not in used]
            random.shuffle(cands)
            for p in cands[:cnt]:
                used.add(p["id"])
                d = TODAY - timedelta(days=random.randint(60, 900))
                pax = {"U02": 4, "U09": 3, "U01": 2, "U04": 2, "U05": 2, "U06": 2}.get(per["id"], 1)
                rating = random.choice([5, 5, 4, 4, 3]) if per["id"] != "U01" else random.choice([5, 4])
                orders.append(dict(order_id=f"O{oid:04d}", product_id=p["id"], departure_date=d.isoformat(), pax=pax,
                                   amount=p["price"] * pax, rating=rating, review=random.choice(REVIEWS[rating])))
                oid += 1
        orders.sort(key=lambda o: o["departure_date"])
        # 收藏清單：符合風格但沒買過的商品
        wish = [p["id"] for p in products if p["id"] not in used and per["styles"] and
                sum(t in p["tags"] for t in per["styles"]) >= 2]
        random.shuffle(wish)
        u = {k: v for k, v in per.items() if k != "buys"}
        u["orders"] = orders
        u["wishlist"] = wish[:2]
        users.append(u)
    return users


# ─────────────────────────── 評估 query ───────────────────────────
ANIMALS = ["動物", "企鵝", "大象", "鯨鯊", "無尾熊", "袋鼠", "羊駝", "小鹿", "熊貓", "馴鹿", "海豚", "眼鏡猴", "長頸鹿", "哈士奇"]
EVAL = [
    ("帶爸媽去日本泡溫泉，不要太累", lambda p: p["region"] == "日本" and has(p, "溫泉") and p["theme"] in ("senior", "onsen")),
    ("適合小朋友的海島行程", lambda p: "家庭" in p["suitable_for"] and has(p, "海島")),
    ("想看北極光", lambda p: has(p, "極光")),
    ("蜜月旅行 想住有私人泳池的villa", lambda p: has(p, "蜜月") and has(p, "海島")),
    ("秋天去看紅葉", lambda p: has(p, "賞楓")),
    ("冬天滑雪", lambda p: has(p, "滑雪")),
    ("白川鄉合掌村", lambda p: any("白川鄉" in d["content"] for d in p["itinerary"]) or "白川鄉" in p["title"]),
    ("十萬以內的歐洲行程", lambda p: p["region"] == "歐洲" and p["price"] <= 100000),
    ("週末短天數去韓國大吃", lambda p: p["region"] == "韓國" and p["days"] <= 4 and has(p, "美食")),
    ("國內兩天一夜放鬆一下", lambda p: p["region"] == "國內" and p["days"] <= 2),
    ("不想跟團，自己玩東京", lambda p: "東京" in p["cities"] and p["product_type"] in ("自由行", "機加酒")),
    ("喜歡爬山走步道親近大自然", lambda p: p["theme"] == "outdoor" or (has(p, "健行") and "年輕族群" in p["suitable_for"])),
    ("搭景觀火車欣賞阿爾卑斯雪山", lambda p: p["country"] == "瑞士" and has(p, "鐵道")),
    ("文藝復興 美術館 博物館巡禮", lambda p: p["region"] == "歐洲" and any(("美術館" in d["content"] or "博物館" in d["content"]) for d in p["itinerary"])),
    ("坐郵輪", lambda p: p["product_type"] == "郵輪"),
    ("預算兩萬以內 曼谷", lambda p: "曼谷" in p["cities"] and p["price"] <= 20000),
    ("搭熱氣球看日出", lambda p: "卡帕多奇亞" in p["cities"] and any("熱氣球" in d["content"] for d in p["itinerary"])),
    ("古鎮 掛滿燈籠的夜晚", lambda p: any("燈籠" in d["content"] for d in p["itinerary"])),
    ("從高雄出發去日本", lambda p: p["departure_airport"] == "KHH" and p["region"] == "日本"),
    ("京都賞櫻", lambda p: has(p, "賞櫻") and "京都" in p["cities"]),
    ("北海道吃螃蟹海鮮", lambda p: p["country"] == "日本" and "札幌" in p["cities"] and has(p, "美食")),
    ("想跟可愛動物互動", lambda p: has(p, "動物") and any(w in h for h in p["highlights"][:3] for w in ANIMALS)),
    ("沒有購物站的團", lambda p: has(p, "無購物站")),
    ("兩個人的浪漫旅行 預算充足", lambda p: "情侶" in p["suitable_for"]),
    ("潛水看海龜", lambda p: has(p, "浮潛")),
    ("聖誕節去歐洲逛市集", lambda p: has(p, "節慶") and p["region"] == "歐洲"),
]


def main():
    products = gen_products()
    users = gen_users(products)
    evals = []
    for q, fn in EVAL:
        rel = [p["id"] for p in products if fn(p)]
        evals.append({"query": q, "relevant": rel})
        if not rel:
            print("⚠️ 無相關商品：", q)
    for p in products:
        p.pop("theme", None)
    (DATA / "products.json").write_text(json.dumps(products, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "users.json").write_text(json.dumps(users, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "eval_queries.json").write_text(json.dumps(evals, ensure_ascii=False, indent=1), encoding="utf-8")

    words = set()
    for d in DESTINATIONS:
        words.add(d["name"]); words.update(d["cities"]); words.add(d["country"])
    for p in products:
        words.update(p["tags"]); words.update(p["cities"])
    words.update(["長輩友善", "無購物站", "機加酒", "自由行", "合掌村", "北極光", "歐若拉", "賞楓", "賞櫻", "迪士尼"])
    (DATA / "userdict.txt").write_text("\n".join(f"{w} 50000" for w in sorted(words) if len(w) > 1), encoding="utf-8")

    print(f"products={len(products)} users={len(users)} eval={len(evals)}")
    from collections import Counter
    print(Counter(p["region"] for p in products))
    print(Counter(p["product_type"] for p in products))
    for e in evals:
        print(f"  {len(e['relevant']):3d}  {e['query']}")
    for u in users:
        print(u["id"], u["name"], [o["product_id"] for o in u["orders"]], u["wishlist"])


if __name__ == "__main__":
    main()
