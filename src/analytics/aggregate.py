"""Khối 4 — Spark aggregation trên trace lake.

Bảng: tactic_stats (tần suất + failure rate), outcomes (tactic x outcome, pivot), branching
(theo depth), per_theorem (depth, states expanded, proved), transitions (tactic cha -> con dọc
cây), position (tactic trước -> sau theo thứ tự bước, window lag).

    python -m src.analytics.aggregate --source benchmark --limit-theorems 1000
"""
from __future__ import annotations

import argparse
import os
import pathlib
import time

from src.common.runlog import log_run, new_run_id
from src.common.schema import OUTCOMES

TABLES = ("tactic_stats", "outcomes", "branching", "per_theorem", "transitions", "position")
# Chỉ đọc các cột cần cho tổng hợp (Parquet là columnar -> không đọc text state_before/after)
COLS = ("run_id", "theorem_id", "step_idx", "parent_step_idx", "depth", "tactic", "outcome",
        "elapsed_ms", "split", "domain", "budget_id", "policy", "tau")


def get_spark(driver_memory: str = "6g", shuffle_partitions: int = 64):
    from pyspark.sql import SparkSession
    return (SparkSession.builder.appName("g7-aggregate")
            .master(os.environ.get("SPARK_MASTER", "local[*]"))
            .config("spark.driver.memory", driver_memory)
            .config("spark.sql.shuffle.partitions", str(shuffle_partitions))
            .config("spark.sql.adaptive.enabled", "true")
            .config("spark.ui.showConsoleProgress", "false")
            .getOrCreate())


def load_events(spark, lake: str, source: str, limit_theorems: int = 0, run_id: str | None = None):
    from pyspark.sql import functions as F
    ev = (spark.read.parquet(lake)
          .filter(F.col("source") == source)                 # partition pruning
          .select(*COLS)                                     # column pruning
          .withColumn("tactic_head", F.split(F.trim("tactic"), r"\s+").getItem(0)))
    if run_id:
        ev = ev.filter(F.col("run_id") == run_id)
    if limit_theorems:
        keep = (ev.select("theorem_id").distinct().orderBy("theorem_id").limit(limit_theorems))
        ev = ev.join(F.broadcast(keep), "theorem_id")      # bảng nhỏ -> broadcast, tránh shuffle bảng lớn
    return ev


def aggregate(ev) -> dict:
    """ev: DataFrame event (đã có tactic_head). Trả về dict tên -> DataFrame (lazy)."""
    from pyspark.sql import Window, functions as F
    k = ["run_id", "theorem_id"]
    is_err = (F.col("outcome") == "error").cast("double")

    tactic_stats = (ev.groupBy("tactic_head")
                    .agg(F.count("*").alias("n"),
                         F.avg(is_err).alias("fail_rate"),
                         F.avg("elapsed_ms").alias("avg_elapsed_ms"))
                    .orderBy(F.desc("n"), "tactic_head"))

    # phân bố kết quả mỗi tactic (pivot): lời gọi "duplicate" = trả về state đã gặp -> tốn Lean, vô ích
    outcomes = (ev.groupBy("tactic_head").pivot("outcome", list(OUTCOMES)).count().fillna(0)
                .orderBy("tactic_head"))

    # branching factor: số con "progress" mỗi state (state = event cha), trung bình theo depth
    branching = (ev.groupBy(*k, "parent_step_idx", "depth")
                 .agg(F.sum((F.col("outcome") == "progress").cast("int")).alias("children"),
                      F.count("*").alias("tried"))
                 .groupBy("depth")
                 .agg(F.avg("children").alias("avg_branching"),
                      F.avg("tried").alias("avg_tried"),
                      F.count("*").alias("n_states"))
                 .orderBy("depth"))

    per_theorem = (ev.groupBy(*k, "split", "domain", "budget_id", "policy", "tau")
                   .agg(F.max("depth").alias("max_depth"),
                        F.count("*").alias("states_expanded"),
                        F.max((F.col("outcome") == "finished").cast("int")).alias("proved"),
                        F.avg(is_err).alias("fail_rate"),
                        F.sum("elapsed_ms").alias("lean_ms"))
                   .orderBy(*k))

    # chuyển tiếp cha -> con dọc cây: self-join (cả 2 phía lớn -> SortMergeJoin + shuffle)
    parent = ev.select(*k, F.col("step_idx").alias("parent_step_idx"),
                       F.col("tactic_head").alias("prev_tactic"))
    transitions = (ev.join(parent, k + ["parent_step_idx"], "left")
                   .fillna({"prev_tactic": "<start>"})
                   .groupBy("prev_tactic", "tactic_head").count()
                   .orderBy(F.desc("count"), "prev_tactic", "tactic_head"))

    # window: tactic liền trước theo thứ tự bước (với benchmark = chứng minh mẫu)
    w = Window.partitionBy(*k).orderBy("step_idx")
    position = (ev.withColumn("prev_in_order", F.coalesce(F.lag("tactic_head").over(w), F.lit("<start>")))
                .groupBy("prev_in_order", "tactic_head").count()
                .orderBy(F.desc("count"), "prev_in_order", "tactic_head"))

    return {"tactic_stats": tactic_stats, "outcomes": outcomes, "branching": branching,
            "per_theorem": per_theorem, "transitions": transitions, "position": position}


def explain_string(df, mode: str = "formatted") -> str:
    """Physical plan dạng text (như df.explain) để lưu vào results/raw."""
    return df._sc._jvm.PythonSQLUtils.explainString(df._jdf.queryExecution(), mode)


def lake_bytes(lake: str, source: str) -> int:
    root = pathlib.Path(lake) / f"source={source}"
    return sum(p.stat().st_size for p in root.rglob("*.parquet")) if root.exists() else 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake", default="data/lake/events")
    ap.add_argument("--source", default="benchmark")
    ap.add_argument("--run-id", default=None, help="chỉ lấy 1 run (source=search)")
    ap.add_argument("--limit-theorems", type=int, default=0)
    ap.add_argument("--out", default="results/raw/agg")
    ap.add_argument("--driver-memory", default="6g")
    ap.add_argument("--shuffle-partitions", type=int, default=64)
    ap.add_argument("--repeat-idx", type=int, default=0, help="lần lặp (đo runtime ≥3 lần)")
    ap.add_argument("--explain", action="store_true", help="ghi physical plan vào results/raw/spark_plans")
    ap.add_argument("--tag", default=None, help="tên thư mục output (mặc định suy từ source/limit)")
    ap.add_argument("--replication", type=int, default=1, help="lake nhân bản ×k (scripts/replicate_lake.py)")
    args = ap.parse_args(argv)

    spark = get_spark(args.driver_memory, args.shuffle_partitions)
    t0 = time.perf_counter()
    ev = load_events(spark, args.lake, args.source, args.limit_theorems, args.run_id).cache()
    n_events = ev.count()
    n_theorems = ev.select("run_id", "theorem_id").distinct().count()
    tag = args.tag or (f"{args.source}_n{args.limit_theorems or 'all'}" + (f"_{args.run_id}" if args.run_id else ""))
    out_dir = pathlib.Path(args.out) / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = aggregate(ev)
    sizes = {}
    for name, df in tables.items():
        pdf = df.toPandas()                    # bảng tổng hợp nhỏ -> CSV trong results/raw
        pdf.to_csv(out_dir / f"{name}.csv", index=False)
        sizes[name] = len(pdf)
    runtime = time.perf_counter() - t0
    if args.explain:                           # plan trên DataFrame chưa cache: thấy được join/Exchange
        plan_dir = pathlib.Path(args.out).parent / "spark_plans" / tag
        plan_dir.mkdir(parents=True, exist_ok=True)
        raw = aggregate(load_events(spark, args.lake, args.source, args.limit_theorems, args.run_id))
        for name, df in raw.items():
            (plan_dir / f"{name}.txt").write_text(explain_string(df), encoding="utf-8", newline="\n")
    metrics = {"events": n_events, "theorems": n_theorems, "runtime_s": runtime,
               "events_per_s": n_events / runtime if runtime else None,
               "lake_bytes": lake_bytes(args.lake, args.source), "rows_out": sizes,
               "spark_cores": spark.sparkContext.defaultParallelism}
    log_run(new_run_id(f"agg-{tag}"), "aggregate", vars(args), metrics, status="ok",
            data_version=f"see {pathlib.Path(args.lake).parent.as_posix()}/manifest.json")
    print(f"{tag}: {n_events} events, {n_theorems} theorems in {runtime:.1f}s -> {out_dir}")
    spark.stop()


if __name__ == "__main__":
    main()
