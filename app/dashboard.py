"""Dashboard Streamlit: streamlit run app/dashboard.py"""
import glob
import json
import os

import pandas as pd
import streamlit as st

RAW, FIG = "results/raw", "results/figures"

st.set_page_config(page_title="Proof-Search Analytics — Nhóm 7", layout="wide")
st.title("Proof-Search Analytics — Nhóm 7")

tab_agg, tab_pred, tab_search, tab_prune, tab_runs = st.tabs(
    ["Trace analytics", "Tactic predictor", "Search budget", "Pruning", "Run log"])

with tab_agg:
    tags = sorted(os.path.basename(p) for p in glob.glob(f"{RAW}/agg/*"))
    if not tags:
        st.info("Chưa có kết quả aggregate — chạy `make aggregate`.")
    else:
        base = f"{RAW}/agg/" + st.selectbox("Bộ dữ liệu", tags)
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Tactic phổ biến & failure rate")
            st.dataframe(pd.read_csv(f"{base}/tactic_stats.csv").head(30))
        with c2:
            st.subheader("Branching factor theo depth")
            st.line_chart(pd.read_csv(f"{base}/branching.csv").set_index("depth")[["avg_branching", "avg_tried"]])
        st.subheader("Chuyển tiếp tactic (cha → con)")
        st.dataframe(pd.read_csv(f"{base}/transitions.csv").head(50))
        st.subheader("Theo định lý")
        st.dataframe(pd.read_csv(f"{base}/per_theorem.csv"))

with tab_pred:
    p = f"{RAW}/predictor_metrics.json"
    if os.path.exists(p):
        m = json.load(open(p, encoding="utf-8"))
        st.dataframe(pd.DataFrame({k: v for k, v in m.items() if isinstance(v, dict) and "top1" in v}).T)
        if os.path.exists(f"{RAW}/predictor_by_domain.csv"):
            st.subheader("Top-k theo domain")
            st.dataframe(pd.read_csv(f"{RAW}/predictor_by_domain.csv"))
    else:
        st.info("Chưa train — chạy `make train`.")

with tab_search:
    p = f"{FIG}/search_runs.csv"
    if os.path.exists(p):
        st.dataframe(pd.read_csv(p))
    else:
        st.info("Chưa có run search — `make figures` sau `make baseline`.")

with tab_prune:
    for p in sorted(glob.glob(f"{RAW}/prune_sweep_*.csv")):
        if p.endswith(("_per_theorem.csv", "_lost.csv")):
            continue
        st.caption(p)
        d = pd.read_csv(p)
        st.dataframe(d)
        st.scatter_chart(d, x="avg_states_expanded", y="proof_success_rate")
        lost = p.replace(".csv", "_lost.csv")
        if os.path.exists(lost):
            st.write("Định lý baseline chứng minh được nhưng bị mất khi prune:")
            st.dataframe(pd.read_csv(lost))

with tab_runs:
    p = f"{RAW}/runs.jsonl"
    if os.path.exists(p):
        runs = [json.loads(line) for line in open(p, encoding="utf-8") if line.strip()]
        st.dataframe(pd.json_normalize(runs)[["run_id", "kind", "timestamp", "status", "data_version"]])
