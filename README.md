# Proof-Search Analytics — Nhóm 7 (INT4418 Big Data, AI4Math)

**Mục tiêu.** Ghi lại quá trình một prover cố định thử tactic trên các định lý Lean 4, lưu thành
trace lake Parquet có schema version hóa, dùng Spark để phân tích hành vi tìm kiếm (branching
factor, depth, failure rate, chuyển tiếp tactic), học predictor tactic tiếp theo, và đánh giá việc
cắt nhánh (pruning) so với baseline no-pruning ở **cùng timeout và search budget**.

Hai câu hỏi nghiên cứu:
1. Đặc trưng proof state dự đoán tactic tiếp theo tốt đến đâu (top-k), khác nhau thế nào theo domain?
2. Pruning bằng predictor giảm được bao nhiêu states expanded trước khi proof success rate giảm đáng kể?

## Kiến trúc

```
LeanDojo Benchmark 4 ──ingest──┐
                               ├─> Parquet lake (source=/budget_id=) ─> Spark aggregation ─> results/raw/agg
Lean REPL/Dojo ─best-first─────┘         │  manifest + sha256                                    │
   (collect, budget S/M/L)               ├─> features (TF-IDF state) ─> predictor ─> policy(τ)   │
                                         └─> replay(trace no-pruning, policy, τ) ─> Pareto ──────┴─> figures, dashboard
```

| Khối | Mã | Ghi chú |
|---|---|---|
| 1 Trace collector | `src/search/{core,live_repl,live,collect,select}.py` | best-first, budget 3 chiều (calls, giây Lean, depth) |
| 2 Event schema | `src/common/schema.py`, `docs/data_card.md` | v0.1.0, 1 dòng = 1 lần thử tactic |
| 3 Parquet lake | `src/ingest/benchmark.py`, `src/lake/manifest.py` | partition `source`, `budget_id`; zstd; manifest checksum |
| 4 Spark aggregation | `src/analytics/aggregate.py` | 6 bảng; broadcast join, self-join, window lag, pivot; ghi physical plan |
| 5–6 Feature/predictor/policy | `src/model/{train,policy}.py` | baseline most-frequent vs TF-IDF + SGD |
| 7 Replay/eval | `src/search/replay.py`, `src/eval/{prune_sweep,figures}.py` | budget lấy từ run gốc, ≥3 lần, median |

## Cài đặt (Docker)

LeanDojo không chạy native trên Windows; mọi thứ chạy trong container.

```bash
docker compose build                       # Python 3.11 + Java 17 + elan + LeanDojo + PySpark
echo GITHUB_ACCESS_TOKEN=ghp_xxx > .env    # LeanDojo gọi GitHub API (không commit .env)
docker compose run --rm app make test      # pytest
```

Vào shell: `docker compose run --rm --service-ports app bash` (mở cổng 8501 Streamlit, 4040 Spark UI).

## Chạy nhanh

Kiểm tra pipeline offline (fixture tổng hợp + môi trường toy, không cần Lean/Benchmark; **không phải số liệu báo cáo**):

```bash
docker compose run --rm app make demo      # kết quả ở data/demo/
```

### Chuẩn bị máy (Windows + Docker Desktop, 1 lần)

- Docker Desktop → Settings → Resources → Advanced → **Disk image location** sang ổ còn nhiều chỗ
  (vd `D:\DockerData`): mathlib build sẵn + toolchain Lean chiếm ~8–10 GB.
- Cấp RAM cho WSL: `C:\Users\<user>\.wslconfig` gồm `[wsl2]`, `memory=20GB`, `processors=8`; rồi `wsl --shutdown`.
- Search dùng 2 REPL đã import Mathlib (mỗi REPL 4–6 GB). Windows cần có **pagefile** (để hệ thống quản lý) và
  đủ commit trống; nếu không, khi hết bộ nhớ ảo Windows giết WSL và container thoát với mã 137/255.
  Không để máy sleep trong lúc chạy search (sleep cũng làm Docker Desktop dừng).

### Phần 1 — Analytics & predictor (Benchmark 4, không cần Lean)

```bash
make download                  # LeanDojo Benchmark 4 -> data/raw + MANIFEST.txt (sha256)
make sample                    # data_sample/ bằng 1 lệnh (100 định lý/split) + manifest
make ingest                    # toàn bộ Benchmark -> data/lake/events + manifest.json
make aggregate                 # Spark ở 100/1K/10K/all định lý, mỗi mức 3 lần (E1); ghi physical plan
make replicate aggregate-rep   # lake nhân bản ×10, ×50 (chỉ đo runtime Spark), mỗi mức 3 lần
make train                     # most-frequent vs TF-IDF+SGD, top-1/3/5/10 (E2); make ablation
```

### Phần 2 — Search Lean thật (miniF2F qua LeanInteract — phương án chính)

```bash
make smoke-repl                # Lean core, không mathlib: kiểm tra REPL chạy (vài phút lần đầu)
make minif2f                   # 488 bài miniF2F Lean 4, commit cố định + sha256
make select-minif2f            # 100 bài cố định (seed 42) -> data/selections/minif2f_100_s42.jsonl
make collect CONFIG=configs/search_repl_baseline_S.yaml   # chạy thử (lần đầu tải mathlib build sẵn)
make baseline-repl             # no-pruning budget S/M/L (E3) — LÂU, chạy nền qua đêm
make sweep RUN=<run_id repl-baseline-M>                   # replay τ ∈ {0..0.2} ×3 (E4)
make collect CONFIG=configs/search_repl_prune_M_tau001.yaml       # live check τ đã chọn (0.01); tương tự tau0005
make aggregate-search && make figures && make dashboard
```

### Phần 3 — Báo cáo và slides (chạy trên máy host)

```bash
pip install -r requirements-docs.txt
make report                    # report.docx + slides/slides.pptx; mọi số đọc từ results/
```

`report.pdf` xuất từ `report.docx` (Word → Save as PDF). Kịch bản demo: `slides/demo_script.md`.

Phương án dự phòng (LeanDojo trên chính Benchmark 4, cần trace mathlib — nặng):
`make select && make baseline` rồi `make sweep RUN=<run_id search-baseline-M>`.

**Ghi chú lệch so với đề (deviation note).** Đề gợi ý thu trace qua LeanDojo. Trên máy 1 người,
LeanDojo phải trace toàn bộ mathlib4 (nhiều giờ, RAM lớn, hàng chục GB) — rủi ro cao. Phần search
dùng LeanInteract (Lean REPL + mathlib build sẵn) trên miniF2F. Ảnh hưởng: *correctness* — vẫn là
Lean 4 + mathlib thật, cùng thuật toán/schema; *cost* — không cần trace; *scalability* — 100 → 488 bài
(miniF2F), quy mô 1K–10K vẫn ở phần analytics Benchmark 4; *integration* — event ghi cùng schema v0.1.0,
`source=search`, `data_version` ghi rõ nguồn + phiên bản Lean. Predictor học từ Benchmark 4 (mathlib
2023) được áp dụng lên state miniF2F (mathlib theo Lean v4.9.0): lệch phân phối, phân tích trong báo cáo.

`run_id` của mỗi run nằm trong `results/raw/runs.jsonl` (đủ trường Phụ lục B).

## Tái tạo kết quả chính

1. Mọi tham số nằm trong `configs/*.yaml` + `Makefile` (DV, SEED, N, SCALES, REPEATS).
2. Tập định lý search: `make select` (seed cố định, sort theo `full_name` trước khi lấy mẫu).
3. Mọi bảng/hình trong `results/figures/` sinh bằng `make figures` từ `results/raw/`; mỗi hình có
   `.meta.json` ghi máy, phần mềm, budget, seed, số lần lặp, run nguồn.
4. Replay tái lập kết quả pruning mà không cần Lean: `make sweep RUN=...` đọc trace từ lake.

## Thí nghiệm & chỉ số

| | Biến | Cố định | Đo |
|---|---|---|---|
| E1 scale analytics | 100 → 1K → 10K → all định lý → lake nhân bản ×10, ×50 | Spark config, máy | runtime median [min–max], events/s, storage |
| E2 predictor | most-frequent vs TF-IDF+SGD; ablation unigram | split Benchmark, seed | top-1/3/5/10, theo domain |
| E3 search budget | S / M / L | 100 định lý, danh sách tactic | proof rate, states expanded, wall time |
| E4 pruning | τ | cùng định lý, cùng budget (S/M/L; live ở M) | Pareto proof rate ↔ states expanded, unknown rate, định lý bị mất |

Primary metrics: **proof success rate** (chất lượng) và **states expanded / định lý** (chi phí).

## Kết quả (21/10/2026)

Số liệu lấy từ `results/figures/{search_summary,search_runs,scale_aggregate}.csv`, `pruning_losses_*.csv`,
`results/raw/predictor_metrics.json` (sinh bằng `make figures`). Máy: Ryzen 5 3400G 8 luồng, Docker/WSL 20 GB RAM,
không GPU. Search chạy tuần tự, 2 worker, không job nào khác song song.

**E3–E4: search miniF2F (100 bài, seed 42, Lean v4.9.0 + mathlib).** Nhiều lần chạy: median [min–max].

| Run | Budget | τ | Lần | Proof rate | States / bài | Wall s / bài |
|---|---|---|---|---|---|---|
| baseline | S (50 calls, 30 s) | 0 | 1 | 0.32 | 25.7 | 16.1 |
| baseline | M (200 calls, 120 s) | 0 | 3 | 0.32 | 46.5 [44.5–46.5] | 26.7 [22.3–36.6] |
| baseline | L (800 calls, 300 s) | 0 | 1 | 0.32 | 76.7 | 32.8 |
| pruning live | M | 0.005 | 1 | 0.32 | 39.8 (−14%) | 20.5 |
| **pruning live (chọn)** | M | **0.01** | 1 | **0.32** | **31.2 (−33%)** | 18.9 |

- **τ cuối cùng = 0.01**: giảm 33% states expanded so với median baseline M, không mất bài nào.
- Tăng budget không chứng minh thêm bài nào: cả 5 run baseline giải đúng cùng 32 bài. Các bài còn lại cần
  tactic ngoài danh sách cố định (vd `interval_cases`). Proof rate và states gần như tất định; wall time dao động
  theo độ trễ Lean nên không dùng làm metric chính.
- Replay (ước lượng bảo thủ, `unknown` = thất bại) ở τ=0.01 cho 0.30, live đạt 0.32: 2 bài replay "mất" được giải
  bằng `nlinarith`, lời gọi mà baseline chưa từng làm. Tiết kiệm states ở τ=0.01 tăng theo budget
  (replay: S −29%, M −42%, L −53%); từ τ≥0.02 proof rate giảm nhanh (0.25).
- Phân tích lỗi (`pruning_losses_M*.csv`): 100% bài bị mất là do policy cắt đúng tactic trên đường chứng minh
  gốc (2/7/18/21/29 bài ở τ=0.01/0.02/0.05/0.1/0.2), chủ yếu `rfl` (mathd_numbertheory) và `linarith`
  (mathd_algebra) — các tactic hiếm trong mathlib nên predictor cho điểm thấp.
- Hành vi search (`search_behavior.png`): ~13 lời gọi cho mỗi state nhưng chỉ ~1 state con mới; `ring`/`norm_num`
  không lỗi nhưng 75%/94% lời gọi trả về state đã gặp; `exact?` tốn ~5 s/lời gọi so với ~4 ms của `decide`.

**E2: predictor (Benchmark 4, test 4,221 bước):** most-frequent top-1/top-10 = 0.203/0.724;
TF-IDF+SGD = 0.301/0.851; ablation unigram = 0.285/0.845.

**E1: Spark** (median [min–max] của 3 lần):

| Mức | Định lý | Event | Runtime s | Event/s | Lake |
|---|---|---|---|---|---|
| 100 | 100 | 476 | 20.8 [20.2–26.1] | 23 | 18 MB |
| 1K | 1,000 | 4,978 | 19.2 [17.9–20.2] | 259 | 18 MB |
| 10K | 10,000 | 43,815 | 21.2 [20.3–21.7] | 2,062 | 18 MB |
| all | 50,020 | 213,067 | 23.0 [22.9–23.9] | 9,277 | 18 MB |
| ×10 (nhân bản) | 500,200 | 2,130,670 | 45.1 [43.6–47.2] | 47,281 | 173 MB |
| ×50 (nhân bản) | 2,501,000 | 10,653,350 | 133.0 [124.2–135.2] | 80,103 | 865 MB |

Tới 50K định lý chi phí cố định (JVM, lập lịch) lấn át; lake nhân bản (chỉ dùng đo runtime) cho thấy vùng
tăng gần tuyến tính. Physical plan (`results/raw/spark_plans/`): lọc định lý là BroadcastHashJoin; self-join
cha–con chuyển từ BroadcastHashJoin (n100) sang SortMergeJoin có shuffle (toàn bộ).

**Run bị loại / thay thế:** 5 run search đầu bị lỗi REPL; các run Spark cũ được chạy lại cùng code
(xem `results/raw/invalid_runs.json`). Test: 27 pass (`make test`).

## Giới hạn đã biết

- Search live chỉ ở quy mô ~100 định lý (Lean chậm); quy mô 1K–10K cho analytics dùng Benchmark 4.
- Replay là ước lượng bảo thủ: lời gọi mà baseline chưa làm → `unknown` (tính thất bại). Cần live check.
- Predictor học từ chứng minh của người (Benchmark), nhưng policy chấm điểm danh sách tactic ứng viên cố định.

## Cấu trúc thư mục

`src/` mã theo khối · `tests/` pytest · `configs/` 1 file/run · `data_sample/` mẫu nhỏ + manifest ·
`scripts/` tải/tái tạo dữ liệu · `results/raw/` output thô · `results/figures/` hình sinh tự động ·
`docs/` data card, model card, AI use, license · `app/` dashboard · `slides/`.
