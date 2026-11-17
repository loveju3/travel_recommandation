"""
檢查 .env 設定是否正確：Neon 連線、pgvector、OpenAI embedding、OpenAI 對話模型。
用法：python scripts/check_setup.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402

ok = True


def step(name, fn):
    global ok
    try:
        msg = fn()
        print(f"✅ {name}：{msg}")
    except Exception as e:
        ok = False
        print(f"❌ {name}：{type(e).__name__}: {e}")


def check_env():
    missing = [k for k in ("DATABASE_URL", "OPENAI_API_KEY") if not getattr(config, k)]
    if missing and not (config.EMBED_PROVIDER == "fake" and missing == ["OPENAI_API_KEY"]):
        raise RuntimeError(f".env 缺少 {missing}")
    if "sslmode=require" not in config.DATABASE_URL and "neon.tech" in config.DATABASE_URL:
        raise RuntimeError("Neon 連線字串需要帶 ?sslmode=require")
    return f"EMBED_PROVIDER={config.EMBED_PROVIDER}, EMBED_MODEL={config.EMBED_MODEL}, CHAT_MODEL={config.CHAT_MODEL}"


def check_db():
    import psycopg
    with psycopg.connect(config.DATABASE_URL, connect_timeout=15) as c:
        ver = c.execute("select version()").fetchone()[0].split(",")[0]
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        vv = c.execute("select extversion from pg_extension where extname='vector'").fetchone()[0]
        n = c.execute("select to_regclass('public.products') is not null").fetchone()[0]
        cnt = c.execute("select count(*) from products").fetchone()[0] if n else 0
    return f"{ver}｜pgvector {vv}｜products 筆數 {cnt}" + ("（尚未匯入，請執行 scripts/ingest.py）" if not cnt else "")


def check_embed():
    from app.embeddings import embed_batch
    v = embed_batch(["北海道溫泉之旅"])[0]
    if len(v) != config.EMBED_DIM:
        raise RuntimeError(f"向量維度 {len(v)} ≠ EMBED_DIM {config.EMBED_DIM}")
    return f"{config.EMBED_MODEL} 回傳 {len(v)} 維向量"


def check_chat():
    if not config.LLM_AVAILABLE:
        return "LLM 已停用（DISABLE_LLM=1 或沒有 API key），搜尋仍可運作"
    from app.llm import parse_query
    r = parse_query("五萬以內帶爸媽去日本泡溫泉")
    if r.get("error"):
        raise RuntimeError(r["error"])
    return f"{config.CHAT_MODEL} 解析結果：目的地={r.get('destinations')}, 預算上限={r.get('max_price')}, 標籤={r.get('tags')}"


step("讀取 .env", check_env)
step("連線 Neon / pgvector", check_db)
step("OpenAI Embedding", check_embed)
step("OpenAI 對話模型（query 解析）", check_chat)
print("\n全部通過，可以執行 ingest 與啟動服務。" if ok else "\n有項目失敗，請對照 SETUP.md 的「常見問題」排除。")
sys.exit(0 if ok else 1)
