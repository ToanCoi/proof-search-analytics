#!/usr/bin/env bash
# Bổ sung sau đợt chạy chính, TUẦN TỰ:
#   E1: chạy lại Spark ở mọi mức (column pruning + ghi physical plan), rồi lake nhân bản ×10, ×50
#   E4: sweep lại S/M/L để có thêm proof_paths (phân tích bài bị mất)
#   E3: baseline M thêm 2 lần (median wall time) — chạy cuối, không có job nặng nào song song
#   bash scripts/run_extra_experiments.sh [LAKE]
set -euo pipefail
LAKE="${1:-data/lake/events}"

last_run() {
  python -c "import json,sys; rs=[json.loads(l) for l in open('results/raw/runs.jsonl')]; \
print([r['run_id'] for r in rs if r['kind']=='collect' and r['parameters']['run_name']==sys.argv[1]][-1])" "$1"
}

make aggregate LAKE="$LAKE"
make replicate LAKE="$LAKE"
make aggregate-rep
make aggregate-search LAKE="$LAKE"
for b in S M L; do
  python -m src.eval.prune_sweep --lake "$LAKE" --run-id "$(last_run "repl-baseline-$b")" --repeats 3
done
for i in 1 2; do
  python -m src.search.collect --config configs/search_repl_baseline_M.yaml --lake "$LAKE"
done
python -m src.lake.manifest --lake "$LAKE" --out "$(dirname "$LAKE")/manifest.json"
