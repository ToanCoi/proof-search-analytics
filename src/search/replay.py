"""Replay offline: tra bảng (state_before, tactic) -> Result từ trace no-pruning đã ghi.

Lời gọi chưa có trong bảng trả "unknown" và search dừng với status unknown
(tính là thất bại — ước lượng bảo thủ, cần kiểm chứng lại bằng live run).
"""
from __future__ import annotations

import pandas as pd

from src.search.core import Result


def make_replay_apply(events: pd.DataFrame):
    """events: trace no-pruning của MỘT định lý trong MỘT run."""
    table = {}
    for r in events.itertuples(index=False):
        out = "progress" if r.outcome == "duplicate" else r.outcome
        elapsed = 0.0 if pd.isna(r.elapsed_ms) else float(r.elapsed_ms)
        table[(r.state_before, r.tactic)] = Result(out, r.state_after or "", elapsed)
    return lambda pp, tac: table.get((pp, tac), Result("unknown"))


def root_state(events: pd.DataFrame) -> str:
    return events.loc[events.parent_step_idx.isna(), "state_before"].iloc[0]
