"""Manifest của lake: danh sách file + số dòng + bytes + sha256 + schema_version.

    python -m src.lake.manifest --lake data/lake/events --out data/lake/manifest.json
    python -m src.lake.manifest --lake data_sample/events --verify data_sample/manifest.json
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import sys

import pyarrow.parquet as pq

from src.common.schema import SCHEMA_VERSION


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(lake: str) -> dict:
    root = pathlib.Path(lake)
    files = sorted(root.rglob("*.parquet"))
    entries = [{"path": p.relative_to(root).as_posix(), "rows": pq.ParquetFile(p).metadata.num_rows,
                "bytes": p.stat().st_size, "sha256": sha256(p)} for p in files]
    return {"schema_version": SCHEMA_VERSION,
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "files": entries,
            "total_rows": sum(e["rows"] for e in entries),
            "total_bytes": sum(e["bytes"] for e in entries)}


def verify(lake: str, manifest_path: str) -> list[str]:
    """So lake hiện tại với manifest đã lưu; trả về danh sách khác biệt."""
    saved = json.loads(pathlib.Path(manifest_path).read_text(encoding="utf-8"))
    now = {e["path"]: e for e in build_manifest(lake)["files"]}
    errs = []
    for e in saved["files"]:
        cur = now.pop(e["path"], None)
        if cur is None:
            errs.append(f"missing: {e['path']}")
        elif cur["sha256"] != e["sha256"]:
            errs.append(f"checksum differs: {e['path']}")
    errs += [f"extra: {p}" for p in now]
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake", default="data/lake/events")
    ap.add_argument("--out", default="data/lake/manifest.json")
    ap.add_argument("--verify", help="đường dẫn manifest cần kiểm tra thay vì tạo mới")
    args = ap.parse_args(argv)
    if args.verify:
        errs = verify(args.lake, args.verify)
        print("\n".join(errs) or "manifest OK")
        sys.exit(1 if errs else 0)
    manifest = build_manifest(args.lake)
    pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.out).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"{len(manifest['files'])} files, {manifest['total_rows']} rows, "
          f"{manifest['total_bytes'] / 1e6:.2f} MB -> {args.out}")


if __name__ == "__main__":
    main()
