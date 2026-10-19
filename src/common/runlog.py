"""Log mỗi run theo Phụ lục B: 1 dòng JSON / run trong results/raw/runs.jsonl."""
from __future__ import annotations

import datetime
import json
import os
import platform
import subprocess
import sys
import uuid

DEFAULT_PATH = "results/raw/runs.jsonl"


def _cmd(args: list[str]) -> str:
    try:
        return subprocess.check_output(args, stderr=subprocess.STDOUT, text=True, timeout=10).strip()
    except Exception:
        return "n/a"


def _version(module: str) -> str:
    try:
        return __import__(module).__version__
    except Exception:
        return "n/a"


def runlog_path() -> str:
    return os.environ.get("G7_RUNLOG", DEFAULT_PATH)


def new_run_id(name: str) -> str:
    return f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{name}-{uuid.uuid4().hex[:4]}"


def machine_info() -> dict:
    try:
        import psutil
        ram_gb = round(psutil.virtual_memory().total / 2**30, 1)
    except ImportError:
        ram_gb = None
    gpu = _cmd(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
    return {"cpu": platform.processor() or platform.machine(), "cores": os.cpu_count(),
            "ram_gb": ram_gb, "gpu": "none" if gpu == "n/a" else gpu, "os": platform.platform()}


def software_info() -> dict:
    java = _cmd(["java", "-version"]).splitlines()
    return {"python": sys.version.split()[0], "spark": _version("pyspark"),
            "pyarrow": _version("pyarrow"), "sklearn": _version("sklearn"),
            "lean": _cmd(["lean", "--version"]), "java": java[0] if java else "n/a",
            "lean_dojo": _version("lean_dojo")}


def log_run(run_id: str, kind: str, params: dict, metrics: dict, status: str,
            data_version: str, seed=None, timeout=None, log_path: str = "",
            path: str | None = None) -> dict:
    """kind: ingest | aggregate | collect | train | sweep | ..."""
    rec = {
        "run_id": run_id,
        "kind": kind,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "git_commit": _cmd(["git", "rev-parse", "--short", "HEAD"]),
        "data_version": data_version,
        "machine": machine_info(),
        "software": software_info(),
        "parameters": params,
        "seed": seed,
        "timeout": timeout,
        "metrics": metrics,
        "status": status,
        "log_path": log_path,
    }
    path = path or runlog_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
    return rec


def read_runs(path: str | None = None) -> list[dict]:
    path = path or runlog_path()
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
