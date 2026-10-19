"""Spark local trên fixture. Bỏ qua nếu môi trường không có pyspark/Java (chạy trong Docker)."""
import shutil

import pytest

pyspark = pytest.importorskip("pyspark")
if not shutil.which("java"):
    pytest.skip("java not found", allow_module_level=True)


@pytest.fixture(scope="module")
def spark():
    from src.analytics.aggregate import get_spark
    s = get_spark("1g", 4)
    yield s
    s.stop()


def test_aggregate_tables(spark, lake):
    from src.analytics.aggregate import TABLES, aggregate, load_events
    ev = load_events(spark, lake, "benchmark")
    tables = {k: v.toPandas() for k, v in aggregate(ev).items()}
    assert set(tables) == set(TABLES)
    total = ev.count()
    assert tables["tactic_stats"].n.sum() == total
    assert tables["transitions"]["count"].sum() == total
    assert tables["position"]["count"].sum() == total
    # benchmark = đường thẳng: mỗi state có đúng 1 tactic được thử
    assert (tables["branching"].avg_tried == 1).all()
    pt = tables["per_theorem"]
    assert (pt.proved == 1).all()
    assert pt.states_expanded.sum() == total


def test_limit_theorems(spark, lake):
    from src.analytics.aggregate import load_events
    ev = load_events(spark, lake, "benchmark", limit_theorems=10)
    assert ev.select("theorem_id").distinct().count() == 10
