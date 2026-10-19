import pandas as pd

from src.eval.prune_sweep import sweep
from src.search.core import Budget, best_first
from src.search.replay import make_replay_apply, root_state
from src.search.toy import make_toy_apply, toy_init_state

BUDGET = Budget("S", max_calls=60, timeout_s=30.0, max_depth=6)


def _trace(thm):
    events, status = best_first(toy_init_state(thm), make_toy_apply(thm), BUDGET)
    df = pd.DataFrame(events).assign(theorem_id=thm, budget_id="S", max_calls=60,
                                     timeout_s=30.0, max_depth=6)
    return df, status


def test_replay_at_tau0_reproduces_trace():
    for i in range(10):
        df, status = _trace(f"T{i}")
        replayed, rstatus = best_first(root_state(df), make_replay_apply(df), BUDGET)
        assert rstatus == status
        assert [(e["state_before"], e["tactic"], e["outcome"]) for e in replayed] == \
               list(zip(df.state_before, df.tactic, df.outcome))


def test_sweep_monotone_cost_and_lost_list():
    ev = pd.concat([_trace(f"T{i}")[0] for i in range(20)], ignore_index=True)
    simp_only = lambda s, t: 1.0 if t in ("simp", "omega") else 0.01
    rows, per_thm, lost = sweep(ev, simp_only, [0.0, 0.5], repeats=1)
    assert list(rows.tau) == [0.0, 0.5]
    assert rows.unknown_rate.iloc[0] == 0.0           # tau=0 khớp hoàn toàn với trace gốc
    assert rows.avg_states_expanded.iloc[1] <= rows.avg_states_expanded.iloc[0] + 1e-9 or \
        rows.unknown_rate.iloc[1] > 0
    assert set(lost.theorem_id) <= set(per_thm.theorem_id)
