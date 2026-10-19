"""Môi trường TOY tất định thay cho Lean — chỉ để kiểm thử đường ống collect -> lake -> replay
khi chưa có LeanDojo. Dữ liệu sinh ra có data_version="toy-synthetic" và KHÔNG được dùng
trong báo cáo kết quả.

Kết quả của (theorem, state, tactic) được quyết định bởi hash, nên chạy lại cho cùng trace.
"""
from __future__ import annotations

import hashlib

from src.search.core import Result

TOY_DATA_VERSION = "toy-synthetic"
# Vài tactic "hay thành công" hơn để policy có tín hiệu học được
_BIAS = {"simp": 25, "omega": 15, "ring": 10, "norm_num": 10, "rfl": 5}


def _h(*parts: str) -> int:
    return int(hashlib.sha1("|".join(parts).encode()).hexdigest()[:8], 16)


def toy_init_state(theorem_id: str) -> str:
    return f"x y : Nat\n⊢ goal_{_h(theorem_id) % 10_000}"


def make_toy_apply(theorem_id: str):
    def apply(pp: str, tac: str) -> Result:
        h = _h(theorem_id, pp, tac)
        r = h % 100
        head = tac.split()[0]
        ms = 5.0 + (h >> 8) % 40
        depth = pp.count("'")                  # mỗi bước progress thêm 1 dấu '
        if depth >= 1 and r < 6 + _BIAS.get(head, 0) // 3:
            return Result("finished", "", ms)
        if r < 30 + _BIAS.get(head, 0):
            return Result("progress", f"{pp}'{(h >> 4) % 7}", ms)
        return Result("error", "", ms)
    return apply
