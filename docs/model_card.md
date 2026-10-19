# Model / system card — Tactic predictor & pruning policy

## Mô hình
- **Baseline:** `DummyClassifier(strategy="prior")` — luôn xếp hạng tactic theo tần suất trong train (most-frequent tactic).
- **Phương pháp:** TF-IDF (token tách theo khoảng trắng/ngoặc, n-gram 1–2, sublinear tf, ≤200K đặc trưng)
  trên `state_before` + `SGDClassifier(loss="log_loss")`. Seed cố định (mặc định 42).
- **Nhãn:** `tactic_head` (token đầu của tactic), top-50 lớp + `<other>`.
- **Dữ liệu:** split train/test của LeanDojo Benchmark 4 (random split, chia theo định lý). Train tối đa 300K event.

## Đánh giá
- Top-1/3/5/10 accuracy trên test, tổng và theo domain → `results/raw/predictor_metrics.json`, `predictor_by_domain.csv`.
- Ablation: unigram (`make ablation`).

## Policy pruning
`policy(state, tactic) = P(tactic_head | state)`; ứng viên có điểm < τ bị bỏ. Thứ tự ứng viên và
priority giữ nguyên như baseline nên khác biệt duy nhất là việc cắt nhánh.

## Giới hạn
- Phân phối lệch: train là chứng minh của người, áp dụng lên danh sách ứng viên cố định của search.
- Xác suất không hiệu chỉnh (calibration) → τ chỉ có ý nghĩa tương đối, chọn qua Pareto.
- Không dùng premise/retrieval; tactic có tham số (`rw [...]`) chỉ dự đoán phần đầu.
