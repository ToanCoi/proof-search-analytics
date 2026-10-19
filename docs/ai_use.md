# Khai báo sử dụng AI

| Phần | Công cụ AI | Mức độ | Kiểm chứng bởi nhóm |
|---|---|---|---|
| Khung code `src/`, `tests/`, `Makefile`, Docker | Claude Code (Anthropic) | Sinh bản đầu theo thiết kế trong `../docs/huong-dan-de-tai-7.html` | _(điền: ai đã đọc/sửa, test nào đã chạy)_ |
| Tài liệu `README.md`, `docs/*.md` | Claude Code | Soạn bản đầu | _(điền)_ |
| Phân tích kết quả, kết luận trong báo cáo | _(điền)_ | | |

Nguyên tắc: mọi đoạn code AI sinh đều được chạy qua `make test` và đọc lại; mọi con số trong báo cáo
sinh từ `results/raw/` bằng script, không lấy từ câu trả lời của AI. Dữ liệu fixture/toy
(`tests/fixtures/mini_benchmark.py`, `src/search/toy.py`) là tổng hợp, chỉ dùng để kiểm thử.
