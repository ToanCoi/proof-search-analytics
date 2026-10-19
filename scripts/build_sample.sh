#!/usr/bin/env bash
# Tái tạo data_sample/ (100 định lý đầu theo full_name mỗi split) + manifest có checksum.
#   bash scripts/build_sample.sh [BENCH_DIR] [DATA_VERSION]
set -euo pipefail
BENCH="${1:-data/raw/leandojo_benchmark_4/random}"
DV="${2:-lb4-z10114185}"
export G7_RUNLOG=data_sample/build_log.jsonl
rm -rf data_sample/events
python -m src.ingest.benchmark --bench-dir "$BENCH" --data-version "$DV" --limit 100 --out data_sample/events
python -m src.lake.manifest --lake data_sample/events --out data_sample/manifest.json
