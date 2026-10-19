from src.search.core import Budget, Result, best_first

# Cây giả: S0 --simp--> S1 --ring--> xong; mọi thứ khác lỗi
TREE = {("S0", "simp"): Result("progress", "S1", 5.0),
        ("S1", "ring"): Result("finished", "", 5.0)}


def fake_apply(pp, tac):
    return TREE.get((pp, tac), Result("error", "", 1.0))


def test_finds_proof():
    events, status = best_first("S0", fake_apply, Budget(max_calls=100))
    assert status == "proved"
    assert events[-1]["tactic"] == "ring"
    assert events[-1]["parent_step_idx"] == 1          # simp là event index 1 (sau rfl lỗi)


def test_call_budget_respected():
    events, status = best_first("S0", fake_apply, Budget(max_calls=3))
    assert status == "budget_exhausted" and len(events) == 3


def test_time_budget_respected():
    slow = lambda pp, tac: Result("error", "", 1000.0)
    events, status = best_first("S0", slow, Budget(max_calls=100, timeout_s=2.5))
    assert status == "budget_exhausted" and len(events) == 3


def test_depth_budget():
    chain = lambda pp, tac: Result("progress", pp + "'", 1.0) if tac == "simp" else Result("error", "", 1.0)
    events, status = best_first("S0", chain, Budget(max_calls=10_000, max_depth=3))
    assert status == "exhausted"
    assert max(e["depth"] for e in events) == 2


def test_duplicate_states_not_reexpanded():
    loop = lambda pp, tac: Result("progress", "S0", 1.0) if tac == "simp" else Result("error", "", 1.0)
    events, _ = best_first("S0", loop, Budget())
    assert [e["outcome"] for e in events if e["tactic"] == "simp"] == ["duplicate"]


def test_pruning_reduces_calls():
    full, _ = best_first("S0", fake_apply, Budget())
    keep = {"simp", "ring"}
    pruned, status = best_first("S0", fake_apply, Budget(),
                                policy=lambda s, t: 1.0 if t in keep else 0.0, tau=0.5)
    assert status == "proved" and len(pruned) < len(full)
    # S0: simp (progress), ring (error); S1: simp (error), ring (finished)
    assert [(e["tactic"], e["outcome"]) for e in pruned] == [
        ("simp", "progress"), ("ring", "error"), ("simp", "error"), ("ring", "finished")]
