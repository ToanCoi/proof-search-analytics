"""Chọn tập định lý cố định (version hóa bằng tên file + seed) cho search.

Hai nguồn:
- Benchmark 4 (backend lean/LeanDojo): ưu tiên chứng minh ngắn để search cố định có cơ hội thành công.
- miniF2F JSONL (backend repl/LeanInteract): mỗi dòng có formal_statement + header.

    python -m src.search.select --n 100 --seed 42 --out data/selections/thm_100_s42.jsonl
    python -m src.search.select --minif2f data/raw/minif2f/minif2f.jsonl --n 100 --out data/selections/minif2f_100_s42.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re

KEYS = ("url", "commit", "file_path", "full_name")
MINIF2F_SOURCE = "https://github.com/deepseek-ai/DeepSeek-Prover-V1.5/blob/2c4ba91/datasets/minif2f.jsonl"


def select(theorems: list[dict], n: int, max_steps: int, seed: int) -> list[dict]:
    pool = [t for t in theorems if 0 < len(t.get("traced_tactics") or []) <= max_steps]
    pool.sort(key=lambda t: t["full_name"])          # thứ tự ổn định trước khi lấy mẫu
    picked = random.Random(seed).sample(pool, min(n, len(pool)))
    return [{k: t.get(k) for k in KEYS} for t in picked]


def minif2f_domain(name: str) -> str:
    """amc12a_2019_p21 -> amc; mathd_algebra_10 -> mathd_algebra; imo_1959_p1 -> imo."""
    m = re.match(r"(mathd_[a-z]+|[a-z]+)", name)
    return m.group(1) if m else "Other"


def minif2f_to_meta(row: dict) -> dict:
    return {"full_name": row["name"], "file_path": f"miniF2F/{row['split']}",
            "split": row["split"], "domain": minif2f_domain(row["name"]),
            "statement": row["formal_statement"], "header": row.get("header", ""),
            "url": MINIF2F_SOURCE, "commit": "2c4ba91"}


def select_minif2f(rows: list[dict], n: int, seed: int, splits: tuple[str, ...]) -> list[dict]:
    pool = sorted((r for r in rows if r["split"] in splits), key=lambda r: r["name"])
    picked = random.Random(seed).sample(pool, min(n, len(pool)))
    return [minif2f_to_meta(r) for r in picked]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default="data/raw/leandojo_benchmark_4/random/test.json")
    ap.add_argument("--minif2f", help="đường dẫn minif2f.jsonl (thay cho --bench)")
    ap.add_argument("--splits", default="valid,test", help="split miniF2F được chọn")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--max-steps", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.minif2f:
        with open(args.minif2f, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        picked = select_minif2f(rows, args.n, args.seed, tuple(args.splits.split(",")))
    else:
        with open(args.bench, encoding="utf-8") as f:
            picked = select(json.load(f), args.n, args.max_steps, args.seed)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(t, ensure_ascii=False) + "\n" for t in picked)
    print(f"{len(picked)} theorems -> {args.out}")


if __name__ == "__main__":
    main()
