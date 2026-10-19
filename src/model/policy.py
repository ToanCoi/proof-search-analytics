"""Biến predictor thành hàm điểm policy(state_pp, tactic) -> xác suất của tactic_head."""
from __future__ import annotations

import hashlib
from functools import lru_cache

import joblib

DEFAULT_MODEL = "artifacts/tactic_model.joblib"


def model_hash(path: str = DEFAULT_MODEL) -> str:
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:8]


def load_policy(path: str = DEFAULT_MODEL):
    model = joblib.load(path)
    idx = {c: i for i, c in enumerate(model.classes_)}
    other = idx.get("<other>")

    @lru_cache(maxsize=100_000)
    def probs(state_pp: str):
        return model.predict_proba([state_pp])[0]

    def policy(state_pp: str, tactic: str) -> float:
        head = tactic.split()[0]
        i = idx.get(head, other)
        return 0.0 if i is None else float(probs(state_pp)[i])

    return policy
