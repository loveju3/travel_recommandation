from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import search as S
from .config import CHAT_MODEL, EMBED_MODEL, EMBED_PROVIDER, LLM_AVAILABLE
from .db import conn
from .evaluate import run_eval

STATIC = Path(__file__).resolve().parent.parent / "static"
app = FastAPI(title="旅遊商品語意搜尋推薦 Demo")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class SearchReq(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    user_id: str | None = None
    top_n: int = Field(10, ge=1, le=30)
    modes: list[str] = ["keyword", "vector", "hybrid"]
    use_llm_parse: bool = True
    use_llm_explain: bool = False
    weights: dict[str, float] = {"relevance": 0.6, "personal": 0.25, "business": 0.15}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
def config():
    return {"embed_provider": EMBED_PROVIDER, "embed_model": EMBED_MODEL, "chat_model": CHAT_MODEL,
            "llm_available": LLM_AVAILABLE,
            "example_queries": list(S._EVAL.keys())}


@app.get("/api/users")
def users():
    with conn() as c:
        rows = c.execute("""SELECT u.id, u.name, u.age, u.household, u.member_tier, u.styles,
                                   (SELECT count(*) FROM orders o WHERE o.user_id = u.id) AS n_orders
                            FROM users u ORDER BY u.id""").fetchall()
    return rows


@app.get("/api/users/{uid}")
def user(uid: str):
    u = S.get_user(uid)
    if not u:
        raise HTTPException(404)
    return S.public_user(u)


@app.get("/api/products/{pid}")
def product(pid: str):
    p = S.get_product(pid)
    if not p:
        raise HTTPException(404)
    p.pop("jieba_tokens", None)
    return p


@app.post("/api/search")
def do_search(req: SearchReq):
    use_parse = req.use_llm_parse and LLM_AVAILABLE
    use_explain = req.use_llm_explain and LLM_AVAILABLE
    return S.search(req.query, req.user_id, req.top_n, tuple(req.modes), use_parse, use_explain, req.weights)


@app.get("/api/eval")
def evaluate(k: int = 10, llm: bool = True):
    return run_eval(k, llm and LLM_AVAILABLE)
