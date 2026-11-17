"""離線評估：Recall@K、NDCG@K、MRR，比較 Jieba / 向量 / Hybrid（不含個人化，避免使用者偏好干擾）。"""
import json
import math

from .config import DATA_DIR
from .search import run_hybrid, run_keyword, run_vector
from . import llm


def _metrics(ranked, relevant, k):
    rel = set(relevant)
    hits = [1 if pid in rel else 0 for pid in ranked[:k]]
    recall = sum(hits) / min(len(rel), k) if rel else 0.0
    dcg = sum(h / math.log2(i + 2) for i, h in enumerate(hits))
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(rel), k)))
    ndcg = dcg / idcg if idcg else 0.0
    mrr = next((1 / (i + 1) for i, h in enumerate(hits) if h), 0.0)
    prec = sum(hits) / k
    return {"recall": recall, "ndcg": ndcg, "mrr": mrr, "precision": prec}


def run_eval(k=10, use_llm_parse=True):
    queries = json.loads((DATA_DIR / "eval_queries.json").read_text(encoding="utf-8"))
    modes = ["keyword", "vector", "hybrid"]
    per_query, totals = [], {m: {"recall": 0, "ndcg": 0, "mrr": 0, "precision": 0} for m in modes}
    for q in queries:
        row = {"query": q["query"], "n_relevant": len(q["relevant"])}
        kw, _ = run_keyword(q["query"], k)
        vs = run_vector(q["query"], k)
        parsed = llm.parse_query(q["query"]) if use_llm_parse else None
        if parsed and parsed.get("error"):
            parsed = None
        hy, _ = run_hybrid(q["query"], None, parsed, k, {"relevance": 0.85, "personal": 0, "business": 0.15}, {})
        for m, res in zip(modes, (kw, vs, hy)):
            met = _metrics([r["id"] for r in res], q["relevant"], k)
            row[m] = {kk: round(v, 3) for kk, v in met.items()}
            for kk in met:
                totals[m][kk] += met[kk]
        per_query.append(row)
    n = len(queries)
    summary = {m: {kk: round(v / n, 3) for kk, v in totals[m].items()} for m in modes}
    return {"k": k, "llm_parse": use_llm_parse and llm.LLM_AVAILABLE, "summary": summary, "per_query": per_query}
