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


ROOT, AB = 0, 1


class FakeServer:
    """Mô phỏng REPL. Proof state id gắn với "thế hệ" server; server bị kill thì id cũ vô hiệu.

    Cây: root --simp--> {a, b} --ring--> xong. "boom" = timeout cứng (kill REPL). Còn lại: lỗi.
    """

    def __init__(self, gen):
        self.gen, self.alive = gen, True

    def run(self, req, timeout=None):
        from lean_interact.interface import LeanError
        if not self.alive:
            raise BrokenPipeError
        ps_gen, node = divmod(req.proof_state, 10)          # id = thế hệ*10 + nút
        if ps_gen != self.gen:
            return LeanError(message="unknown proof state")
        if req.tactic == "boom":
            self.alive = False
            raise TimeoutError
        if (node, req.tactic) == (ROOT, "simp"):
            return SimpleNamespace(messages=[], goals=["⊢ a", "⊢ b"], proof_state=self.gen * 10 + AB)
        if (node, req.tactic) == (AB, "ring"):
            return SimpleNamespace(messages=[], goals=[], proof_state=self.gen * 10 + 2)
        if req.tactic == "omega":
            return LeanError(message="failed")
        return SimpleNamespace(messages=[SimpleNamespace(severity="error", data="failed")], goals=["⊢ x"],
                               proof_state=self.gen * 10 + 9)


class FakeSession:
    def __init__(self):
        self.generation, self.restarts, self.reopens = 1, 0, 0
        self.server = FakeServer(1)

    def restart(self):
        self.restarts += 1
        self.generation += 1
        self.server = FakeServer(self.generation)

    def reopen(self):
        self.reopens += 1
        return self.generation * 10 + ROOT, "⊢ root"


def _apply(session):
    from src.search.live_repl import make_repl_apply
    return make_repl_apply(session, 10 + ROOT, "⊢ root")


def test_repl_apply_outcomes():
    apply = _apply(FakeSession())
    r = apply("⊢ root", "simp")
    assert r.outcome == "progress" and r.state_after == "⊢ a\n\n⊢ b"
    assert apply(r.state_after, "ring").outcome == "finished"
    assert apply("⊢ root", "omega").outcome == "error"           # LeanError
    assert apply("⊢ root", "linarith").outcome == "error"        # message severity=error


def test_timeout_restarts_and_rebuilds_state():
    """Lỗi cũ: sau 1 timeout, mọi lời gọi sau đều 'error' 0 ms. Giờ state được dựng lại."""
    session = FakeSession()
    apply = _apply(session)
    ab = apply("⊢ root", "simp").state_after
    assert apply("⊢ root", "boom").outcome == "error"            # timeout = tactic thất bại thật
    assert session.restarts == 1
    assert apply(ab, "ring").outcome == "finished"               # dựng lại {a,b} bằng replay "simp"
    assert session.reopens == 1


def test_unrecoverable_returns_unknown():
    session = FakeSession()
    apply = _apply(session)
    ab = apply("⊢ root", "simp").state_after
    apply("⊢ root", "boom")
    session.reopen = lambda: (_ for _ in ()).throw(RuntimeError("REPL down"))
    assert apply(ab, "ring").outcome == "unknown"


def test_repl_search_end_to_end_with_crash():
    events, status = best_first("⊢ root", _apply(FakeSession()), Budget(max_calls=100),
                                candidates=("simp", "boom", "omega", "ring"))
    assert status == "proved"
    assert [(e["tactic"], e["outcome"]) for e in events] == [
        ("simp", "progress"), ("boom", "error"), ("omega", "error"), ("ring", "error"),
        ("simp", "error"), ("boom", "error"), ("omega", "error"), ("ring", "finished")]
