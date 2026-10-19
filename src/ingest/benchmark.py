"""Nguồn A: LeanDojo Benchmark 4 (JSON) -> Parquet trace lake (source=benchmark).

Mỗi tactic trong chứng minh mẫu của người viết = 1 event; chuỗi tactic là đường thẳng
(parent = bước trước). Xử lý theo lô để không giữ cả train.json dưới dạng rows trong RAM.

    python -m src.ingest.benchmark --bench-dir data/raw/leandojo_benchmark_4/random --data-version lb4-v5
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time

import pyarrow.parquet as pq

from src.common.runlog import log_run, new_run_id
from src.common.schema import PARTITION_COLS, SCHEMA_VERSION, domain_of, to_table, validate

SPLITS = ("train", "val", "test")


def theorem_to_rows(t: dict, split: str, data_version: str) -> list[dict]:
    rows = []
    for i, tt in enumerate(t.get("traced_tactics") or []):
        done = tt["state_after"].strip() == "no goals"
        rows.append(dict(
            schema_version=SCHEMA_VERSION, source="benchmark", run_id=f"bench-{data_version}",
            data_version=data_version, split=split, theorem_id=t["full_name"],
            file_path=t["file_path"], domain=domain_of(t["file_path"]),
            step_idx=i, parent_step_idx=i - 1 if i else None, depth=i,
            state_before=tt["state_before"], tactic=tt["tactic"],
            state_after="" if done else tt["state_after"],
            outcome="finished" if done else "progress",
            budget_id="na", policy="human"))
    return rows


def ingest(bench_dir: str, out: str, data_version: str, limit: int = 0,
           batch_size: int = 5000, clean: bool = True) -> dict:
    if clean:
        shutil.rmtree(os.path.join(out, "source=benchmark"), ignore_errors=True)
    stats = {}
    for split in SPLITS:
        path = os.path.join(bench_dir, f"{split}.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            thms = json.load(f)
        thms.sort(key=lambda t: t["full_name"])          # thứ tự ổn định -> limit tái lập được
        if limit:
            thms = thms[:limit]
        n_events = 0
        for b in range(0, len(thms), batch_size):
            rows = [r for t in thms[b:b + batch_size] for r in theorem_to_rows(t, split, data_version)]
            if not rows:
                continue
            table = to_table(rows)
            errs = validate(table)
            if errs:
                raise ValueError(f"{split} batch {b}: {errs}")
            pq.write_to_dataset(table, out, partition_cols=PARTITION_COLS,
                                basename_template=f"bench-{split}-b{b // batch_size:04d}-{{i}}.parquet",
                                compression="zstd", existing_data_behavior="overwrite_or_ignore")
            n_events += table.num_rows
        stats[split] = {"theorems": len(thms), "events": n_events}
        print(f"{split}: {len(thms)} theorems, {n_events} events")
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench-dir", default="data/raw/leandojo_benchmark_4/random")
    ap.add_argument("--data-version", required=True)
    ap.add_argument("--limit", type=int, default=0, help="số định lý mỗi split (0 = tất cả)")
    ap.add_argument("--batch-size", type=int, default=5000)
    ap.add_argument("--out", default="data/lake/events")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    stats = ingest(args.bench_dir, args.out, args.data_version, args.limit, args.batch_size)
    runtime = time.perf_counter() - t0
    log_run(new_run_id("ingest"), "ingest", vars(args), {"splits": stats, "runtime_s": runtime},
            status="ok", data_version=args.data_version)


if __name__ == "__main__":
    main()
