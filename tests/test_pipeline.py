"""Ingest -> manifest -> train -> collect (toy) -> sweep trên fixture nhỏ."""
import json
import os

import pandas as pd
import pyarrow.dataset as ds

from src.common.runlog import read_runs
from src.common.schema import SCHEMA_VERSION
from src.lake.manifest import build_manifest, verify


def test_ingest_lake_layout(lake):
    parts = sorted(os.listdir(lake))
    assert parts == ["source=benchmark"]
    assert os.listdir(os.path.join(lake, "source=benchmark")) == ["budget_id=na"]
    df = pd.read_parquet(lake)
    assert set(df.split) == {"train", "val", "test"}
    assert (df.schema_version == SCHEMA_VERSION).all()
    # chuỗi tactic là đường thẳng; bước cuối finished
    g = df[df.theorem_id == df.theorem_id.iloc[0]].sort_values("step_idx")
    assert g.parent_step_idx.isna().iloc[0]
    assert g.outcome.iloc[-1] == "finished"


def test_ingest_limit_is_deterministic(bench_dir, tmp_path):
    from src.ingest.benchmark import ingest
    a = ingest(bench_dir, str(tmp_path / "a"), "v", limit=10)
    b = ingest(bench_dir, str(tmp_path / "b"), "v", limit=10)
    assert a == b and a["train"]["theorems"] == 10


def test_manifest_detects_change(lake, tmp_path):
    m = build_manifest(lake)
    assert m["total_rows"] == ds.dataset(lake, partitioning="hive").count_rows()
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(m))
    assert verify(lake, str(p)) == []
    m["files"][0]["sha256"] = "0" * 64
    p.write_text(json.dumps(m))
    assert verify(lake, str(p))


def test_train_beats_or_matches_baseline(lake):
    from src.model.train import load_split_data, train_eval
    _, results, per_domain = train_eval(load_split_data(lake), top=20, seed=0)
    assert results["tfidf_sgd"]["top1"] >= results["most_frequent"]["top1"]
    assert results["most_frequent"]["top10"] >= results["most_frequent"]["top1"]
    assert set(per_domain.model) == {"most_frequent", "tfidf_sgd"}


def test_collect_toy_then_sweep(lake, bench_dir, tmp_path):
    import joblib
    from src.eval.prune_sweep import sweep
    from src.model.policy import load_policy
    from src.model.train import load_split_data, train_eval
    from src.search.collect import collect
    from src.search.select import select

    models, _, _ = train_eval(load_split_data(lake), top=20, seed=0)
    model_path = str(tmp_path / "m.joblib")
    joblib.dump(models["tfidf_sgd"], model_path)

    thms = select(json.load(open(os.path.join(bench_dir, "test.json"), encoding="utf-8")), 8, 4, 42)
    sel = tmp_path / "sel.jsonl"
    sel.write_text("".join(json.dumps(t) + "\n" for t in thms), encoding="utf-8")
    cfg = {"run_name": "toy-S", "data_version": "toy-synthetic", "theorems": str(sel),
           "n_theorems": 8, "budget": {"budget_id": "S", "max_calls": 40, "timeout_s": 30, "max_depth": 6},
           "workers": 1, "seed": 42, "backend": "toy", "policy": "none"}
    search_lake = str(tmp_path / "events")
    run_id, metrics = collect(cfg, search_lake, results=str(tmp_path / "raw"),
                              staging_root=str(tmp_path / "staging"))
    assert metrics["n"] == 8 and metrics["events"] > 0
    assert os.listdir(os.path.join(search_lake, "source=search")) == ["budget_id=S"]
    assert read_runs()[-1]["kind"] == "collect"

    ev = pd.read_parquet(search_lake, filters=[("run_id", "=", run_id)])
    rows, _, _ = sweep(ev, load_policy(model_path), [0.0, 0.05], repeats=1)
    assert rows.proof_success_rate.iloc[0] == metrics["proof_success_rate"]
    assert rows.avg_states_expanded.iloc[0] == metrics["avg_states_expanded"]
