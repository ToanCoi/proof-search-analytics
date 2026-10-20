"""Khối 7 — Replay trace no-pruning dưới nhiều ngưỡng tau, CÙNG budget với run gốc.

Budget lấy từ chính các cột max_calls/timeout_s/max_depth của run gốc, nên không thể
vô tình so sánh khác budget. Ghi thêm danh sách định lý bị mất ở mỗi tau để phân tích.

    python -m src.eval.prune_sweep --run-id <run_id no-pruning>
"""
from __future__ import annotations

import argparse
import os
import statistics
import time

import pandas as pd

from src.common.runlog import log_run, new_run_id, read_runs
from src.search.core import CANDIDATES, PROVED, UNKNOWN, Budget, best_first
from src.search.replay import make_replay_apply, root_state


def budget_of(ev: pd.DataFrame) -> Budget:
    cols = ["budget_id", "max_calls", "timeout_s", "max_depth"]
    b = ev[cols].astype({"budget_id": str}).drop_duplicates()
    if len(b) != 1:
        raise ValueError(f"run có nhiều budget: {b}")
    r = b.iloc[0]
    return Budget(r.budget_id, int(r.max_calls), float(r.timeout_s), int(r.max_depth))


def candidates_of(ev: pd.DataFrame) -> tuple[str, ...]:
    """Danh sách ứng viên (theo tactic_rank) mà run gốc đã dùng — replay phải dùng đúng nó."""
    pairs = ev[["tactic_rank", "tactic"]].drop_duplicates().sort_values("tactic_rank")
    if pairs.tactic_rank.duplicated().any():
        raise ValueError("1 tactic_rank ứng với nhiều tactic — run không nhất quán")
    ranks = pairs.tactic_rank.astype(int).tolist()
    if ranks != list(range(len(ranks))):
        raise ValueError(f"thiếu tactic_rank trong trace ({ranks}); truyền --candidates")
    return tuple(pairs.tactic)


def sweep(ev: pd.DataFrame, policy, taus: list[float], repeats: int = 3,
          candidates: tuple[str, ...] | None = None):
    budget = budget_of(ev)
    candidates = tuple(candidates) if candidates else candidates_of(ev)
    used = ev[["tactic_rank", "tactic"]].drop_duplicates()
    if any(r >= len(candidates) or candidates[r] != t for r, t in zip(used.tactic_rank.astype(int), used.tactic)):
        raise ValueError("candidates không khớp với tactic_rank/tactic trong trace")
    groups = [(thm, g.sort_values("step_idx")) for thm, g in ev.groupby("theorem_id")]
    n = len(groups)
    rows, per_thm = [], []
    for tau in taus:
        walls = []
        for rep in range(repeats):
            t0 = time.perf_counter()
            stats = []
            for thm, g in groups:
                events, status = best_first(root_state(g), make_replay_apply(g), budget,
                                            policy=policy if tau > 0 else None, tau=tau,
                                            candidates=candidates)
                stats.append((thm, status, len(events), sum(e["elapsed_ms"] for e in events)))
            walls.append(time.perf_counter() - t0)
        per_thm += [{"tau": tau, "theorem_id": t, "status": s, "states_expanded": k, "lean_ms": ms}
                    for t, s, k, ms in stats]
        rows.append({"tau": tau, "n": n, "budget_id": budget.budget_id,
                     "max_calls": budget.max_calls, "timeout_s": budget.timeout_s,
                     "proof_success_rate": sum(s == PROVED for _, s, _, _ in stats) / n,
                     "avg_states_expanded": sum(k for _, _, k, _ in stats) / n,
                     "unknown_rate": sum(s == UNKNOWN for _, s, _, _ in stats) / n,
                     "est_lean_s_per_thm": sum(ms for *_, ms in stats) / n / 1000,
                     "replay_wall_s_median": statistics.median(walls),
                     "replay_wall_s_min": min(walls), "replay_wall_s_max": max(walls),
                     "repeats": repeats})
        print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in rows[-1].items()})
    per_thm = pd.DataFrame(per_thm)
    base = set(per_thm[(per_thm.tau == taus[0]) & (per_thm.status == PROVED)].theorem_id)
    lost = per_thm[(per_thm.theorem_id.isin(base)) & (per_thm.status != PROVED)]
    return pd.DataFrame(rows), per_thm, lost


def proof_paths(ev: pd.DataFrame, policy) -> pd.DataFrame:
    """Đường chứng minh của run gốc (từ gốc tới event 'finished') + điểm policy của từng bước.

    Bài bị mất ở ngưỡng tau mà min_score < tau là do pruning cắt đúng tactic cần thiết;
    còn lại là do replay rời khỏi trace (unknown) hoặc hết budget theo đường khác.
    """
    rows = []
    for thm, g in ev.groupby("theorem_id"):
        by_step = g.set_index("step_idx")
        fin = g[g.outcome == "finished"]
        if fin.empty:
            continue
        path, step = [], int(fin.step_idx.iloc[0])
        while step is not None:
            e = by_step.loc[step]
            path.append(e)
            step = None if pd.isna(e.parent_step_idx) else int(e.parent_step_idx)
        path.reverse()
        scores = [policy(e.state_before, e.tactic) for e in path]
        rows += [{"theorem_id": thm, "domain": g.domain.iloc[0], "step": i, "tactic": e.tactic,
                  "score": sc, "min_score": min(scores), "path": " ; ".join(p.tactic for p in path)}
                 for i, (e, sc) in enumerate(zip(path, scores))]
    return pd.DataFrame(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake", default="data/lake/events")
    ap.add_argument("--run-id", required=True, help="run no-pruning dùng làm nguồn replay")
    ap.add_argument("--model", default="artifacts/tactic_model.joblib")
    ap.add_argument("--taus", default="0,0.005,0.01,0.02,0.05,0.1,0.2")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--candidates", help="danh sách tactic phân tách bằng '|' (mặc định: suy ra từ trace)")
    ap.add_argument("--results", default="results/raw")
    args = ap.parse_args(argv)
    cands = tuple(args.candidates.split("|")) if args.candidates else None
    if not cands:                               # ưu tiên config gốc của run trong runs.jsonl
        rec = next((r for r in read_runs() if r["run_id"] == args.run_id), None)
        if rec:
            cands = tuple(rec["parameters"].get("candidates") or CANDIDATES)

    taus = sorted(float(t) for t in args.taus.split(","))
    if taus[0] != 0:
        taus = [0.0] + taus                     # luôn có điểm no-pruning để so sánh
    ev = pd.read_parquet(args.lake, filters=[("source", "=", "search"), ("run_id", "=", args.run_id)])
    if ev.empty:
        raise SystemExit(f"không có event cho run {args.run_id}")
    if (ev.policy.astype(str) != "none").any():
        raise SystemExit("run nguồn replay phải là no-pruning (policy=none)")
    from src.model.policy import load_policy, model_hash
    rows, per_thm, lost = sweep(ev, load_policy(args.model), taus, args.repeats, cands)
    rows["model_hash"] = model_hash(args.model)
    os.makedirs(args.results, exist_ok=True)
    out = os.path.join(args.results, f"prune_sweep_{args.run_id}.csv")
    rows.to_csv(out, index=False)
    per_thm.to_csv(os.path.join(args.results, f"prune_sweep_{args.run_id}_per_theorem.csv"), index=False)
    lost.to_csv(os.path.join(args.results, f"prune_sweep_{args.run_id}_lost.csv"), index=False)
    proof_paths(ev, load_policy(args.model)).to_csv(
        os.path.join(args.results, f"prune_sweep_{args.run_id}_proof_paths.csv"), index=False)
    log_run(new_run_id("sweep"), "sweep", vars(args), {"file": out, "rows": rows.to_dict("records")},
            status="ok", data_version=args.run_id, timeout=budget_of(ev).as_dict())


if __name__ == "__main__":
    main()
