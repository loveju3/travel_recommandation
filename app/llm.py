"""LLM：① 把自然語言 query 解析成結構化條件 ② 產生一句話推薦理由。"""
import json
from functools import lru_cache

from .config import CHAT_MODEL, LLM_AVAILABLE, OPENAI_API_KEY

TAG_VOCAB = ["親子", "蜜月", "情侶", "長輩友善", "無購物站", "慢遊", "美食", "購物", "溫泉", "海島", "浮潛", "健行", "戶外",
             "冒險", "自然", "文化", "古蹟", "藝術", "攝影", "夜景", "鐵道", "動物", "主題樂園", "奢華", "小資", "經濟實惠",
             "賞楓", "賞櫻", "雪景", "滑雪", "花季", "極光", "節慶", "深度", "SPA", "郵輪", "季節限定"]
REGION_VOCAB = ["日本", "韓國", "東南亞", "中國港澳", "歐洲", "美洲", "紐澳", "中東", "國內"]
TYPE_VOCAB = ["團體旅遊", "自由行", "機加酒", "郵輪", "國內旅遊"]

PARSE_PROMPT = f"""你是旅遊電商的搜尋 query 解析器。把使用者輸入轉成 JSON，只輸出 JSON，不要多餘文字。
今天日期：2026-11-16。

欄位（沒提到就給 null 或空陣列，不要自行猜測）：
- destinations: 目的地字串陣列，可以是國家、區域或城市名（例：["日本"]、["北海道"]、["京都"]）。區域可用：{REGION_VOCAB}
- min_price / max_price: 每人預算（新台幣整數）。「五萬以內」→ max_price=50000
- min_days / max_days: 天數。「週末」→ max_days=3；「兩天一夜」→ min_days=2,max_days=2；「五天左右」→ 4~6
- product_types: 從 {TYPE_VOCAB} 選。「不想跟團、自己玩」→ ["自由行","機加酒"]
- departure_airport: "TPE"/"KHH"/"RMQ"，使用者明確說從哪裡出發才填（高雄→KHH、台中→RMQ）
- months: 想出發的月份整數陣列。「寒假」→[1,2]、「聖誕節」→[12]、「秋天」→[9,10,11]
- tags: 從這個清單挑出符合需求的標籤：{TAG_VOCAB}
  （「帶爸媽/長輩」→ 長輩友善、慢遊；「小孩」→ 親子；「看紅葉」→ 賞楓）
- semantic_query: 把使用者真正想要的旅遊體驗改寫成一句完整、具體的描述，供語意向量搜尋使用（去掉價格、天數等已結構化的條件）
- intent_summary: 用 15 字內的中文摘要使用者需求
"""


def _client():
    from openai import OpenAI
    return OpenAI(api_key=OPENAI_API_KEY)


@lru_cache(maxsize=512)
def _parse_cached(query: str) -> str:
    resp = _client().chat.completions.create(
        model=CHAT_MODEL, temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": PARSE_PROMPT}, {"role": "user", "content": query}],
    )
    return resp.choices[0].message.content


def parse_query(query: str) -> dict | None:
    if not LLM_AVAILABLE:
        return None
    try:
        data = json.loads(_parse_cached(query.strip()))
    except Exception as e:  # LLM 失敗時退回不解析，不讓搜尋整個掛掉
        return {"error": str(e)}
    data["tags"] = [t for t in (data.get("tags") or []) if t in TAG_VOCAB]
    data["product_types"] = [t for t in (data.get("product_types") or []) if t in TYPE_VOCAB]
    data["destinations"] = [d for d in (data.get("destinations") or []) if isinstance(d, str) and d]
    data["months"] = [int(m) for m in (data.get("months") or []) if str(m).isdigit() and 1 <= int(m) <= 12]
    for k in ("min_price", "max_price", "min_days", "max_days"):
        v = data.get(k)
        data[k] = int(v) if isinstance(v, (int, float)) and v > 0 else None
    if data.get("departure_airport") not in ("TPE", "KHH", "RMQ"):
        data["departure_airport"] = None
    return data


EXPLAIN_PROMPT = """你是旅遊顧問。根據使用者資料、搜尋需求與每個推薦商品的資訊，
為每個商品寫一句 40 字以內、具體、口語的繁體中文推薦理由（說明為什麼適合「這位使用者」的「這次需求」）。
不要編造商品沒有的資訊。輸出 JSON：{"reasons": {"商品id": "理由", ...}}"""


def explain(user: dict | None, query: str, items: list[dict]) -> dict:
    if not LLM_AVAILABLE or not items:
        return {}
    profile = "新會員，無資料" if not user else (
        f"{user['name']}，{user['age']}歲，{user['household']}，預算 {user['budget_min']}~{user['budget_max']}，"
        f"偏好：{'、'.join(user['styles'] or [])}。{user['note']}")
    lines = [f"- {it['id']}｜{it['title']}｜{it['days']}天｜{it['price']}元｜標籤：{'、'.join(it['tags'][:8])}"
             f"｜系統命中原因：{'、'.join(it.get('reasons', []))}" for it in items]
    try:
        resp = _client().chat.completions.create(
            model=CHAT_MODEL, temperature=0.3, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": EXPLAIN_PROMPT},
                      {"role": "user", "content": f"使用者：{profile}\n搜尋：{query}\n商品：\n" + "\n".join(lines)}])
        return json.loads(resp.choices[0].message.content).get("reasons", {})
    except Exception as e:
        return {"_error": str(e)}
