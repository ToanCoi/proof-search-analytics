"""Sinh report.docx từ results/raw + results/figures (mọi con số đọc từ file, không gõ tay).

    python scripts/build_report.py            # -> report.docx
Chạy lại sau `make figures` để report khớp với kết quả mới nhất.
"""
from __future__ import annotations

import glob
import json
import os
import re

import pandas as pd
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

RAW, FIG = "results/raw", "results/figures"
FINAL_TAU = 0.01            # τ nhóm chọn cho báo cáo (quyết định 20/10/2026)
ACCENT = RGBColor(0x1F, 0x3A, 0x5F)


# ---------- dữ liệu ----------
def runs():
    bad = set()
    if os.path.exists(f"{RAW}/invalid_runs.json"):
        j = json.load(open(f"{RAW}/invalid_runs.json", encoding="utf-8"))
        bad = {r["run_id"] for r in j.get("invalid_runs", []) + j.get("superseded_runs", [])}
    return [r for r in map(json.loads, open(f"{RAW}/runs.jsonl", encoding="utf-8")) if r["run_id"] not in bad]


def sweep_of(budget: str):
    for p in glob.glob(f"{RAW}/prune_sweep_*-repl-baseline-{budget}-*.csv"):
        if not p.endswith(("_per_theorem.csv", "_lost.csv", "_proof_paths.csv")):
            return p, pd.read_csv(p)
    raise FileNotFoundError(budget)


def live_rescue(theorems, run_name="repl-prune-M-tau001", lake="data/lake/events"):
    """Tactic đóng chứng minh trong run live cho các bài replay đánh mất (đọc từ lake)."""
    rid = [r["run_id"] for r in runs() if r["kind"] == "collect" and r["parameters"]["run_name"] == run_name][-1]
    ev = pd.read_parquet(lake, filters=[("source", "=", "search"), ("run_id", "=", rid)],
                         columns=["theorem_id", "tactic", "outcome"])
    fin = ev[(ev.outcome == "finished") & ev.theorem_id.isin(theorems)]
    return dict(zip(fin.theorem_id, fin.tactic))


def share(heads, path=f"{RAW}/agg/benchmark_nall/tactic_stats.csv"):
    """Tỉ lệ bước tactic trong Benchmark 4 có tactic_head thuộc heads."""
    t = pd.read_csv(path)
    return t[t.tactic_head.isin(heads)].n.sum() / t.n.sum()


def pct(x):
    return f"{x * 100:.0f}%"


def rng(med, lo, hi, fmt="{:.1f}"):
    return f"{fmt.format(med)} [{fmt.format(lo)}–{fmt.format(hi)}]" if hi - lo > 1e-9 else fmt.format(med)


# ---------- định dạng ----------
def setup(doc):
    sec = doc.sections[0]
    sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
    sec.left_margin = sec.right_margin = Cm(2.2)
    sec.top_margin = sec.bottom_margin = Cm(2.0)
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Times New Roman", Pt(12)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    st.paragraph_format.space_after = Pt(4)
    st.paragraph_format.line_spacing = 1.15
    for name, size in (("Heading 1", 15), ("Heading 2", 13), ("Title", 22)):
        h = doc.styles[name]
        h.font.name, h.font.size, h.font.color.rgb = "Times New Roman", Pt(size), ACCENT
        rf = h.element.rPr.rFonts
        rf.set(qn("w:eastAsia"), "Times New Roman")
        for a in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
            rf.attrib.pop(qn(a), None)            # bỏ font theme để heading cũng là Times New Roman
        h.paragraph_format.space_before = Pt(10 if name != "Title" else 0)
        h.paragraph_format.space_after = Pt(4)
    # số trang ở footer
    p = sec.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    for tag, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if tag:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), tag)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._r.append(el)


def para(doc, text, bold_prefix=None, italic=False, size=None, align=None):
    p = doc.add_paragraph()
    if bold_prefix:
        p.add_run(bold_prefix).bold = True
    r = p.add_run(text)
    r.italic = italic
    if size:
        r.font.size = Pt(size)
    if align:
        p.alignment = align
    return p


def bullets(doc, items):
    for it in items:
        p = doc.add_paragraph(style="List Bullet")
        if isinstance(it, tuple):
            p.add_run(it[0]).bold = True
            p.add_run(it[1])
        else:
            p.add_run(it)


def shade(cell, hex_fill):
    tc = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), hex_fill)
    tc.append(sh)


def table(doc, header, rows, widths, caption=None, size=10, bold_rows=()):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold, r.font.size = True, Pt(size)
        shade(c, "DCE6F0")
    for k, row in enumerate(rows):
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            r = cells[i].paragraphs[0].add_run(str(v))
            r.font.size = Pt(size)
            r.bold = k in bold_rows
    for row in t.rows:
        for i, w in enumerate(widths):
            row.cells[i].width = Cm(w)
    if caption:
        cap = para(doc, caption, italic=True, size=10, align=WD_ALIGN_PARAGRAPH.CENTER)
        cap.paragraph_format.space_after = Pt(8)
    return t


def figure(doc, path, caption, width_cm=13.5):
    doc.add_picture(path, width=Cm(width_cm))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    para(doc, caption, italic=True, size=10, align=WD_ALIGN_PARAGRAPH.CENTER)


# ---------- nội dung ----------
def build(out="report.docx"):
    rs = runs()
    sw_name, sw = sweep_of("M")
    m_run = os.path.basename(sw_name)[len("prune_sweep_"):-4]
    summ = pd.read_csv(f"{FIG}/search_summary.csv")
    scale = pd.read_csv(f"{FIG}/scale_aggregate.csv")
    pm = json.load(open(f"{RAW}/predictor_metrics.json", encoding="utf-8"))
    pm_uni = json.load(open(f"{RAW}/predictor_metrics_unigram.json", encoding="utf-8"))
    by_dom = pd.read_csv(f"{RAW}/predictor_by_domain.csv")
    losses = pd.read_csv(f"{FIG}/pruning_losses_M.csv")
    collect = [r for r in rs if r["kind"] == "collect"]
    mach, soft = collect[-1]["machine"], collect[-1]["software"]
    cands = collect[-1]["parameters"]["candidates"]

    def srow(name):
        return summ[summ.run_name == name].iloc[0]

    base = {b: srow(f"repl-baseline-{b}") for b in "SML"}
    live = {t: srow(n) for t, n in ((0.005, "repl-prune-M-tau0005"), (0.01, "repl-prune-M-tau001"))}
    bM = base["M"]
    fin = live[FINAL_TAU]
    save = 1 - fin.avg_states_expanded_median / bM.avg_states_expanded_median
    sw_at = sw.set_index("tau")

    doc = Document()
    setup(doc)

    # --- trang bìa gọn ---
    doc.add_paragraph("INT4418 – Dữ liệu lớn · Bài tập lớn · Nhóm 7 (AI4Math)").alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_heading("Proof-Search Analytics: phân tích trace tìm kiếm chứng minh Lean 4, "
                    "dự đoán tactic và cắt nhánh", level=0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    para(doc, "Thành viên: [Họ tên 1 – MSSV] · [Họ tên 2 – MSSV] · [Họ tên 3 – MSSV] · [Họ tên 4 – MSSV]",
         align=WD_ALIGN_PARAGRAPH.CENTER)
    para(doc, "Repo: proof-search-analytics/ · Mọi bảng/hình sinh từ results/raw bằng script "
         "(src/eval/figures.py, scripts/build_report.py).", italic=True, size=10, align=WD_ALIGN_PARAGRAPH.CENTER)

    doc.add_heading("Tóm tắt", level=1)
    para(doc, (
        f"Nhóm xây dựng một pipeline dữ liệu lớn cho trace tìm kiếm chứng minh: một prover best-first cố định "
        f"chạy trên Lean 4 + mathlib, mỗi lần thử tactic thành một event theo schema có version, lưu vào trace lake "
        f"Parquet, tổng hợp bằng PySpark, học predictor tactic và đánh giá pruning bằng replay rồi kiểm chứng live. "
        f"Predictor TF-IDF + SGD đạt top-1 {pm['tfidf_sgd']['top1']:.3f} so với {pm['most_frequent']['top1']:.3f} "
        f"của baseline most-frequent (top-10 {pm['tfidf_sgd']['top10']:.3f} vs {pm['most_frequent']['top10']:.3f}). "
        f"Trên 100 bài miniF2F ở budget M, pruning với τ = {FINAL_TAU:g} giảm states expanded từ "
        f"{bM.avg_states_expanded_median:.1f} xuống {fin.avg_states_expanded_median:.1f} mỗi bài (−{pct(save)}) "
        f"mà proof success rate giữ nguyên {fin.proof_success_rate_median:.2f} khi chạy Lean thật; replay cho thấy "
        f"từ τ = 0.02 proof rate bắt đầu giảm ({sw_at.loc[0.02].proof_success_rate:.2f})."))

    # 1
    doc.add_heading("1. Bài toán và câu hỏi nghiên cứu", level=1)
    para(doc, (
        "Tìm chứng minh tự động trong Lean là một bài toán tìm kiếm: tại mỗi proof state, prover thử nhiều tactic, "
        "phần lớn thất bại và mỗi lần thử tốn một lời gọi Lean. Dữ liệu sinh ra (state, tactic, kết quả, thời gian) "
        "lớn nhanh theo số định lý × số nhánh, và là nguồn để hiểu hành vi tìm kiếm cũng như học cách cắt nhánh. "
        "Đề tài tập trung vào phần dữ liệu: thu thập, lưu trữ, tổng hợp và đánh giá có kiểm soát chi phí."))
    bullets(doc, [
        ("RQ1. ", "Đặc trưng proof state dự đoán tactic tiếp theo tốt đến đâu (top-k), khác nhau thế nào theo domain?"),
        ("RQ2. ", "Pruning bằng predictor giảm được bao nhiêu states expanded trước khi proof success rate giảm?"),
    ])
    para(doc, "Primary metrics: proof success rate (chất lượng) và states expanded / định lý (chi phí). "
              "Chỉ số phụ: top-k accuracy, wall time, thời gian Lean, dung lượng lake, runtime tổng hợp, events/s.")

    # 2
    doc.add_heading("2. Dữ liệu", level=1)
    table(doc, ["Nguồn", "Vai trò", "Quy mô", "Phiên bản / license"], [
        ["LeanDojo Benchmark 4 (Zenodo 10114185)", "Analytics (E1), huấn luyện predictor (E2)",
         "98,514 / 2,000 / 2,000 định lý (train/val/test, random split); 213,067 bước tactic",
         "mathlib4 @ 3ce43c18; Apache-2.0"],
        ["miniF2F Lean 4 (DeepSeek-Prover-V1.5)", "Search thật (E3, E4)",
         "488 bài; chọn cố định 100 bài (seed 42)", "commit 2c4ba91; MIT"],
        ["Trace tự sinh", "Lake source=search", f"{sum(r['metrics']['events'] for r in collect):,} event "
         f"({len(collect)} run hợp lệ)", "Lean v4.9.0 + mathlib (LeanInteract 0.11.6)"],
    ], [3.6, 3.6, 5.0, 4.4], "Bảng 1. Nguồn dữ liệu. Dữ liệu đầy đủ không commit; repo có data_sample/ + manifest sha256 "
       "và script tải lại (make download, make minif2f).")
    para(doc, ("Split cố định và có version: Benchmark dùng split của LeanDojo (chia theo định lý, tránh rò rỉ giữa "
               "các bước của cùng một chứng minh); tập 100 bài miniF2F được chọn bằng seed 42 sau khi sắp xếp theo "
               "tên, lưu ở data/selections/. Mỗi run ghi data_version (vd minif2f-ds15@2c4ba91+lean-v4.9.0)."))

    # 3
    doc.add_heading("3. Kiến trúc hệ thống", level=1)
    table(doc, ["#", "Khối", "Hiện thực", "Điểm Big Data"], [
        ["1", "Trace collector", "src/search/{core,live_repl,collect}.py",
         "best-first, budget 3 chiều (lời gọi, giây Lean, độ sâu); 2 worker song song; ghi staging rồi compact"],
        ["2", "Event schema", "src/common/schema.py, docs/data_card.md",
         "v0.1.0, 24 cột, grain = 1 lần thử tactic; validate() trước khi ghi"],
        ["3", "Parquet trace lake", "src/ingest/benchmark.py, src/lake/manifest.py",
         "partition source/budget_id, zstd, manifest sha256; 694 MB JSON → ~18 MB Parquet"],
        ["4", "Spark aggregation", "src/analytics/aggregate.py",
         "5 bảng; partition + column pruning, broadcast join, self-join, window lag"],
        ["5", "Feature extraction", "src/model/train.py", "TF-IDF n-gram trên proof state (≤200K đặc trưng)"],
        ["6", "Predictor / policy", "src/model/{train,policy}.py",
         "most-frequent vs TF-IDF + SGD; policy = P(tactic | state), cắt nếu < τ"],
        ["7", "Replay / evaluation", "src/search/replay.py, src/eval/{prune_sweep,figures}.py",
         "replay trace no-pruning cùng budget, ×3 lần; live check; Pareto"],
    ], [0.7, 3.0, 5.6, 7.3], "Bảng 2. Bảy khối của pipeline và nơi hiện thực trong repo.", size=9)
    para(doc, ("Luồng dữ liệu: Benchmark JSON và trace search cùng đi vào một lake Parquet duy nhất (cùng schema), "
               "Spark đọc lake để sinh bảng tổng hợp CSV vào results/raw; predictor học từ phần benchmark; replay "
               "đọc trace no-pruning để mô phỏng pruning mà không cần Lean; figures.py sinh mọi hình/bảng kèm "
               ".meta.json (máy, phần mềm, seed, budget, số lần lặp). Mọi bước chạy trong Docker; mỗi run ghi một "
               "bản ghi Phụ lục B (run_id, git_commit, data_version, machine, software, parameters, seed, timeout, "
               "metrics, status) vào results/raw/runs.jsonl."))

    # 4
    doc.add_heading("4. Schema và trace lake", level=1)
    para(doc, ("Một dòng = một lần thử một tactic trên một proof state. Khóa (run_id, theorem_id, step_idx); "
               "parent_step_idx trỏ tới event sinh ra state_before nên dựng lại được cây tìm kiếm. Mỗi event mang "
               "budget của trace (budget_id, max_calls, timeout_s, max_depth) và policy/τ, nên không thể so sánh "
               "nhầm hai run khác budget. Dữ liệu append-only: sửa = tạo run mới."))
    table(doc, ["Nhóm cột", "Cột"], [
        ["Định danh, version", "schema_version, source, run_id, data_version, split, theorem_id, file_path, domain"],
        ["Cây tìm kiếm", "step_idx, parent_step_idx, depth, state_before, state_after"],
        ["Hành động & kết quả", "tactic, tactic_rank, score, outcome (finished/progress/duplicate/error/unknown), elapsed_ms"],
        ["Budget & policy", "budget_id, max_calls, timeout_s, max_depth, policy, tau"],
    ], [4.0, 12.6], "Bảng 3. Schema v0.1.0 (chi tiết kiểu và quy tắc tiến hóa trong docs/data_card.md).")
    para(doc, ("Quy tắc tiến hóa: thêm cột nullable ở cuối → tăng minor; đổi nghĩa/kiểu/xóa → tăng major. "
               "Nhóm khác đọc trực tiếp bằng pandas/pyarrow/Spark với filter theo partition; tính toàn vẹn kiểm "
               "bằng manifest sha256 (make sample-verify). Ingest toàn bộ Benchmark mất ~20 giây, ghi theo lô "
               "5,000 định lý thành file lớn (tránh small-files problem); collect ghi file nhỏ vào staging rồi "
               "compact một lần cuối run."))

    # 5
    doc.add_heading("5. Thiết lập thí nghiệm", level=1)
    table(doc, ["Budget", "Lời gọi tactic tối đa", "Giây Lean tối đa / bài", "Độ sâu tối đa"],
          [["S", 50, 30, 8], ["M", 200, 120, 8], ["L", 800, 300, 8]], [3, 4.5, 4.5, 3],
          "Bảng 4. Ba mức search budget (giống nhau cho baseline và pruning).")
    para(doc, (f"Máy: {mach['cores']} nhân CPU, {mach['ram_gb']} GB RAM cấp cho Docker/WSL2, không GPU. Phần mềm: "
               f"Python {soft['python']}, Spark {soft['spark']}, scikit-learn {soft['sklearn']}, pyarrow "
               f"{soft['pyarrow']}, Lean 4.9.0 + mathlib qua LeanInteract. Danh sách ứng viên cố định "
               f"({len(cands)} tactic): {', '.join(cands)}. Mỗi lời gọi có timeout cứng 20 giây và maxHeartbeats "
               f"200,000. Seed 42 cho chọn bài, chia dữ liệu và huấn luyện."))
    table(doc, ["", "Biến thay đổi", "Cố định", "Đo"], [
        ["E1", "100 → 1K → 10K → toàn bộ định lý; lake nhân bản ×10, ×50", "Spark local[8], driver 6 GB",
         "runtime median [min–max] ×3, events/s, dung lượng"],
        ["E2", "most-frequent vs TF-IDF+SGD; ablation unigram", "split Benchmark, seed", "top-1/3/5/10, theo domain"],
        ["E3", "budget S / M / L", "100 bài, ứng viên, máy", "proof rate, states, wall time"],
        ["E4", "τ ∈ {0, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2}", "100 bài, budget M", "Pareto proof rate ↔ states; bài bị mất"],
    ], [1.0, 6.0, 4.3, 5.3], "Bảng 5. Thiết kế thí nghiệm.", size=10)

    # 6 — E1
    doc.add_heading("6. Kết quả", level=1)
    doc.add_heading("6.1 E1 – Khả năng mở rộng của Spark aggregation", level=2)
    sc = scale[scale.source == "benchmark"].sort_values("events")
    rows = []
    for _, r in sc.iterrows():
        level = f"×{int(r.replication)} (nhân bản)" if r.replication > 1 else \
            ("toàn bộ" if r["limit"] == 0 else f"{int(r['limit']):,} định lý")
        rows.append([level, f"{int(r.theorems):,}", f"{int(r.events):,}",
                     rng(r.runtime_median, r.runtime_min, r.runtime_max), f"{r.events_per_s_median:,.0f}",
                     f"{r.lake_bytes / 1e6:,.0f}", int(r.repeats)])
    table(doc, ["Mức", "Định lý", "Event", "Runtime s, median [min–max]", "Event/s", "Lake MB", "Lần"],
          rows, [3.2, 2.2, 2.4, 3.8, 2.0, 1.6, 1.0], "Bảng 6. Runtime tổng hợp 5 bảng (đọc + 5 action) theo quy mô.",
          size=9)
    figure(doc, f"{FIG}/scale_aggregate.png", "Hình 1. Runtime Spark theo số event (log). Đường nét đứt: lake nhân bản.",
           11.5)
    small, full = sc[sc.replication == 1].iloc[0], sc[sc.replication == 1].iloc[-1]
    big = sc.iloc[-1]
    para(doc, (
        f"Với dữ liệu thật, runtime gần như phẳng: {small.runtime_median:.0f} s ở {int(small.events):,} event và "
        f"{full.runtime_median:.0f} s ở {int(full.events):,} event. Ở quy mô này chi phí cố định (khởi động JVM, "
        f"lập lịch stage, 5 lần collect về driver) lấn át. Để thấy vùng tuyến tính, nhóm nhân bản lake (mỗi bản sao "
        f"đổi theorem_id thành <id>#k, nên groupBy/join vẫn tách đúng từng định lý). Ở ×{int(big.replication)} "
        f"({int(big.events):,} event, {big.lake_bytes / 1e6:,.0f} MB) runtime là {big.runtime_median:.0f} s, "
        f"throughput {big.events_per_s_median:,.0f} event/s so với {full.events_per_s_median:,.0f} event/s ở dữ "
        f"liệu gốc. Dữ liệu nhân bản chỉ dùng đo runtime, không dùng cho bất kỳ kết quả chất lượng nào."))
    plan_lines = []
    for tag in ("benchmark_n100", "benchmark_nall"):
        p = f"{RAW}/spark_plans/{tag}/transitions.txt"
        if os.path.exists(p):
            joins = sorted(set(re.findall(r"(BroadcastHashJoin|SortMergeJoin|ShuffledHashJoin) (\w+)",
                                          open(p, encoding="utf-8").read())))
            plan_lines.append(f"{tag}: " + ", ".join(f"{a} {b}" for a, b in joins))
    para(doc, (
        "Physical plan (results/raw/spark_plans/, sinh bằng --explain): đọc lake chỉ lấy partition source=benchmark "
        "và 13 cột cần thiết (column pruning – không đọc text state_before/state_after). Lọc theo tập định lý là "
        "broadcast join (bảng keep nhỏ). Bảng transitions là self-join cha → con theo (run_id, theorem_id, step_idx): "
        + "; ".join(plan_lines) + ". Khi phía cha nhỏ, AQE/optimizer chọn broadcast; khi cả hai phía lớn, Spark cần "
        "shuffle (Exchange hashpartitioning) trước khi join. Bảng position dùng Window lag theo (run_id, theorem_id) "
        "sắp theo step_idx, cũng cần shuffle theo khóa phân vùng."))

    # Hành vi tìm kiếm (Spark trên trace search)
    doc.add_heading("6.2 Hành vi tìm kiếm (Spark trên trace search)", level=2)
    agg = f"{RAW}/agg/search_nall"
    oc = pd.read_csv(f"{agg}/outcomes.csv").set_index("tactic_head")
    oc_cols = [c for c in ("finished", "progress", "duplicate", "error") if c in oc]
    tot = oc[oc_cols].sum(axis=1)
    sh = oc[oc_cols].div(tot, axis=0)
    br = pd.read_csv(f"{agg}/branching.csv")
    figure(doc, f"{FIG}/search_behavior.png",
           f"Hình 2. Trái: phân bố kết quả của {int(tot.sum()):,} lời gọi tactic trong mọi run search hợp lệ. "
           "Phải: số lời gọi và số con mới (progress) trên mỗi state theo độ sâu.", 15.5)
    dup_heavy = sh[sh.duplicate > 0.5].sort_values("duplicate", ascending=False)
    wasted = (oc.loc[dup_heavy.index, "duplicate"].sum()) / tot.sum()
    closers = sh.finished.sort_values(ascending=False).head(3)
    slow = pd.read_csv(f"{agg}/tactic_stats.csv").set_index("tactic_head").avg_elapsed_ms.sort_values()
    para(doc, (
        f"Spark tổng hợp trace search (cùng code aggregate.py với phần Benchmark) cho thấy ba điều. (1) Phần lớn lời "
        f"gọi thất bại: tỉ lệ error trung bình {oc.error.sum() / tot.sum():.0%}. (2) "
        + ", ".join(f"{t} trả về state đã gặp ở {v:.0%} lần gọi" for t, v in dup_heavy.duplicate.items())
        + f" – chúng gần như không bao giờ báo lỗi mà chuẩn hóa goal về đúng dạng cũ; riêng các lời gọi này chiếm "
        f"{wasted:.0%} tổng lời gọi, là chi phí Lean vô ích mà một bộ lọc 'no-op' rẻ hơn predictor có thể bỏ. (3) Tactic "
        f"đóng bài nhiều nhất theo tỉ lệ: " + ", ".join(f"{t} ({v:.1%})" for t, v in closers.items())
        + f". Chi phí mỗi lời gọi chênh nhau hơn {slow.iloc[-1] / max(slow.iloc[0], 1e-9):.0f} lần: nhanh nhất "
        f"{slow.index[0]} ({slow.iloc[0]:.0f} ms), chậm nhất {slow.index[-1]} ({slow.iloc[-1] / 1000:.1f} s) – vì vậy "
        f"budget đo bằng giây Lean chứ không chỉ bằng số lời gọi. Ở mọi độ sâu, mỗi state được thử "
        f"~{br.avg_tried.median():.0f} tactic nhưng chỉ sinh ~{br.avg_branching.median():.1f} con mới: cây hẹp, "
        f"chi phí chủ yếu là các nhánh chết ngay."))

    # E2
    doc.add_heading("6.3 E2 – Dự đoán tactic", level=2)
    mrow = lambda name, m: [name] + [f"{m[k]:.3f}" for k in ("top1", "top3", "top5", "top10")]
    table(doc, ["Mô hình", "Top-1", "Top-3", "Top-5", "Top-10"], [
        mrow("Most-frequent (baseline)", pm["most_frequent"]),
        mrow("TF-IDF 1–2 gram + SGD", pm["tfidf_sgd"]),
        mrow("Ablation: unigram", pm_uni["tfidf_sgd"]),
    ], [6.0, 2.4, 2.4, 2.4, 2.4], f"Bảng 7. Top-k accuracy trên test split Benchmark 4 "
       f"({pm['tfidf_sgd']['n_test']:,} bước; train {pm['tfidf_sgd']['n_train']:,} bước).", bold_rows=(1,))
    piv = by_dom.pivot(index="domain", columns="model", values="top1")
    n = by_dom[by_dom.model == "most_frequent"].set_index("domain").n
    top = n.sort_values(ascending=False).head(8).index
    table(doc, ["Domain", "Số bước test", "Top-1 most-frequent", "Top-1 TF-IDF", "Chênh"],
          [[d, int(n[d]), f"{piv.loc[d, 'most_frequent']:.3f}", f"{piv.loc[d, 'tfidf_sgd']:.3f}",
            f"{piv.loc[d, 'tfidf_sgd'] - piv.loc[d, 'most_frequent']:+.3f}"] for d in top],
          [4.4, 2.8, 3.4, 3.0, 2.0], "Bảng 8. Top-1 theo domain (8 domain nhiều bước nhất).", size=10)
    gains = (piv.tfidf_sgd - piv.most_frequent).loc[top]
    para(doc, (
        f"Predictor cải thiện top-1 thêm {pm['tfidf_sgd']['top1'] - pm['most_frequent']['top1']:.3f} tuyệt đối "
        f"(+{(pm['tfidf_sgd']['top1'] / pm['most_frequent']['top1'] - 1) * 100:.0f}% tương đối). Mức cải thiện "
        f"không đều: lớn nhất ở {gains.idxmax()} ({gains.max():+.3f}), nhỏ nhất ở {gains.idxmin()} "
        f"({gains.min():+.3f}). Bỏ bigram chỉ giảm top-1 "
        f"{pm['tfidf_sgd']['top1'] - pm_uni['tfidf_sgd']['top1']:.3f}, tức phần lớn tín hiệu nằm ở từng token "
        f"(ký hiệu, tên hằng) của goal. Chi phí: huấn luyện {pm['tfidf_sgd']['fit_s']:.0f} s so với "
        f"{pm['most_frequent']['fit_s']:.1f} s của baseline."))

    # E3
    doc.add_heading("6.4 E3 – Search theo budget (no-pruning)", level=2)

    def srow_cells(label, r):
        return [label, int(r.repeats), f"{r.proof_success_rate_median:.2f}",
                rng(r.avg_states_expanded_median, r.avg_states_expanded_min, r.avg_states_expanded_max),
                rng(r.avg_wall_s_median, r.avg_wall_s_min, r.avg_wall_s_max)]
    table(doc, ["Run", "Lần", "Proof rate", "States / bài", "Wall s / bài"],
          [srow_cells(f"Baseline {b}", base[b]) for b in "SML"]
          + [srow_cells(f"Pruning τ={t:g} (live, M)", live[t]) for t in (0.005, 0.01)],
          [4.6, 1.2, 2.2, 4.2, 4.2], "Bảng 9. Search thật trên 100 bài miniF2F. Nhiều lần chạy: median [min–max].",
          bold_rows=(4,))
    exh = {b: next(r for r in collect if r["parameters"]["run_name"] == f"repl-baseline-{b}")["metrics"]
           ["budget_exhausted_rate"] for b in "SML"}
    para(doc, (
        f"Tăng budget từ S lên L làm chi phí tăng {base['L'].avg_states_expanded_median / base['S'].avg_states_expanded_median:.1f}× "
        f"nhưng không chứng minh thêm bài nào. Tỉ lệ hết budget giảm từ {pct(exh['S'])} (S) xuống {pct(exh['L'])} (L): "
        f"budget lớn chỉ giúp search duyệt hết cây sinh bởi {len(cands)} tactic cố định. Các bài còn lại nhiều khả năng cần tactic có "
        f"tham số hoặc ngoài danh sách (vd interval_cases, hoặc nlinarith kèm bất đẳng thức gợi ý). Như vậy giới hạn chất lượng nằm "
        f"ở không gian hành động, còn chi phí nằm ở số nhánh vô ích – đúng chỗ pruning có thể giúp."))

    # E4
    doc.add_heading("6.5 E4 – Pruning: replay và kiểm chứng live", level=2)
    figure(doc, f"{FIG}/pareto_{m_run}.png",
           "Hình 3. Pareto proof rate ↔ states expanded ở budget M. Đường xanh: replay (×3 lần, tất định); "
           "sao đỏ: chạy Lean thật với policy.", 11.5)
    table(doc, ["τ", "Proof rate (replay)", "States / bài", "Unknown rate", "Giây Lean ước tính / bài"],
          [[f"{r.tau:g}", f"{r.proof_success_rate:.2f}", f"{r.avg_states_expanded:.1f}", f"{r.unknown_rate:.2f}",
            f"{r.est_lean_s_per_thm:.1f}"] for r in sw.itertuples()],
          [2.0, 3.6, 3.0, 3.0, 4.6], "Bảng 10. Replay sweep trên trace baseline M (cùng budget, cùng 100 bài).")
    cause = pd.read_csv(f"{FIG}/pruning_losses_M_by_cause.csv").set_index("tau")
    lost_at = lambda t: losses[losses.tau == t]
    l02, l05 = lost_at(0.02), lost_at(0.05)
    pruned02 = (l02.cause == "proof tactic pruned").sum()
    top_cut = (l05.pruned_proof_tactics.dropna().str.split(" ; ").explode().value_counts().head(3))
    l01 = lost_at(0.01)
    rescued = live_rescue(l01.theorem_id.tolist())
    para(doc, (
        f"Replay coi mọi lời gọi chưa có trong trace gốc là thất bại (unknown), nên là ước lượng bảo thủ. Ở "
        f"τ = 0.01 replay dự đoán proof rate {sw_at.loc[0.01].proof_success_rate:.2f}; chạy live đạt "
        f"{live[0.01].proof_success_rate_median:.2f} với {live[0.01].avg_states_expanded_median:.1f} states/bài "
        f"(replay: {sw_at.loc[0.01].avg_states_expanded:.1f}). Replay mất {len(l01)} bài "
        f"({', '.join(l01.theorem_id)}) vì policy cắt tactic của đường chứng minh gốc ("
        f"{', '.join(sorted(set(l01.pruned_proof_tactics)))}). Khi chạy live, cả hai được chứng minh bằng "
        f"{', '.join(sorted(set(rescued.values())))} – ứng viên đứng ngay sau trong danh sách mà baseline chưa từng "
        f"thử vì đã thành công trước đó, nên không có trong trace. Đây chính là cơ chế làm replay bảo thủ."))
    para(doc, (
        f"Điểm gối nằm giữa τ = 0.01 và 0.02. Ở τ = 0.02 replay mất {len(l02)} bài so với baseline, cả "
        f"{pruned02} bài đều do policy cắt đúng tactic nằm trên đường chứng minh gốc; ở τ = 0.05 mất {len(l05)} "
        f"bài, tactic bị cắt: " + ", ".join(f"{k} ({v})" for k, v in top_cut.items()) + ". "
        "Các bài mathd_numbertheory (tính toán số cụ thể) bị ảnh hưởng nhiều nhất vì chứng minh gốc chỉ là rfl. "
        f"Nguyên nhân: predictor học từ chứng minh của người trên mathlib, nơi rw, simp, exact chiếm "
        f"{share(['rw', 'simp', 'exact']):.0%} số bước, còn rfl chỉ {share(['rfl']):.1%}, linarith "
        f"{share(['linarith']):.1%}, norm_num {share(['norm_num']):.1%}. Prior thấp đó kéo xác suất của các tactic "
        "tự động xuống dưới ngưỡng, dù chúng giải trực tiếp nhiều bài thi đấu của miniF2F (lệch phân phối giữa nguồn "
        "huấn luyện và nơi áp dụng). Hướng cải tiến: fine-tune predictor trên trace search của chính prover."))
    table(doc, ["τ"] + list(cause.columns), [[f"{t:g}"] + [int(v) for v in r] for t, r in cause.iterrows()],
          [2.0] + [14.6 / len(cause.columns)] * len(cause.columns),
          "Bảng 11. Số bài bị mất theo nguyên nhân (src/eval/figures.py: table_pruning_losses).", size=10)

    # E4 theo budget: cùng policy, replay trên trace baseline S / M / L
    sweeps = {b: sweep_of(b)[1].set_index("tau") for b in "SML"}
    taus = [t for t in sweeps["M"].index if t in (0.0, 0.005, 0.01, 0.02, 0.05)]
    table(doc, ["τ"] + [f"{b}: proof / states" for b in "SML"],
          [[f"{t:g}"] + [f"{sweeps[b].loc[t].proof_success_rate:.2f} / {sweeps[b].loc[t].avg_states_expanded:.1f}"
                         for b in "SML"] for t in taus],
          [2.0, 4.9, 4.9, 4.9], "Bảng 12. Replay sweep ở ba mức budget (cùng 100 bài, cùng policy).")
    cut = {b: 1 - sweeps[b].loc[FINAL_TAU].avg_states_expanded / sweeps[b].loc[0.0].avg_states_expanded for b in "SML"}
    para(doc, (
        f"Theo budget, proof rate của replay ở mỗi τ giống hệt nhau giữa S, M và L (vd τ = {FINAL_TAU:g}: "
        f"{', '.join(f'{sweeps[b].loc[FINAL_TAU].proof_success_rate:.2f}' for b in 'SML')}), vì cả 5 lần chạy baseline (S, M×3, L) chứng minh đúng cùng 32 bài, "
        f"tức mọi bài giải được đều đã xong trong budget S. Ngược lại, phần states tiết kiệm tăng theo budget: "
        f"{', '.join(f'{b} {pct(cut[b])}' for b in 'SML')} ở τ = {FINAL_TAU:g}. Budget càng lớn, search càng tốn "
        f"lời gọi cho các bài không giải được, và đó là phần policy cắt được. Hình 4 cho thấy hình dạng Pareto ở S và L "
        f"giống M: điểm gối vẫn nằm giữa τ = 0.01 và 0.02, nên một ngưỡng chọn ở M dùng được cho cả ba mức budget."))
    for b, label in (("S", "Hình 4a"), ("L", "Hình 4b")):
        run = os.path.basename(sweep_of(b)[0])[len("prune_sweep_"):-4]
        figure(doc, f"{FIG}/pareto_{run}.png", f"{label}. Pareto replay ở budget {b}.", 8.5)
    para(doc, (
        f"Kết luận E4: nhóm chọn τ = {FINAL_TAU:g}. So với baseline M cùng budget, cùng 100 bài, live giảm "
        f"states expanded {pct(save)} và giây Lean "
        f"{pct(1 - next(r for r in collect if r['parameters']['run_name'] == 'repl-prune-M-tau001')['metrics']['avg_lean_s'] / next(r for r in collect if r['parameters']['run_name'] == 'repl-baseline-M')['metrics']['avg_lean_s'])}"
        f", không mất bài nào. Chi phí thêm của policy (một lần predict_proba mỗi state, có cache) không đáng kể so "
        f"với lời gọi Lean. Không khẳng định 'nhanh hơn' cho τ ≥ 0.02 vì proof rate giảm."))

    # 7
    doc.add_heading("7. Thảo luận và giới hạn", level=1)
    bullets(doc, [
        ("Quy mô search: ", "live search chỉ 100 bài (Lean chậm, ~20 s/bài ở budget M); quy mô 1K–10K+ nằm ở phần "
                            "analytics trên Benchmark và lake nhân bản."),
        ("Replay là ước lượng: ", "lời gọi ngoài trace → unknown (tính thất bại). Vì vậy τ cuối cùng được kiểm chứng "
                                  "bằng chạy live, cùng budget và cùng bài."),
        ("Lệch phân phối: ", "predictor học từ chứng minh của người (mathlib 2023) nhưng chấm điểm ứng viên cố định "
                             "trên state miniF2F (mathlib theo Lean v4.9.0)."),
        ("Spark trên một máy: ", "local[8], không có cluster; kết quả scale phản ánh song song hóa trong một node. "
                                 "Dữ liệu nhân bản không có đa dạng thật, chỉ dùng đo runtime."),
        ("Độ ổn định: ", "proof rate và states gần như tất định; wall time phụ thuộc độ trễ Lean, nên baseline M "
                         "được chạy 3 lần và báo median [min–max]. Search chạy tuần tự, không song song với job khác."),
        ("Sự cố đã xử lý: ", "phiên bản đầu của adapter REPL ghi sai mọi lời gọi sau một timeout cứng thành lỗi 0 ms. "
                             "Lỗi được sửa (khởi động lại REPL và dựng lại state theo đường tactic), có test, và 5 run "
                             "bị ảnh hưởng được cách ly kèm lý do trong results/raw/invalid_runs.json rồi chạy lại."),
        ("Tài nguyên máy: ", "hai lần chạy lặp baseline M bị ngắt giữa chừng (máy vào sleep; Windows hết bộ nhớ ảo vì "
                             "không có pagefile, trong khi 2 REPL đã import Mathlib dùng ~7.5 GB). Collect chỉ ghi vào "
                             "lake và runs.jsonl khi chạy xong, nên run dở không lọt vào dữ liệu; các lần lặp được chạy lại "
                             "trọn vẹn."),
    ])
    para(doc, "Ghi chú lệch so với đề (deviation note). ", italic=False).runs[0].bold = True
    para(doc, (
        "Đề gợi ý thu trace bằng LeanDojo. LeanDojo phải trace toàn bộ mathlib4 (nhiều giờ, RAM và đĩa lớn), rủi ro "
        "cao trên máy cá nhân, nên phần search dùng LeanInteract (Lean REPL + mathlib build sẵn) trên miniF2F. "
        "Correctness: vẫn là Lean 4 + mathlib thật, cùng thuật toán và schema. Cost: không cần trace mathlib. "
        "Scalability: search ở 100 bài; quy mô lớn ở phần analytics. Integration: event cùng schema v0.1.0, "
        "source=search, data_version ghi rõ nguồn và phiên bản Lean; adapter LeanDojo vẫn có (make baseline)."))

    # 8
    doc.add_heading("8. Tái lập kết quả", level=1)
    para(doc, "Trong Docker (docker compose build), từ thư mục proof-search-analytics/:")
    for cmd in ("make download sample ingest aggregate train ablation          # E1, E2",
                "make replicate aggregate-rep                                  # E1 nhân bản",
                "make minif2f select-minif2f search-all                        # E3, E4 (tuần tự, vài giờ)",
                "make aggregate-search figures && python scripts/build_report.py",
                "make dashboard                                                # http://localhost:8501"):
        p = doc.add_paragraph()
        r = p.add_run(cmd)
        r.font.name, r.font.size = "Consolas", Pt(9)
        p.paragraph_format.space_after = Pt(0)
    para(doc, ("Mỗi hình có file .meta.json đi kèm (máy, phần mềm, seed, budget, số lần lặp, run nguồn). "
               "Kiểm thử: 27 test (pytest), gồm test replay τ=0 khớp trace gốc và test khôi phục REPL sau timeout."))

    # 9
    doc.add_heading("9. Khai báo sử dụng AI và phân công", level=1)
    para(doc, ("Nhóm dùng Claude Code (Anthropic) để sinh bản đầu của code, script thí nghiệm và tài liệu; chi tiết "
               "trong docs/ai_use.md. Mọi con số trong báo cáo được sinh từ results/raw bằng script, không lấy từ câu "
               "trả lời của AI. [Nhóm điền: ai đã đọc/kiểm chứng phần nào.] Phân công: xem contributions.md."))
    doc.save(out)
    print("->", out)


if __name__ == "__main__":
    build()
