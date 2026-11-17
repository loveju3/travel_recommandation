import atexit
from contextlib import contextmanager

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import DATABASE_URL

_pool = None


def _configure(conn):
    register_vector(conn)


def pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("請在 .env 設定 DATABASE_URL（Neon 連線字串）")
        _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=5, configure=_configure,
                               kwargs={"row_factory": dict_row}, open=True)
        atexit.register(_pool.close)
    return _pool


@contextmanager
def conn():
    with pool().connection() as c:
        yield c


def connect_raw():
    """給 ingest 腳本使用的單一連線。"""
    c = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return c
