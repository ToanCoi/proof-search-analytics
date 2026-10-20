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


def fig_pareto(raw: str, out: str, runs: list[dict] = ()):
    for path in sorted(glob.glob(os.path.join(raw, "prune_sweep_*.csv"))):
        if path.endswith(("_per_theorem.csv", "_lost.csv", "_proof_paths.csv")):
            continue
        d = pd.read_csv(path).sort_values("tau")
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot(d.avg_states_expanded, d.proof_success_rate, marker="o", label="replay (ước lượng)")
        # live check: run có policy, cùng budget với baseline nguồn
        live = [r for r in runs if r.get("kind") == "collect"
                and r["parameters"].get("policy", "none") != "none"
                and r["parameters"]["budget"]["budget_id"] == d.budget_id.iloc[0]]
        if live:
            ax.scatter([r["metrics"]["avg_states_expanded"] for r in live],
                       [r["metrics"]["proof_success_rate"] for r in live], marker="*", s=160,
                       color="C3", zorder=3, label="live Lean")
            for r in live:
                ax.annotate(f"τ={r['parameters']['tau']:g} live",
                            (r["metrics"]["avg_states_expanded"], r["metrics"]["proof_success_rate"]),
                            fontsize=8, color="C3", xytext=(3, -10), textcoords="offset points")
        ax.legend(loc="lower right", fontsize=8)
        for _, r in d.iterrows():
            ax.annotate(f"τ={r.tau:g}", (r.avg_states_expanded, r.proof_success_rate),
                        fontsize=8, xytext=(3, 3), textcoords="offset points")
        ax.set_xlabel("States expanded / theorem (cost)")
        ax.set_ylabel("Proof success rate")
        run_id = os.path.basename(path)[len("prune_sweep_"):-4]
        ax.set_title(f"Pruning sweep — budget {d.budget_id.iloc[0]}, n={d.n.iloc[0]}")
        _save(fig, os.path.join(out, f"pareto_{run_id}.png"),
              {"source": path, "source_run": run_id, "repeats": int(d.repeats.iloc[0]),
               "budget": {"budget_id": d.budget_id.iloc[0], "max_calls": int(d.max_calls.iloc[0]),
                          "timeout_s": float(d.timeout_s.iloc[0])},
               "model_hash": d.model_hash.iloc[0] if "model_hash" in d else None,
               "live_runs": [r["run_id"] for r in live]})


def fig_scale(runs: list[dict], out: str):
    rows = [{"source": r["parameters"]["source"], "limit": r["parameters"]["limit_theorems"],
             "replication": r["parameters"].get("replication", 1),
             "theorems": r["metrics"]["theorems"], "events": r["metrics"]["events"],
             "runtime_s": r["metrics"]["runtime_s"], "events_per_s": r["metrics"]["events_per_s"],
             "lake_bytes": r["metrics"]["lake_bytes"], "run_id": r["run_id"]}
            for r in runs if r.get("kind") == "aggregate" and not r["parameters"].get("run_id")]
    if not rows:
        return
    d = pd.DataFrame(rows)
    table = (d.groupby(["source", "replication", "limit", "theorems", "events"])
             .agg(runtime_median=("runtime_s", "median"), runtime_min=("runtime_s", "min"),
                  runtime_max=("runtime_s", "max"), events_per_s_median=("events_per_s", "median"),
                  repeats=("runtime_s", "size"), lake_bytes=("lake_bytes", "max"))
             .reset_index().sort_values(["source", "events"]))
    table.to_csv(os.path.join(out, "scale_aggregate.csv"), index=False)
    print("-> scale_aggregate.csv\n", table.to_string(index=False))
    fig, ax = plt.subplots(figsize=(6, 4))
    for (src, rep), g in table.groupby(["source", table.replication > 1]):
        label = f"{src} (replicated ×{'/'.join(map(str, g.replication))})" if rep else src
        ax.errorbar(g.events.to_numpy(), g.runtime_median.to_numpy(),
                    yerr=[(g.runtime_median - g.runtime_min).to_numpy(),
                          (g.runtime_max - g.runtime_median).to_numpy()],
                    marker="s" if rep else "o", mfc="none" if rep else None, ls="--" if rep else "-",
                    capsize=3, label=label)
    ax.set_xscale("log")
    ax.set_xlabel("Events (log)")
    ax.set_ylabel("Spark aggregation runtime (s), median [min–max]")
    ax.legend(fontsize=8)
    _save(fig, os.path.join(out, "scale_aggregate.png"),
          {"source_runs": d.run_id.tolist(), "repeats": table.repeats.tolist(),
           "note": "replication>1 = lake nhân bản (scripts/replicate_lake.py), chỉ dùng đo runtime"})


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


def table_pruning_losses(raw: str, out: str):
    """Bài baseline chứng minh được nhưng mất khi prune: nguyên nhân + domain (từ prune_sweep)."""
    for lost_path in sorted(glob.glob(os.path.join(raw, "prune_sweep_*_lost.csv"))):
        run_id = os.path.basename(lost_path)[len("prune_sweep_"):-len("_lost.csv")]
        paths_csv = os.path.join(raw, f"prune_sweep_{run_id}_proof_paths.csv")
        if not os.path.exists(paths_csv):
            continue
        budget = pd.read_csv(os.path.join(raw, f"prune_sweep_{run_id}.csv")).budget_id.iloc[0]
        lost, paths = pd.read_csv(lost_path), pd.read_csv(paths_csv)
        info = paths.groupby("theorem_id").agg(domain=("domain", "first"), path=("path", "first"),
                                               min_score=("min_score", "first"))
        rows = []
        for _, r in lost.iterrows():
            steps = paths[paths.theorem_id == r.theorem_id]
            cut = steps[steps.score < r.tau]
            i = info.loc[r.theorem_id]
            rows.append({"tau": r.tau, "theorem_id": r.theorem_id, "domain": i.domain,
                         "replay_status": r.status, "baseline_proof": i.path,
                         "min_path_score": i.min_score,
                         "pruned_proof_tactics": " ; ".join(cut.tactic) if len(cut) else "",
                         "cause": "proof tactic pruned" if len(cut) else
                                  ("left baseline trace (unknown)" if r.status == "unknown" else "budget on other branch")})
        d = pd.DataFrame(rows)
        d.to_csv(os.path.join(out, f"pruning_losses_{budget}.csv"), index=False)
        if not d.empty:
            (d.groupby(["tau", "cause"]).size().unstack(fill_value=0)
             .to_csv(os.path.join(out, f"pruning_losses_{budget}_by_cause.csv")))
            n_dom = info.domain.value_counts().rename("proved_baseline")
            (d.groupby(["tau", "domain"]).size().unstack(0, fill_value=0).join(n_dom, how="right")
             .fillna(0).astype(int).to_csv(os.path.join(out, f"pruning_losses_{budget}_by_domain.csv")))
        print(f"-> pruning_losses_{budget}.csv")


def invalid_run_ids(raw: str) -> set[str]:
    """Run bị loại (có ghi lý do) trong results/raw/invalid_runs.json — không đưa vào hình/bảng."""
    path = os.path.join(raw, "invalid_runs.json")
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {r["run_id"] for r in json.load(f)["invalid_runs"]}


def table_search_budget(runs: list[dict], out: str):
    rows = [{"run_id": r["run_id"], "run_name": r["parameters"]["run_name"], "data_version": r["data_version"],
             "budget_id": r["parameters"]["budget"]["budget_id"],
             "max_calls": r["parameters"]["budget"]["max_calls"],
             "timeout_s": r["parameters"]["budget"]["timeout_s"],
             "policy": r["parameters"].get("policy", "none"), "tau": r["parameters"].get("tau", 0.0),
             **{k: r["metrics"].get(k) for k in ("n", "proof_success_rate", "avg_states_expanded",
                                                 "avg_lean_s", "avg_wall_s", "budget_exhausted_rate",
                                                 "unknown_rate", "repl_restarts")}}
            for r in runs if r.get("kind") == "collect"]
    if not rows:
        return
    d = pd.DataFrame(rows)
    d.to_csv(os.path.join(out, "search_runs.csv"), index=False)
    # lặp lại cùng config -> median [min–max] (wall time phụ thuộc độ trễ Lean)
    agg = {f"{m}_{f}": (m, f) for m in ("proof_success_rate", "avg_states_expanded", "avg_wall_s")
           for f in ("median", "min", "max")}
    summary = (d.groupby(["run_name", "budget_id", "policy", "tau"])
               .agg(repeats=("run_id", "size"), **agg).reset_index())
    summary.to_csv(os.path.join(out, "search_summary.csv"), index=False)
    print("-> search_runs.csv, search_summary.csv\n", summary.to_string(index=False))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="results/raw")
    ap.add_argument("--out", default="results/figures")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    bad = invalid_run_ids(args.raw)
    runs = [r for r in read_runs(os.path.join(args.raw, "runs.jsonl"))
            if r["run_id"] not in bad and r.get("data_version") not in bad]
    fig_pareto(args.raw, args.out, runs)
    fig_scale(runs, args.out)
    fig_predictor(args.raw, args.out)
    table_search_budget(runs, args.out)
    table_pruning_losses(args.raw, args.out)


if __name__ == "__main__":
    main()
