# Kịch bản demo (~7 phút)

Chuẩn bị trước buổi bảo vệ:
- `docker compose build`.
- Đã chạy xong pipeline: có `data/lake/events` và `results/`.
- Mở sẵn 2 terminal ở `proof-search-analytics/`.
- Trong Git Bash, thêm `MSYS_NO_PATHCONV=1` trước mỗi lệnh `docker`.

| # | Thời gian | Làm gì | Nói gì |
|---|---|---|---|
| 1 | 0:30 | `docker compose run --rm app make test` | 27 test chạy offline, không cần Lean. Trong đó có test replay ở τ=0 khớp trace gốc và test khôi phục REPL sau timeout. |
| 2 | 1:30 | `docker compose run --rm app python -c "import pandas as pd; ev=pd.read_parquet('data/lake/events', filters=[('source','=','search'),('budget_id','=','M')]); print(ev.groupby('run_id').size()); t=ev[ev.theorem_id==ev.theorem_id.iloc[0]]; print(t[['step_idx','parent_step_idx','depth','tactic','outcome','elapsed_ms']].head(15))"` | Grain là 1 lần thử tactic. Cột `parent_step_idx` dựng lại cây tìm kiếm. Budget được ghi ngay trên từng event. Filter theo partition nên chỉ đọc thư mục `budget_id=M`. |
| 3 | 1:00 | `docker compose run --rm --service-ports app make aggregate-search`, rồi mở http://localhost:4040 trong lúc job chạy | Tab SQL hiện BroadcastHashJoin cho tập định lý và Exchange cho self-join/window. Plan đã lưu ở `results/raw/spark_plans/`. |
| 4 | 2:00 | `docker compose run --rm --service-ports app make dashboard`, mở http://localhost:8501 | Đi qua 5 tab: Trace analytics (tactic phổ biến, failure rate, branching theo độ sâu, chuyển tiếp tactic), Tactic predictor (top-k theo domain), Search budget, Pruning, Run log. |
| 5 | 1:30 | Mở `results/figures/pareto_*-M-*.png` và `pruning_losses_M.csv` | Ở τ=0.01, chạy Lean thật giảm 33% states mà không mất bài nào. Từ τ=0.02 trở lên bắt đầu mất bài, vì policy cắt đúng tactic nằm trên đường chứng minh gốc. |
| 6 | 0:30 | `tail -1 results/raw/runs.jsonl` | Mỗi run có log Phụ lục B: git commit, data version, máy, phần mềm, seed, budget. |

Phương án dự phòng nếu Docker hoặc Spark chậm: mở thẳng `results/figures/*.png` và các file CSV đã commit, rồi trình bày.

Câu hỏi hay gặp:
- **Vì sao Spark runtime phẳng?**
  - Lake thật chỉ 18 MB nên chi phí cố định chiếm phần lớn thời gian.
  - Lake nhân bản ×10 và ×50 cho thấy vùng tuyến tính.
- **Replay khác live thế nào?**
  - Replay chỉ dùng được những lời gọi baseline đã thực hiện; lời gọi ngoài trace bị tính là thất bại, nên đây là ước lượng bảo thủ.
  - Vì vậy τ cuối cùng được kiểm chứng bằng chạy Lean thật, cùng budget và cùng 100 bài.
- **So sánh có công bằng không?**
  - Cùng 100 bài, cùng budget, cùng danh sách và thứ tự ứng viên, cùng máy.
  - Search chạy tuần tự, không có job nào khác chạy song song.
- **Vì sao không dùng LeanDojo?** Xem deviation note trong README và report.
