#!/usr/bin/env bash
# Chạy TUẦN TỰ toàn bộ thí nghiệm search (E3 + E4) để độ trễ Lean giữa các run so sánh được:
# baseline S/M/L -> replay sweep trên mỗi baseline -> live check các tau ở budget M.
# Không chạy song song với job Lean khác: budget thời gian tính theo thời gian Lean thật.
#   bash scripts/run_search_experiments.sh [LAKE]
set -euo pipefail
LAKE="${1:-data/lake/events}"

last_run() {  # run_id mới nhất của run_name $1 trong runs.jsonl
  python -c "import json,sys; rs=[json.loads(l) for l in open('results/raw/runs.jsonl')]; \
print([r['run_id'] for r in rs if r['kind']=='collect' and r['parameters']['run_name']==sys.argv[1]][-1])" "$1"
}

for b in S M L; do
  python -m src.search.collect --config "configs/search_repl_baseline_$b.yaml" --lake "$LAKE"
done
for b in S M L; do
  python -m src.eval.prune_sweep --lake "$LAKE" --run-id "$(last_run "repl-baseline-$b")" --repeats 3
done
for cfg in configs/search_repl_prune_M_tau*.yaml; do
  python -m src.search.collect --config "$cfg" --lake "$LAKE"
done
python -m src.lake.manifest --lake "$LAKE" --out "$(dirname "$LAKE")/manifest.json"
