import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# openai：正式 demo；fake：不需 API key 的離線測試模式（字元 n-gram 雜湊，沒有語意能力）
EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "openai")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")
EMBED_DIM = int(os.getenv("EMBED_DIM", "1536"))
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini")

LLM_AVAILABLE = bool(OPENAI_API_KEY) and os.getenv("DISABLE_LLM", "0") != "1"

DATA_DIR = ROOT / "data"
