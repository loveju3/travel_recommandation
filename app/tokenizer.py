"""Jieba 斷詞：重現「舊方法」的關鍵字搜尋 baseline。"""
import logging
import re

import jieba

from .config import DATA_DIR

jieba.setLogLevel(logging.WARNING)
_userdict = DATA_DIR / "userdict.txt"
if _userdict.exists():
    jieba.load_userdict(str(_userdict))

STOPWORDS = set("""
的 了 和 與 及 或 是 在 我 我們 你 想 想要 要 去 有 一下 一些 一個 可以 這 那 也 都 很 嗎 吧 呢 啊 喔 個 跟 給 讓 會 能 就 還 再
不 不要 沒有 沒 最 比較 好 一點 適合 行程 旅遊 旅行 推薦 哪裡 什麼 怎麼 如何 自己 時候 東西 地方 看看 玩 玩玩
""".split())
_punct = re.compile(r"^[\s\W_]+$", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """搜尋引擎模式斷詞（長詞會再切出子詞），去除停用詞與標點。"""
    out = []
    for t in jieba.cut_for_search(text or ""):
        t = t.strip().lower()
        if not t or _punct.match(t) or t in STOPWORDS:
            continue
        out.append(t)
    return out


def to_tsquery_str(tokens: list[str]) -> str:
    """把 tokens 組成 OR 查詢：'北海道' | '溫泉'"""
    uniq = list(dict.fromkeys(tokens))
    return " | ".join("'" + t.replace("'", "''").replace("\\", "") + "'" for t in uniq)
