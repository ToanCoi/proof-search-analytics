import pytest

from tests.fixtures.mini_benchmark import make


@pytest.fixture(autouse=True)
def _isolated_runlog(tmp_path, monkeypatch):
    """Test không ghi vào results/raw/runs.jsonl thật."""
    monkeypatch.setenv("G7_RUNLOG", str(tmp_path / "runs.jsonl"))


@pytest.fixture(scope="session")
def bench_dir(tmp_path_factory):
    return make(str(tmp_path_factory.mktemp("bench")), n_train=120, n_eval=30, seed=0)


@pytest.fixture(scope="session")
def lake(bench_dir, tmp_path_factory):
    from src.ingest.benchmark import ingest
    out = str(tmp_path_factory.mktemp("lake") / "events")
    ingest(bench_dir, out, "fixture-v0")
    return out
