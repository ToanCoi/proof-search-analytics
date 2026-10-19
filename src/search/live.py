"""Adapter gọi Lean thật qua LeanDojo (chỉ chạy trên Linux/Docker)."""
from __future__ import annotations

import time

from src.search.core import Result


def make_live_apply(dojo, init_state):
    from lean_dojo import ProofFinished, TacticState

    states = {init_state.pp: init_state}      # pp -> TacticState (Dojo cần object, không nhận text)

    def apply(pp: str, tac: str) -> Result:
        t0 = time.perf_counter()
        try:
            res = dojo.run_tac(states[pp], tac)
        except Exception:                      # Dojo crash / timeout cứng
            return Result("error", "", (time.perf_counter() - t0) * 1000)
        ms = (time.perf_counter() - t0) * 1000
        if isinstance(res, ProofFinished):
            return Result("finished", "", ms)
        if isinstance(res, TacticState):
            states.setdefault(res.pp, res)
            return Result("progress", res.pp, ms)
        return Result("error", "", ms)         # LeanError, ProofGivenUp, ...

    return apply
