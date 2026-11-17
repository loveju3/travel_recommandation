"""
離線評估：python scripts/eval.py [--k 10] [--no-llm]
輸出三種方法的 Recall@K / NDCG@K / MRR，並存到 data/eval_results.json
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.evaluate import run_eval  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--k", type=int, default=10)
ap.add_argument("--no-llm", action="store_true", help="Hybrid 不使用 LLM query 解析")
args = ap.parse_args()

res = run_eval(args.k, not args.no_llm)
name = {"keyword": "Jieba 關鍵字（舊）", "vector": "Embedding 向量", "hybrid": "Hybrid（RRF+過濾）"}
print(f"\n評估 {len(res['per_query'])} 組 query，K={res['k']}，LLM 解析={'開' if res['llm_parse'] else '關'}\n")
print(f"| 方法 | Recall@{args.k} | NDCG@{args.k} | MRR | Precision@{args.k} |")
print("|---|---|---|---|---|")
for m, v in res["summary"].items():
    print(f"| {name[m]} | {v['recall']:.3f} | {v['ndcg']:.3f} | {v['mrr']:.3f} | {v['precision']:.3f} |")
print("\n各 query NDCG：")
for q in res["per_query"]:
    print(f"  {q['keyword']['ndcg']:.2f} / {q['vector']['ndcg']:.2f} / {q['hybrid']['ndcg']:.2f}  {q['query']}")
(ROOT / "data/eval_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print("\n已存到 data/eval_results.json")
