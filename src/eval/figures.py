"""Sinh mọi hình/bảng từ results/raw (không vẽ tay). Mỗi hình có file .meta.json đi kèm ghi
máy, phần mềm, seed, timeout/budget, số lần lặp và run_id nguồn.

    python -m src.eval.figures
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from src.common.runlog import machine_info, read_runs, software_info  # noqa: E402


def _save(fig, path: str, meta: dict):
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    meta = {"machine": machine_info(), "software": software_info(), **meta}
    with open(os.path.splitext(path)[0] + ".meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, default=str, ensure_ascii=False)
    print("->", path)


def fig_pareto(raw: str, out: str):
    for path in sorted(glob.glob(os.path.join(raw, "prune_sweep_*.csv"))):
        if path.endswith(("_per_theorem.csv", "_lost.csv")):
            continue
        d = pd.read_csv(path).sort_values("tau")
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot(d.avg_states_expanded, d.proof_success_rate, marker="o")
        for _, r in d.iterrows():
            ax.annotate(f"τ={r.tau:g}", (r.avg_states_expanded, r.proof_success_rate),
                        fontsize=8, xytext=(3, 3), textcoords="offset points")
        ax.set_xlabel("States expanded / theorem (cost)")
        ax.set_ylabel("Proof success rate (replay)")
        run_id = os.path.basename(path)[len("prune_sweep_"):-4]
        ax.set_title(f"Pruning sweep — budget {d.budget_id.iloc[0]}, n={d.n.iloc[0]}")
        _save(fig, os.path.join(out, f"pareto_{run_id}.png"),
              {"source": path, "source_run": run_id, "repeats": int(d.repeats.iloc[0]),
               "budget": {"budget_id": d.budget_id.iloc[0], "max_calls": int(d.max_calls.iloc[0]),
                          "timeout_s": float(d.timeout_s.iloc[0])},
               "model_hash": d.model_hash.iloc[0] if "model_hash" in d else None})


def fig_scale(runs: list[dict], out: str):
    rows = [{"source": r["parameters"]["source"], "limit": r["parameters"]["limit_theorems"],
             "theorems": r["metrics"]["theorems"], "events": r["metrics"]["events"],
             "runtime_s": r["metrics"]["runtime_s"], "events_per_s": r["metrics"]["events_per_s"],
             "lake_bytes": r["metrics"]["lake_bytes"], "run_id": r["run_id"]}
            for r in runs if r.get("kind") == "aggregate" and not r["parameters"].get("run_id")]
    if not rows:
        return
    d = pd.DataFrame(rows)
    table = (d.groupby(["source", "limit", "theorems", "events"])
             .agg(runtime_median=("runtime_s", "median"), runtime_min=("runtime_s", "min"),
                  runtime_max=("runtime_s", "max"), events_per_s_median=("events_per_s", "median"),
                  repeats=("runtime_s", "size"), lake_bytes=("lake_bytes", "max"))
             .reset_index().sort_values(["source", "events"]))
    table.to_csv(os.path.join(out, "scale_aggregate.csv"), index=False)
    print("-> scale_aggregate.csv\n", table.to_string(index=False))
    fig, ax = plt.subplots(figsize=(6, 4))
    for src, g in table.groupby("source"):
        ax.errorbar(g.events.to_numpy(), g.runtime_median.to_numpy(),
                    yerr=[(g.runtime_median - g.runtime_min).to_numpy(),
                          (g.runtime_max - g.runtime_median).to_numpy()],
                    marker="o", capsize=3, label=src)
    ax.set_xscale("log")
    ax.set_xlabel("Events (log)")
    ax.set_ylabel("Spark aggregation runtime (s), median [min–max]")
    ax.legend()
    _save(fig, os.path.join(out, "scale_aggregate.png"),
          {"source_runs": d.run_id.tolist(), "repeats": table.repeats.tolist()})


def fig_predictor(raw: str, out: str):
    path = os.path.join(raw, "predictor_metrics.json")
    if not os.path.exists(path):
        return
    m = json.load(open(path, encoding="utf-8"))
    models = [k for k in m if isinstance(m[k], dict) and "top1" in m[k]]
    ks = ["top1", "top3", "top5", "top10"]
    fig, ax = plt.subplots(figsize=(6, 4))
    width = 0.8 / len(models)
    for i, name in enumerate(models):
        ax.bar([j + i * width for j in range(len(ks))], [m[name][k] for k in ks], width, label=name)
    ax.set_xticks([j + width * (len(models) - 1) / 2 for j in range(len(ks))], ks)
    ax.set_ylabel("Accuracy (test split)")
    ax.set_ylim(0, 1)
    ax.legend()
    _save(fig, os.path.join(out, "predictor_topk.png"),
          {"source": path, "model_hash": m.get("model_hash"), "params": m.get("params"),
           "seed": (m.get("params") or {}).get("seed")})


def table_search_budget(runs: list[dict], out: str):
    rows = [{"run_id": r["run_id"], "data_version": r["data_version"],
             "budget_id": r["parameters"]["budget"]["budget_id"],
             "max_calls": r["parameters"]["budget"]["max_calls"],
             "timeout_s": r["parameters"]["budget"]["timeout_s"],
             "policy": r["parameters"].get("policy", "none"), "tau": r["parameters"].get("tau", 0.0),
             **{k: r["metrics"][k] for k in ("n", "proof_success_rate", "avg_states_expanded",
                                             "avg_lean_s", "avg_wall_s", "budget_exhausted_rate")}}
            for r in runs if r.get("kind") == "collect"]
    if rows:
        pd.DataFrame(rows).to_csv(os.path.join(out, "search_runs.csv"), index=False)
        print("-> search_runs.csv")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="results/raw")
    ap.add_argument("--out", default="results/figures")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    runs = read_runs(os.path.join(args.raw, "runs.jsonl"))
    fig_pareto(args.raw, args.out)
    fig_scale(runs, args.out)
    fig_predictor(args.raw, args.out)
    table_search_budget(runs, args.out)


if __name__ == "__main__":
    main()
