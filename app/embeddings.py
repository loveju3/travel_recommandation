"""文字 → 向量。正式用 OpenAI Embedding API；fake 模式僅供離線測試流程。"""
import hashlib
from functools import lru_cache

import numpy as np

from .config import EMBED_DIM, EMBED_MODEL, EMBED_PROVIDER, OPENAI_API_KEY

_client = None


def _openai():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def _fake(text: str) -> np.ndarray:
    v = np.zeros(EMBED_DIM, dtype=np.float32)
    grams = list(text) + [text[i:i + 2] for i in range(len(text) - 1)]
    for g in grams:
        h = int(hashlib.md5(g.encode()).hexdigest(), 16)
        v[h % EMBED_DIM] += 1.0 if (h >> 64) & 1 else -1.0
    n = np.linalg.norm(v)
    return v / n if n else v


def embed_batch(texts: list[str], batch_size: int = 64) -> list[np.ndarray]:
    if EMBED_PROVIDER == "fake":
        return [_fake(t) for t in texts]
    out = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i:i + batch_size]
        kwargs = {"model": EMBED_MODEL, "input": chunk}
        if EMBED_MODEL.startswith("text-embedding-3"):
            kwargs["dimensions"] = EMBED_DIM
        resp = _openai().embeddings.create(**kwargs)
        out.extend(np.array(d.embedding, dtype=np.float32) for d in resp.data)
    return out


@lru_cache(maxsize=2048)
def _embed_query_cached(text: str) -> tuple:
    return tuple(embed_batch([text])[0].tolist())


def embed_query(text: str) -> np.ndarray:
    """查詢向量會快取：同一個 query 不重複呼叫 API（實務上可換成 Redis）。"""
    return np.array(_embed_query_cached(text.strip()), dtype=np.float32)
