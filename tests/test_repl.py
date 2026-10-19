"""Backend REPL (LeanInteract) với server giả + chọn bài miniF2F + candidates của replay. Không cần Lean."""
from types import SimpleNamespace

import pandas as pd
import pytest

from src.eval.prune_sweep import candidates_of, sweep
from src.search.core import Budget, best_first
from src.search.select import minif2f_domain, select_minif2f

ROWS = [{"name": n, "split": s, "formal_statement": f"theorem {n} : True := by\n", "header": "import Mathlib\n"}
        for n, s in [("amc12a_2019_p21", "valid"), ("mathd_algebra_10", "test"),
                     ("imo_1959_p1", "test"), ("aime_1983_p1", "valid")]]


def test_minif2f_domain():
    assert minif2f_domain("amc12a_2019_p21") == "amc"
    assert minif2f_domain("mathd_numbertheory_3") == "mathd_numbertheory"
    assert minif2f_domain("imo_1959_p1") == "imo"


def test_select_minif2f_deterministic_and_split_filter():
    a = select_minif2f(ROWS, 2, 42, ("test",))
    assert a == select_minif2f(list(reversed(ROWS)), 2, 42, ("test",))
    assert {t["split"] for t in a} == {"test"}
    assert all(t["statement"].endswith(":= by\n") and t["header"] for t in a)


def test_candidates_of_and_mismatch():
    events, _ = best_first("S0", lambda pp, tac: SimpleNamespace(outcome="error", state_after="", elapsed_ms=1.0),
                           Budget("S", 100, 60.0, 4), candidates=("simp", "nlinarith", "ring"))
    ev = pd.DataFrame(events).assign(theorem_id="t", budget_id="S", max_calls=100, timeout_s=60.0, max_depth=4)
    assert candidates_of(ev) == ("simp", "nlinarith", "ring")
    with pytest.raises(ValueError):
        sweep(ev, None, [0.0], 1, candidates=("simp", "ring", "nlinarith"))


lean_interact = pytest.importorskip("lean_interact")


class FakeServer:
    """S0 --simp--> S1 (2 goal) --ring--> xong; mọi tactic khác lỗi."""

    def __init__(self):
        self.next_id = 1

    def run(self, req, timeout=None):
        from lean_interact.interface import LeanError
        if req.tactic == "boom":
            raise TimeoutError
        if (req.proof_state, req.tactic) == (0, "simp"):
            return SimpleNamespace(messages=[], goals=["⊢ a", "⊢ b"], proof_state=1, proof_status="Incomplete")
        if (req.proof_state, req.tactic) == (1, "ring"):
            return SimpleNamespace(messages=[], goals=[], proof_state=2, proof_status="Completed")
        if req.tactic == "omega":
            return LeanError(message="unknown")
        return SimpleNamespace(messages=[SimpleNamespace(severity="error", data="failed")], goals=["⊢ x"],
                               proof_state=9, proof_status="Error")


def test_repl_apply_outcomes():
    from src.search.live_repl import make_repl_apply
    apply = make_repl_apply(FakeServer(), 0, "⊢ root")
    r = apply("⊢ root", "simp")
    assert r.outcome == "progress" and r.state_after == "⊢ a\n\n⊢ b"
    assert apply(r.state_after, "ring").outcome == "finished"
    assert apply("⊢ root", "omega").outcome == "error"           # LeanError
    assert apply("⊢ root", "linarith").outcome == "error"        # message severity=error
    assert apply("⊢ root", "boom").outcome == "error"            # timeout


def test_repl_search_end_to_end():
    from src.search.live_repl import make_repl_apply
    events, status = best_first("⊢ root", make_repl_apply(FakeServer(), 0, "⊢ root"), Budget(max_calls=100),
                                candidates=("simp", "omega", "ring"))
    assert status == "proved"
    assert [(e["tactic"], e["outcome"]) for e in events][-1] == ("ring", "finished")
