# Mọi bước chạy đều qua đây. Trong Docker: docker compose run --rm app make <target>
PY      := python -m
DV      ?= lb4-z10114185
BENCH   ?= data/raw/leandojo_benchmark_4/random
LAKE    ?= data/lake/events
SCALES  ?= 100 1000 10000 0
REPEATS ?= 3
REPS    ?= 10 50
N       ?= 100
SEED    ?= 42
SEL     := data/selections/thm_$(N)_s$(SEED).jsonl
SEL_F2F := data/selections/minif2f_$(N)_s$(SEED).jsonl

.PHONY: help test download ingest manifest sample sample-verify select baseline collect \
        aggregate aggregate-search replicate aggregate-rep train ablation sweep figures dashboard \
        fixture demo clean-demo

help:            ## liệt kê target
	@grep -E '^[a-z-]+:.*##' Makefile | sed 's/:.*##/\t/'

test:            ## pytest (Spark test tự skip nếu thiếu Java)
	pytest -q

download:        ## tải LeanDojo Benchmark 4 vào data/raw + ghi checksum
	bash scripts/download_benchmark.sh

ingest:          ## Benchmark 4 JSON -> Parquet lake (toàn bộ) + manifest
	$(PY) src.ingest.benchmark --bench-dir $(BENCH) --data-version $(DV) --out $(LAKE)
	$(MAKE) manifest

manifest:
	$(PY) src.lake.manifest --lake $(LAKE) --out $(dir $(LAKE))manifest.json

sample:          ## tái tạo data_sample/ bằng 1 lệnh (100 định lý/split)
	bash scripts/build_sample.sh $(BENCH) $(DV)

sample-verify:   ## kiểm tra data_sample/ khớp manifest đã commit
	$(PY) src.lake.manifest --lake data_sample/events --verify data_sample/manifest.json

select:          ## chọn N định lý cố định từ test split
	$(PY) src.search.select --bench $(BENCH)/test.json --n $(N) --seed $(SEED) --out $(SEL)

baseline:        ## search no-pruning ở 3 mức budget (LÂU — chạy nền/qua đêm)
	for b in S M L; do $(PY) src.search.collect --config configs/search_baseline_$$b.yaml --lake $(LAKE) || exit 1; done
	$(MAKE) manifest

# ---- Search qua LeanInteract (Lean REPL + mathlib build sẵn, không trace) trên miniF2F ----
minif2f:         ## tải miniF2F Lean 4 (488 bài) ở commit cố định
	bash scripts/download_minif2f.sh

select-minif2f:  ## chọn N bài miniF2F cố định (seed)
	$(PY) src.search.select --minif2f data/raw/minif2f/minif2f.jsonl --n $(N) --seed $(SEED) --out $(SEL_F2F)

smoke-repl:      ## kiểm tra LeanInteract với Lean core (không mathlib), ghi vào lake riêng
	G7_RUNLOG=data/smoke/runs.jsonl $(PY) src.search.collect --config configs/smoke_repl_core.yaml \
	  --lake data/smoke/events --results data/smoke/raw

baseline-repl:   ## search no-pruning budget S/M/L trên miniF2F (LÂU — chạy nền)
	for b in S M L; do $(PY) src.search.collect --config configs/search_repl_baseline_$$b.yaml --lake $(LAKE) || exit 1; done
	$(MAKE) manifest

search-all:      ## baseline S/M/L + sweep + live tau, TUẦN TỰ (vài giờ) — log ở data/logs/search_all.log
	mkdir -p data/logs
	bash scripts/run_search_experiments.sh $(LAKE) 2>&1 | tee data/logs/search_all.log

collect:         ## CONFIG=configs/xxx.yaml
	$(PY) src.search.collect --config $(CONFIG) --lake $(LAKE)

aggregate:       ## Spark ở các mức quy mô SCALES, mỗi mức REPEATS lần
	for n in $(SCALES); do for r in $$(seq 1 $(REPEATS)); do \
	  $(PY) src.analytics.aggregate --lake $(LAKE) --limit-theorems $$n --repeat-idx $$r \
	    $$([ $$r = 1 ] && echo --explain) || exit 1; done; done

replicate:       ## lake nhân bản ×k (REPS) từ Benchmark — CHỈ để đo scale Spark, ghi rõ trong báo cáo
	for k in $(REPS); do python scripts/replicate_lake.py --lake $(LAKE) --factor $$k --out data/lake_rep/x$$k/events || exit 1; \
	  $(PY) src.lake.manifest --lake data/lake_rep/x$$k/events --out data/lake_rep/x$$k/manifest.json || exit 1; done

aggregate-rep:   ## Spark trên lake nhân bản, mỗi mức REPEATS lần
	for k in $(REPS); do for r in $$(seq 1 $(REPEATS)); do \
	  $(PY) src.analytics.aggregate --lake data/lake_rep/x$$k/events --tag benchmark_rep_x$$k \
	    --replication $$k --repeat-idx $$r || exit 1; done; done

aggregate-search: ## Spark trên trace search (RUN=<run_id> tùy chọn)
	$(PY) src.analytics.aggregate --lake $(LAKE) --source search $(if $(RUN),--run-id $(RUN))

train:           ## baseline most-frequent vs TF-IDF+SGD, top-k
	$(PY) src.model.train --lake $(LAKE) --seed $(SEED)

ablation:        ## bỏ bigram (không ghi đè model chính)
	$(PY) src.model.train --lake $(LAKE) --seed $(SEED) --ngram-max 1 \
	  --model-out artifacts/tactic_model_unigram.joblib --tag unigram

sweep:           ## RUN=<run_id no-pruning>
	$(PY) src.eval.prune_sweep --lake $(LAKE) --run-id $(RUN) --repeats $(REPEATS)

figures:         ## mọi hình/bảng từ results/raw
	$(PY) src.eval.figures

dashboard:
	streamlit run app/dashboard.py --server.address 0.0.0.0 --server.port 8501

# ---- Chạy thử offline trên FIXTURE tổng hợp + môi trường toy (không cần Lean/Benchmark) ----
DEMO := data/demo

fixture:
	$(PY) tests.fixtures.mini_benchmark --out data/raw/mini_benchmark

demo: fixture    ## pipeline end-to-end offline; kết quả ghi vào data/demo (không phải số liệu báo cáo)
	G7_RUNLOG=$(DEMO)/raw/runs.jsonl $(PY) src.ingest.benchmark --bench-dir data/raw/mini_benchmark --data-version fixture --out $(DEMO)/lake/events
	$(PY) src.lake.manifest --lake $(DEMO)/lake/events --out $(DEMO)/lake/manifest.json
	G7_RUNLOG=$(DEMO)/raw/runs.jsonl $(PY) src.analytics.aggregate --lake $(DEMO)/lake/events --out $(DEMO)/raw/agg --driver-memory 2g
	G7_RUNLOG=$(DEMO)/raw/runs.jsonl $(PY) src.model.train --lake $(DEMO)/lake/events --model-out $(DEMO)/model.joblib --results $(DEMO)/raw --top 20
	$(PY) src.search.select --bench data/raw/mini_benchmark/test.json --n 30 --max-steps 4 --out $(DEMO)/sel.jsonl
	G7_RUNLOG=$(DEMO)/raw/runs.jsonl $(PY) src.search.collect --config configs/demo_toy_S.yaml --lake $(DEMO)/lake/events --results $(DEMO)/raw
	G7_RUNLOG=$(DEMO)/raw/runs.jsonl $(PY) src.eval.prune_sweep --lake $(DEMO)/lake/events --model $(DEMO)/model.joblib \
	  --results $(DEMO)/raw --repeats 3 --run-id $$(python -c "import json;print([json.loads(l) for l in open('$(DEMO)/raw/runs.jsonl')][-1]['run_id'])")
	$(PY) src.eval.figures --raw $(DEMO)/raw --out $(DEMO)/figures

clean-demo:
	rm -rf $(DEMO) data/raw/mini_benchmark
