# Data card & data contract — Trace lake Nhóm 7

## Nguồn

| source | Nguồn gốc | License | Cách tái tạo |
|---|---|---|---|
| `benchmark` | LeanDojo Benchmark 4 (Zenodo record 10114185), trích từ mathlib4 | Apache-2.0 (mathlib4); license dataset: xem trang Zenodo và ghi lại ở đây | `make download && make ingest` |
| `search` (chính) | Trace tự sinh: best-first search cố định qua LeanInteract trên miniF2F Lean 4 (bản DeepSeek-Prover-V1.5, commit `2c4ba91`, 244 valid + 244 test) | repo DeepSeek-Prover-V1.5: MIT; miniF2F gốc: xem license repo gốc | `make minif2f && make select-minif2f && make baseline-repl` |
| `search` (dự phòng) | Như trên nhưng qua LeanDojo trên định lý test split của Benchmark 4 | như Benchmark 4 | `make select && make baseline` |

`data_version` của trace search ghi nguồn + phiên bản Lean, vd `minif2f-ds15@2c4ba91+lean-v4.9.0`.
Với miniF2F, `domain` = tiền tố tên bài (`amc`, `aime`, `imo`, `mathd_algebra`, ...), `split` = valid/test của miniF2F.

Không có dữ liệu cá nhân. Dữ liệu đầy đủ không commit; chỉ `data_sample/` + `manifest.json` (sha256).

## Grain và khóa

- **1 dòng = 1 lần thử 1 tactic trên 1 proof state** (search event).
- Khóa: `(run_id, theorem_id, step_idx)`. `parent_step_idx` trỏ tới event sinh ra `state_before`
  (null = state gốc) → dựng lại cây tìm kiếm.
- Dữ liệu append-only; sửa = tạo run mới.

## Schema v0.1.0 (`src/common/schema.py`)

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| schema_version | string | `0.1.0` |
| source | string | `benchmark` \| `search` (partition) |
| run_id | string | id run collect; với benchmark = `bench-<data_version>` |
| data_version | string | phiên bản dữ liệu nguồn |
| split | string | train / val / test (split cố định của Benchmark, chia theo định lý) |
| theorem_id | string | `full_name` của định lý |
| file_path, domain | string | file Lean; domain = thư mục cấp 2 dưới `Mathlib/` |
| step_idx, parent_step_idx, depth | int32 | vị trí trong cây |
| state_before, state_after | string | proof state dạng pretty-print; `state_after=""` nếu finished/error |
| tactic, tactic_rank | string, int32 | tactic đã thử và thứ tự trong danh sách ứng viên |
| score | float32 | điểm policy (1.0 nếu không có policy) |
| outcome | string | finished \| progress \| duplicate \| error \| unknown |
| elapsed_ms | float32 | thời gian gọi Lean |
| budget_id, max_calls, timeout_s, max_depth | | **search budget của trace** (partition theo budget_id; `na` cho benchmark) |
| policy, tau | string, float32 | `human` / `none` / `model:<hash>` và ngưỡng prune |

## Quy tắc tiến hóa

- Thêm cột nullable ở cuối → tăng minor (0.2.0); người đọc cũ bỏ qua được.
- Đổi nghĩa / đổi kiểu / xóa cột → tăng major; ghi migration ở đây.
- `validate()` kiểm tra tên + kiểu cột, cột bắt buộc không null, giá trị `outcome`/`source`, version.

## Cách nhóm khác đọc

```python
import pandas as pd
ev = pd.read_parquet("data/lake/events", filters=[("source", "=", "search"), ("budget_id", "=", "M")])
```
```python
spark.read.parquet("data/lake/events").filter("source = 'benchmark'")
```
Kiểm tra toàn vẹn: `python -m src.lake.manifest --lake data_sample/events --verify data_sample/manifest.json`.
