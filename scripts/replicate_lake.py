"""Tạo lake NHÂN BẢN (×k) từ phần source=benchmark để đo khả năng mở rộng của Spark (E1).

Dữ liệu Benchmark 4 chỉ ~18 MB Parquet nên runtime Spark bị chi phí cố định lấn át. Bản sao thứ i
đổi theorem_id thành "<id>#i" (và run_id tương ứng), nên groupBy/join vẫn tách đúng từng định lý.
Đây là dữ liệu tổng hợp: chỉ dùng cho đo runtime, không dùng cho kết quả chất lượng.

    python scripts/replicate_lake.py --lake data/lake/events --factor 10 --out data/lake_rep/x10/events
"""
from __future__ import annotations

import argparse
import os
import shutil

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake", default="data/lake/events")
    ap.add_argument("--factor", type=int, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    src = ds.dataset(os.path.join(args.lake, "source=benchmark"), format="parquet", partitioning="hive")
    table = src.to_table()
    part = os.path.join(args.out, "source=benchmark", "budget_id=na")
    shutil.rmtree(args.out, ignore_errors=True)
    os.makedirs(part)
    for i in range(args.factor):
        sfx = pa.scalar(f"#{i}")
        t = table
        for col in ("theorem_id", "run_id"):
            j = t.schema.get_field_index(col)
            t = t.set_column(j, col, pc.binary_join_element_wise(t[col], sfx, ""))
        if "budget_id" in t.schema.names:      # cột partition nằm trên đường dẫn, không ghi trong file
            t = t.drop(["budget_id"])
        pq.write_table(t, os.path.join(part, f"rep{i:03d}.parquet"), compression="zstd")
    print(f"{args.factor} bản sao × {table.num_rows} event -> {args.out}")


if __name__ == "__main__":
    main()
