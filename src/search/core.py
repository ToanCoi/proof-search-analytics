"""Lõi best-first search, không phụ thuộc Lean.

`apply(state_pp, tactic) -> Result` được truyền vào, nên cùng một thuật toán dùng cho
chạy thật (live.py), replay offline (replay.py) và môi trường toy (toy.py).
Pruning chỉ bỏ ứng viên có điểm < tau; thứ tự ứng viên và priority không đổi so với
baseline -> khác biệt duy nhất giữa hai lần chạy là việc cắt nhánh.
"""
from __future__ import annotations

import heapq
import itertools
from dataclasses import asdict, dataclass
from typing import Callable, Optional, Sequence

# Danh sách ứng viên CỐ ĐỊNH — giữ nguyên cho mọi thí nghiệm (ghi vào config/log).
CANDIDATES = ("rfl", "simp", "norm_num", "omega", "ring", "linarith",
              "decide", "positivity", "simp_all", "aesop", "intro h",
              "constructor", "exact?")


@dataclass(frozen=True)
class Budget:
    budget_id: str = "M"
    max_calls: int = 200        # số lần gọi tactic tối đa
    timeout_s: float = 120.0    # tổng thời gian Lean tối đa (cộng elapsed_ms)
    max_depth: int = 8

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Result:
    outcome: str                # finished | progress | error | unknown
    state_after: str = ""
    elapsed_ms: float = 0.0


Apply = Callable[[str, str], Result]     # (state_pp, tactic) -> Result
Policy = Callable[[str, str], float]     # (state_pp, tactic) -> điểm 0..1

# Trạng thái kết thúc của 1 lần search
PROVED, BUDGET, EXHAUSTED, UNKNOWN = "proved", "budget_exhausted", "exhausted", "unknown"


def best_first(init_pp: str, apply: Apply, budget: Budget,
               policy: Optional[Policy] = None, tau: float = 0.0,
               candidates: Sequence[str] = CANDIDATES) -> tuple[list[dict], str]:
    """Trả về (events, status). Mỗi event là 1 lần gọi tactic (đã trả chi phí)."""
    events: list[dict] = []
    clock_ms = 0.0
    tie = itertools.count()
    frontier = [(0.0, next(tie), init_pp, 0, None)]   # (priority, tie, state, depth, parent_step)
    seen = {init_pp}
    while frontier:
        prio, _, state, depth, parent = heapq.heappop(frontier)
        if depth >= budget.max_depth:
            continue
        for rank, tac in enumerate(candidates):
            if len(events) >= budget.max_calls or clock_ms >= budget.timeout_s * 1000:
                return events, BUDGET
            score = policy(state, tac) if policy else 1.0
            if score < tau:
                continue                     # PRUNE: không tốn lời gọi Lean
            res = apply(state, tac)
            if res.outcome == "unknown":     # chỉ xảy ra khi replay: lời gọi baseline chưa từng làm
                return events, UNKNOWN
            clock_ms += res.elapsed_ms
            outcome = res.outcome
            if outcome == "progress" and res.state_after in seen:
                outcome = "duplicate"
            events.append(dict(step_idx=len(events), parent_step_idx=parent, depth=depth,
                               state_before=state, tactic=tac, tactic_rank=rank,
                               score=float(score), state_after=res.state_after,
                               outcome=outcome, elapsed_ms=float(res.elapsed_ms)))
            if outcome == "finished":
                return events, PROVED
            if outcome == "progress":
                seen.add(res.state_after)
                heapq.heappush(frontier, (prio + 1 + 0.1 * rank, next(tie),
                                          res.state_after, depth + 1, len(events) - 1))
    return events, EXHAUSTED
