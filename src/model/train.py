"""Khối 5–6 — Feature + tactic predictor.

Nhãn = tactic_head (token đầu), gom về top-N + <other>. Split dùng đúng train/val/test của
Benchmark (chia theo định lý -> không rò rỉ). Baseline = most-frequent (DummyClassifier prior);
phương pháp = TF-IDF n-gram trên proof state + SGD logistic.

    python -m src.model.train --lake data/lake/events
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.pipeline import make_pipeline

from src.common.runlog import log_run, new_run_id

OTHER = "<other>"
KS = (1, 3, 5, 10)


def tactic_head(s: pd.Series) -> pd.Series:
    return s.str.strip().str.split().str[0].fillna("")


def topk_hits(proba: np.ndarray, classes: np.ndarray, y: pd.Series, k: int) -> np.ndarray:
    """Bool từng mẫu: nhãn thật có nằm trong top-k không (nhãn ngoài classes = trượt)."""
    idx = {c: i for i, c in enumerate(classes)}
    true_idx = y.map(idx).fillna(-1).astype(int).to_numpy()
    topk = np.argsort(-proba, axis=1)[:, :k]
    return (topk == true_idx[:, None]).any(axis=1)


def build_models(seed: int, ngram_max: int, max_features: int) -> dict:
    return {
        "most_frequent": DummyClassifier(strategy="prior"),          # BASELINE
        "tfidf_sgd": make_pipeline(
            TfidfVectorizer(token_pattern=r"[^\s()\[\],:]+", ngram_range=(1, ngram_max),
                            max_features=max_features, sublinear_tf=True),
            SGDClassifier(loss="log_loss", alpha=1e-5, max_iter=15, tol=None, random_state=seed)),
    }


def load_split_data(lake: str) -> pd.DataFrame:
    df = pd.read_parquet(lake, columns=["split", "domain", "state_before", "tactic"],
                         filters=[("source", "=", "benchmark")])
    df["y"] = tactic_head(df["tactic"])
    return df


def train_eval(df: pd.DataFrame, top: int = 50, seed: int = 42, max_train: int = 300_000,
               ngram_max: int = 2, max_features: int = 200_000, eval_split: str = "test"):
    train = df[df.split == "train"].sample(frac=1, random_state=seed).head(max_train)
    test = df[df.split == eval_split]
    classes = train["y"].value_counts().index[:top]
    label = lambda s: s.where(s.isin(classes), OTHER)
    ytr, yte = label(train["y"]), label(test["y"])
    models, results, per_domain = build_models(seed, ngram_max, max_features), {}, []
    for name, m in models.items():
        t0 = time.perf_counter()
        m.fit(train["state_before"], ytr)
        fit_s = time.perf_counter() - t0
        proba = m.predict_proba(test["state_before"])
        hits = {k: topk_hits(proba, m.classes_, yte, k) for k in KS}
        results[name] = {**{f"top{k}": float(h.mean()) for k, h in hits.items()},
                         "fit_s": fit_s, "n_train": len(train), "n_test": len(test)}
        dom = test["domain"].reset_index(drop=True)
        for d, g in pd.DataFrame({f"top{k}": h for k, h in hits.items()}).groupby(dom):
            per_domain.append({"model": name, "domain": d, "n": len(g), **g.mean().to_dict()})
        print(name, {k: round(v, 4) for k, v in results[name].items()})
    return models, results, pd.DataFrame(per_domain)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake", default="data/lake/events")
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-train", type=int, default=300_000)
    ap.add_argument("--ngram-max", type=int, default=2, help="1 = ablation bỏ bigram")
    ap.add_argument("--max-features", type=int, default=200_000)
    ap.add_argument("--model-out", default="artifacts/tactic_model.joblib")
    ap.add_argument("--results", default="results/raw")
    ap.add_argument("--tag", default="", help="hậu tố tên file kết quả (vd ablation)")
    args = ap.parse_args(argv)

    df = load_split_data(args.lake)
    models, results, per_domain = train_eval(df, args.top, args.seed, args.max_train,
                                             args.ngram_max, args.max_features)
    os.makedirs(os.path.dirname(args.model_out) or ".", exist_ok=True)
    os.makedirs(args.results, exist_ok=True)
    joblib.dump(models["tfidf_sgd"], args.model_out)
    with open(args.model_out, "rb") as f:
        mhash = hashlib.sha1(f.read()).hexdigest()[:8]
    suffix = f"_{args.tag}" if args.tag else ""
    with open(os.path.join(args.results, f"predictor_metrics{suffix}.json"), "w", encoding="utf-8") as f:
        json.dump({"model_hash": mhash, "params": vars(args), **results}, f, indent=2)
    per_domain.to_csv(os.path.join(args.results, f"predictor_by_domain{suffix}.csv"), index=False)
    log_run(new_run_id("train"), "train", vars(args), {"model_hash": mhash, **results},
            status="ok", data_version="benchmark", seed=args.seed)


if __name__ == "__main__":
    main()
