"""Khối 1 — Trace collector: chạy best-first trên tập định lý cố định, ghi event vào lake.

    python -m src.search.collect --config configs/search_baseline_M.yaml

Config (YAML): run_name, data_version, theorems, n_theorems, budget{...}, workers, seed,
backend (lean | repl | toy), dojo_timeout_s, policy (none | đường dẫn model), tau, candidates (tùy chọn).
backend=repl (LeanInteract) đọc thêm: lean_version, require_mathlib, tactic_timeout_s, restart_every.
Mỗi worker mở Dojo trong process của nó (Dojo không pickle được), ghi 1 file nhỏ vào
staging; cuối run compact thành file lớn trong lake (tránh small-files problem).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from multiprocessing import Pool

import pyarrow.parquet as pq
import yaml

from src.common.runlog import log_run, new_run_id
from src.common.schema import EVENT_SCHEMA, PARTITION_COLS, SCHEMA_VERSION, domain_of, to_table, validate
from src.search.core import CANDIDATES, PROVED, Budget, best_first

_POLICY = {}


def _policy(cfg):
    path = cfg.get("policy", "none")
    if path in (None, "none"):
        return None, "none"
    if path not in _POLICY:                    # nạp 1 lần / worker
        from src.model.policy import load_policy, model_hash
        _POLICY[path] = (load_policy(path), f"model:{model_hash(path)}")
    return _POLICY[path]


_REPL = {}


def _search(thm_meta, cfg, budget, policy, tau, candidates):
    backend = cfg.get("backend", "lean")
    if backend == "repl":                      # LeanInteract, 1 session / worker process
        from src.search.live_repl import ReplSession
        session = _REPL.setdefault("s", ReplSession(cfg))
        ps, init_pp = session.open(thm_meta["statement"], thm_meta.get("header", ""))
        return best_first(init_pp, session.apply_fn(ps, init_pp), budget, policy, tau, candidates)
    if backend == "toy":
        from src.search.toy import make_toy_apply, toy_init_state
        return best_first(toy_init_state(thm_meta["full_name"]), make_toy_apply(thm_meta["full_name"]),
                          budget, policy, tau, candidates)
    from lean_dojo import Dojo, LeanGitRepo, Theorem
    from src.search.live import make_live_apply
    repo = LeanGitRepo(thm_meta["url"], thm_meta["commit"])
    thm = Theorem(repo, thm_meta["file_path"], thm_meta["full_name"])
    with Dojo(thm, timeout=cfg.get("dojo_timeout_s", 600)) as (dojo, s0):
        return best_first(s0.pp, make_live_apply(dojo, s0), budget, policy, tau, candidates)


def run_one(job) -> dict:
    thm_meta, cfg, run_id, staging = job
    budget = Budget(**cfg["budget"])
    policy, policy_name = _policy(cfg)
    tau = float(cfg.get("tau", 0.0)) if policy else 0.0
    candidates = tuple(cfg.get("candidates") or CANDIDATES)
    t0 = time.perf_counter()
    try:
        events, status = _search(thm_meta, cfg, budget, policy, tau, candidates)
    except Exception as e:                     # không mở được định lý
        return {"theorem_id": thm_meta["full_name"], "status": f"init_error:{type(e).__name__}",
                "error": str(e)[:500], "states_expanded": 0, "lean_ms": 0.0, "wall_s": time.perf_counter() - t0}
    wall = time.perf_counter() - t0
    rows = [dict(ev, schema_version=SCHEMA_VERSION, source="search", run_id=run_id,
                 data_version=cfg["data_version"], split=thm_meta.get("split") or cfg.get("split", "test"),
                 theorem_id=thm_meta["full_name"], file_path=thm_meta["file_path"],
                 domain=thm_meta.get("domain") or domain_of(thm_meta["file_path"]),
                 budget_id=budget.budget_id,
                 max_calls=budget.max_calls, timeout_s=budget.timeout_s,
                 max_depth=budget.max_depth, policy=policy_name, tau=tau)
            for ev in events]
    if rows:
        name = "".join(c if c.isalnum() or c in "._-" else "_" for c in thm_meta["full_name"])[:150]
        pq.write_table(to_table(rows), os.path.join(staging, f"{name}.parquet"))
    return {"theorem_id": thm_meta["full_name"], "status": status, "states_expanded": len(events),
            "lean_ms": sum(e["elapsed_ms"] for e in events), "wall_s": wall}


def summarize(summary: list[dict]) -> dict:
    n = len(summary) or 1
    return {"n": len(summary),
            "proof_success_rate": sum(s["status"] == PROVED for s in summary) / n,
            "avg_states_expanded": sum(s["states_expanded"] for s in summary) / n,
            "avg_lean_s": sum(s["lean_ms"] for s in summary) / n / 1000,
            "avg_wall_s": sum(s["wall_s"] for s in summary) / n,
            "budget_exhausted_rate": sum(s["status"] == "budget_exhausted" for s in summary) / n,
            "init_error_rate": sum(s["status"].startswith("init_error") for s in summary) / n}


def collect(cfg: dict, lake: str = "data/lake/events", results: str = "results/raw",
            staging_root: str = "data/staging") -> tuple[str, dict]:
    run_id = new_run_id(cfg["run_name"])
    staging = os.path.join(staging_root, run_id)
    os.makedirs(staging, exist_ok=True)
    with open(cfg["theorems"], encoding="utf-8") as f:
        thms = [json.loads(line) for line in f][: cfg["n_theorems"]]
    jobs = [(t, cfg, run_id, staging) for t in thms]
    t0 = time.perf_counter()
    if cfg.get("workers", 1) > 1:
        with Pool(cfg["workers"]) as pool:
            summary = pool.map(run_one, jobs, chunksize=1)
    else:
        summary = [run_one(j) for j in jobs]
    wall = time.perf_counter() - t0

    n_events = 0
    if any(f.endswith(".parquet") for f in os.listdir(staging)):
        table = pq.read_table(staging, schema=EVENT_SCHEMA)
        errs = validate(table)
        if errs:
            raise ValueError(errs)
        pq.write_to_dataset(table, lake, partition_cols=PARTITION_COLS,
                            basename_template=f"{run_id}-{{i}}.parquet", compression="zstd")
        n_events = table.num_rows
    shutil.rmtree(staging, ignore_errors=True)

    os.makedirs(results, exist_ok=True)
    with open(os.path.join(results, f"search_{run_id}.jsonl"), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(s, ensure_ascii=False) + "\n" for s in summary)
    metrics = {**summarize(summary), "events": n_events, "run_wall_s": wall}
    log_run(run_id, "collect", cfg, metrics, status="ok", data_version=cfg["data_version"],
            seed=cfg.get("seed"), timeout=cfg["budget"])
    return run_id, metrics


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--lake", default="data/lake/events")
    ap.add_argument("--results", default="results/raw")
    args = ap.parse_args(argv)
    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["config_path"] = args.config
    run_id, metrics = collect(cfg, args.lake, args.results)
    print(run_id, json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
