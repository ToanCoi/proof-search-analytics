"""Event schema (data contract) cho trace lake của Nhóm 7.

Grain: 1 dòng = 1 lần thử 1 tactic trên 1 proof state.
Khóa: (run_id, theorem_id, step_idx). parent_step_idx trỏ tới event sinh ra state_before
(null = state gốc) nên dựng lại được cây tìm kiếm.

Quy tắc tiến hóa: chỉ thêm cột nullable ở cuối -> tăng minor; đổi nghĩa/xóa cột -> tăng major.
"""
from __future__ import annotations

import pyarrow as pa

SCHEMA_VERSION = "0.1.0"
SOURCES = ("benchmark", "search")
OUTCOMES = ("finished", "progress", "duplicate", "error", "unknown")
PARTITION_COLS = ["source", "budget_id"]

EVENT_SCHEMA = pa.schema([
    ("schema_version",  pa.string()),
    ("source",          pa.string()),     # benchmark | search
    ("run_id",          pa.string()),
    ("data_version",    pa.string()),     # vd "lb4-v5" hoặc "toy-synthetic"
    ("split",           pa.string()),     # train | val | test
    ("theorem_id",      pa.string()),     # full_name
    ("file_path",       pa.string()),
    ("domain",          pa.string()),     # Mathlib/<Domain>/... -> Domain
    ("step_idx",        pa.int32()),
    ("parent_step_idx", pa.int32()),      # null = state gốc
    ("depth",           pa.int32()),
    ("state_before",    pa.string()),
    ("tactic",          pa.string()),
    ("tactic_rank",     pa.int32()),      # thứ tự trong danh sách ứng viên (null với benchmark)
    ("score",           pa.float32()),    # điểm policy (1.0 nếu không có policy)
    ("state_after",     pa.string()),     # "" nếu finished/error
    ("outcome",         pa.string()),     # OUTCOMES
    ("elapsed_ms",      pa.float32()),    # thời gian gọi Lean (null với benchmark)
    ("budget_id",       pa.string()),     # S | M | L | na
    ("max_calls",       pa.int32()),
    ("timeout_s",       pa.float32()),
    ("max_depth",       pa.int32()),
    ("policy",          pa.string()),     # human | none | model:<hash>
    ("tau",             pa.float32()),
])

REQUIRED_NON_NULL = ("schema_version", "source", "run_id", "theorem_id", "step_idx",
                     "state_before", "tactic", "outcome", "budget_id", "policy")


def domain_of(file_path: str) -> str:
    parts = (file_path or "").split("/")
    return parts[1] if len(parts) > 2 and parts[0] == "Mathlib" else "Other"


def to_table(rows: list[dict]) -> pa.Table:
    """Dựng bảng đúng EVENT_SCHEMA; cột thiếu trong dict được điền null."""
    names = EVENT_SCHEMA.names
    return pa.Table.from_pylist([{n: r.get(n) for n in names} for r in rows], EVENT_SCHEMA)


def validate(table: pa.Table) -> list[str]:
    """Trả về danh sách lỗi; rỗng = hợp lệ."""
    errs = []
    if table.schema.names != EVENT_SCHEMA.names:
        return [f"column mismatch: {table.schema.names}"]
    for field in EVENT_SCHEMA:
        if table.schema.field(field.name).type != field.type:
            errs.append(f"{field.name}: type {table.schema.field(field.name).type} != {field.type}")
    for col in REQUIRED_NON_NULL:
        if table.column(col).null_count:
            errs.append(f"{col} has nulls")
    bad = set(table.column("outcome").to_pylist()) - set(OUTCOMES)
    if bad:
        errs.append(f"unknown outcomes: {bad}")
    bad = set(table.column("source").to_pylist()) - set(SOURCES)
    if bad:
        errs.append(f"unknown sources: {bad}")
    versions = set(table.column("schema_version").to_pylist())
    if versions - {SCHEMA_VERSION}:
        errs.append(f"schema_version mismatch: {versions}")
    return errs
