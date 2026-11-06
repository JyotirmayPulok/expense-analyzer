"""Personal Expense Analyzer — Streamlit UI."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from core import analytics as an
from core.common import DISCLAIMER, MAX_UNIQUE_DESCRIPTIONS, AnalyzerError, categorize_prompt, unique_descriptions
from core.gemini_llm import FALLBACK_MODELS, categorize, insights, list_models, make_client
from core.parser import AMOUNT_MODES, MAX_ROWS, SUPPORTED_TYPES, Mapping, apply_mapping, guess_mapping, read_table
from core.report import build_pdf
from core.schema import CATEGORIES, INCOME_CATEGORIES, InsightsResult
from core.theme import CATEGORY_COLORS, CORAL, CURRENCIES, EMERALD, GOLD, INK, money

load_dotenv()
ROOT = Path(__file__).parent
SAMPLES = ROOT / "samples"
EXPENSE_CATS = [c for c in CATEGORIES if c not in INCOME_CATEGORIES and c not in an.NOT_SPENDING]

st.set_page_config(page_title="Personal Expense Analyzer", page_icon="💸", layout="wide")

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@400;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stButton button {font-family: 'DM Sans', sans-serif;}
.block-container {padding-top: 1.4rem; max-width: 1280px;}
[data-testid="stSidebar"] {background: #0B3B2E;}
[data-testid="stSidebar"] * {color: #E7F5EC;}
[data-testid="stSidebar"] input, [data-testid="stSidebar"] [data-baseweb="select"] * {color: #0B3B2E !important;}
[data-testid="stSidebar"] .stAlert * {color: #0B3B2E !important;}
.ledger {display:flex; align-items:center; justify-content:space-between; gap:1rem; flex-wrap:wrap;
         background: repeating-linear-gradient(0deg,#FFFDF5 0 27px,#E6F2EB 27px 28px); border:1px solid #CFE6D8;
         border-left: 10px solid #059669; border-radius: 6px; padding: 1rem 1.4rem; margin-bottom: 1rem;}
.ledger h1 {font-family:'DM Serif Display', serif; color:#0B3B2E; font-size:2.3rem; margin:0; line-height:1.1;}
.ledger p {color:#335B4C; margin:.25rem 0 0; font-size:.98rem;}
.stamp {border:2px dashed #D97706; color:#B45309; border-radius:8px; padding:.35rem .8rem; font-weight:700;
        transform: rotate(-3deg); font-size:.85rem; background:#FFFBEB;}
.kpi {background:white; border-radius:10px; padding:.8rem 1rem; border:1px solid #DDEBE2; border-top:5px solid var(--c);}
.kpi .v {font-size:1.55rem; font-weight:700; color:var(--c); line-height:1.2;}
.kpi .l {font-size:.8rem; color:#64748B; text-transform:uppercase; letter-spacing:.06em;}
.kpi .s {font-size:.78rem; color:#64748B;}
.step {display:inline-block; padding:.2rem .7rem; border-radius:999px; font-size:.82rem; margin-right:.3rem;
       background:#E6F2EB; color:#0B3B2E;}
.step.done {background:#059669; color:white;}
.flag {border-left:5px solid var(--c); background:white; padding:.55rem .8rem; border-radius:6px; margin-bottom:.45rem;
       border-top:1px solid #EEE; border-right:1px solid #EEE; border-bottom:1px solid #EEE;}
.pattern {background:#FFFDF5; border:1px solid #F1E3BC; border-radius:8px; padding:.7rem .9rem; margin-bottom:.5rem;}
.pattern b {color:#0B3B2E;}
.muted {color:#64748B; font-size:.85rem;}
</style>
""",
    unsafe_allow_html=True,
)

# ---------- state ----------
ss = st.session_state
for key, val in {"raw": None, "raw_name": "", "tx": None, "dropped": 0, "insights": None, "cat_source": "",
                 "ins_source": "", "budgets": {}, "source": "", "edit_rev": 0}.items():
    ss.setdefault(key, val)


@st.cache_data(ttl=3600, show_spinner=False)
def gemini_models(key: str) -> list[str]:
    return list_models(key)


@st.cache_data(show_spinner=False)
def load_demo() -> tuple[pd.DataFrame, dict]:
    path = SAMPLES / "sample_statement.csv"
    raw = read_table(path.read_bytes(), path.name)
    tx, _ = apply_mapping(raw, guess_mapping(raw))
    demo = json.loads((SAMPLES / "sample_analysis.json").read_text())
    return an.apply_categories(tx, {k: tuple(v) for k, v in demo["categories"].items()}), demo


def reset(keep_raw: bool = False) -> None:
    for k in ("tx", "insights", "budgets"):
        ss[k] = {} if k == "budgets" else None
    ss.cat_source = ss.ins_source = ""
    ss.edit_rev += 1
    for k in [k for k in ss if str(k).startswith("bud_")]:
        del ss[k]
    if not keep_raw:
        ss.raw, ss.raw_name, ss.source = None, "", ""


# ---------- sidebar ----------
with st.sidebar:
    st.markdown("## 💸 Settings")
    demo_mode = st.toggle("Demo mode (no API key needed)", value=False,
                          help="Loads a synthetic 3-month BDT statement with pre-generated categories and insights.")
    cur_label = st.selectbox("Currency", list(CURRENCIES), index=0)
    SYM, CODE = CURRENCIES[cur_label]
    api_key = st.text_input("Gemini API key", type="password", disabled=demo_mode,
                            value=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", ""),
                            help="Free key from aistudio.google.com. Kept only in this browser session.")
    model = st.selectbox("Gemini model", gemini_models(api_key) if api_key else FALLBACK_MODELS, disabled=demo_mode,
                         help="Flash-Lite models have the highest free-tier limits.")
    st.caption("⚠️ Free-tier inputs may be used by Google to improve its products.")
    st.markdown("### 🔒 Privacy")
    st.markdown(
        f"- Your file is parsed **on this computer**; all totals are computed locally with pandas.\n"
        f"- Card, account and phone numbers, emails and long reference IDs are **masked** before anything is sent.\n"
        f"- Categorising sends only **unique masked descriptions + money direction** (max {MAX_UNIQUE_DESCRIPTIONS}) "
        f"in **one** request. Insights send only **aggregated totals**.\n"
        f"- Up to **{MAX_ROWS:,} rows** per statement are analysed.")
    st.divider()
    st.caption(DISCLAIMER)
    if ss.tx is not None and not demo_mode and st.button("🔄 Start over", width="stretch"):
        reset()
        st.rerun()

# ---------- header ----------
st.markdown(
    '<div class="ledger"><div><h1>Personal Expense Analyzer</h1>'
    "<p>Upload a bank or mobile-wallet statement → categorise it with Gemini → see where your money goes, "
    "set budgets and download a report.</p></div>"
    '<div class="stamp">🔒 MASKED BEFORE AI</div></div>',
    unsafe_allow_html=True,
)

# ---------- data source ----------
if demo_mode:
    if ss.source != "demo":
        reset()
        tx, demo = load_demo()
        ss.tx, ss.source = tx.copy(), "demo"
        ss.insights = InsightsResult(**demo["insights"])
        ss.cat_source = ss.ins_source = "demo data (pre-generated, not a live Gemini call)"
        ss.raw_name = "sample_statement.csv (synthetic)"
elif ss.source == "demo":
    reset()

if ss.tx is None:
    st.markdown('<span class="step">① Upload</span><span class="step">② Map columns</span>'
                '<span class="step">③ Categorise</span><span class="step">④ Insights</span>', unsafe_allow_html=True)
    up_col, help_col = st.columns([3, 2], gap="large")
    with up_col:
        upload = st.file_uploader("Statement file (CSV, Excel, or text-based PDF)", type=SUPPORTED_TYPES)
        if upload is not None and upload.name != ss.raw_name:
            try:
                ss.raw, ss.raw_name, ss.source = read_table(upload.getvalue(), upload.name), upload.name, "upload"
            except AnalyzerError as e:
                st.error(str(e))
        if st.button("Use the synthetic sample statement instead"):
            p = SAMPLES / "sample_statement.csv"
            ss.raw, ss.raw_name, ss.source = read_table(p.read_bytes(), p.name), p.name, "upload"
    with help_col:
        st.info("**Tip:** most banks and bKash/Nagad let you export statements as CSV or Excel. "
                "Scanned PDFs are not supported. Turn on **Demo mode** in the sidebar to explore without a file.")

    if ss.raw is not None:
        raw = ss.raw
        st.markdown(f"#### ② Map the columns of `{ss.raw_name}`")
        st.caption("Preview of the first rows (stays on this computer).")
        st.dataframe(raw.head(6), width="stretch", hide_index=True)
        g = guess_mapping(raw)
        cols = list(raw.columns)
        idx = lambda c: cols.index(c) if c in cols else 0  # noqa: E731
        with st.form("mapping"):
            a, b, c = st.columns(3)
            date_col = a.selectbox("Date column", cols, index=idx(g.date))
            desc_col = b.selectbox("Description column", cols, index=idx(g.description))
            modes = list(AMOUNT_MODES)
            mode = c.radio("Amounts are in…", modes, index=modes.index(g.mode), format_func=AMOUNT_MODES.get)
            a, b, c = st.columns(3)
            amount_col = a.selectbox("Amount column", cols, index=idx(g.amount or g.debit or cols[-1]),
                                     help="Used for 'one amount column' and 'amount + Dr/Cr'.")
            debit_col = b.selectbox("Debit (money out) column", cols, index=idx(g.debit or cols[-1]))
            credit_col = c.selectbox("Credit (money in) column", cols, index=idx(g.credit or cols[-1]))
            a, b, c = st.columns(3)
            type_col = a.selectbox("Dr/Cr type column", cols, index=idx(g.type_col or cols[-1]))
            dayfirst = b.checkbox("Dates are day-first (31/12/2026)", value=True)
            flip = c.checkbox("Spending is shown as positive numbers (flip sign)", value=False,
                              help="Only for 'one amount column' files where purchases are positive.")
            go_map = st.form_submit_button("Parse statement →", type="primary")
        if go_map:
            m = Mapping(date_col, desc_col, mode, amount=amount_col, debit=debit_col, credit=credit_col,
                        type_col=type_col, dayfirst=dayfirst, flip_sign=flip)
            try:
                tx, dropped = apply_mapping(raw, m)
                ss.tx, ss.dropped = an.apply_categories(tx), dropped
                ss.cat_source = "offline keyword rules"
                st.rerun()
            except AnalyzerError as e:
                st.error(str(e))
    st.stop()

# ---------- analysis available ----------
tx_all: pd.DataFrame = ss.tx
has_ai_cats = not ss.cat_source.startswith("offline")
st.markdown(
    f'<span class="step done">① {ss.raw_name}</span><span class="step done">② {len(tx_all)} rows parsed</span>'
    f'<span class="step {"done" if has_ai_cats else ""}">③ Categories: {ss.cat_source}</span>'
    f'<span class="step {"done" if ss.insights else ""}">④ Insights: {ss.ins_source or "not yet"}</span>',
    unsafe_allow_html=True,
)
if ss.dropped:
    st.caption(f"{ss.dropped} rows without a valid date or amount were skipped (e.g. opening balance lines).")
if len(tx_all) >= MAX_ROWS:
    st.warning(f"Only the first {MAX_ROWS:,} transactions are analysed.")

# ---------- step 3: Gemini categorisation ----------
if not demo_mode and not has_ai_cats:
    uniq = unique_descriptions(tx_all)
    with st.container(border=True):
        a, b = st.columns([3, 1])
        a.markdown(f"**③ Categorise with Gemini** — sends **{min(len(uniq), MAX_UNIQUE_DESCRIPTIONS)}** unique masked "
                   f"descriptions in **one** request" + (f" (of {len(uniq)}; the rest keep rule-based categories)"
                                                         if len(uniq) > MAX_UNIQUE_DESCRIPTIONS else "") + ".")
        with a.expander("🔍 See exactly what will be sent"):
            st.code(categorize_prompt(uniq)[:6000], language="json")
        if b.button("✨ Categorise", type="primary", width="stretch", disabled=not api_key):
            try:
                with st.spinner(f"Asking {model}…"):
                    by_key = categorize(make_client(api_key), model, uniq)
                ss.tx = an.apply_categories(tx_all, by_key)
                ss.cat_source = f"Gemini ({model})"
                ss.edit_rev += 1
                st.rerun()
            except AnalyzerError as e:
                st.error(str(e))
        if not api_key:
            b.caption("Add a Gemini key in the sidebar.")

# ---------- filters ----------
months = sorted(tx_all["month"].unique())
fa, fb = st.columns([2, 3])
sel_months = fa.pills("Months", months, selection_mode="multi", default=months,
                      format_func=lambda m: pd.Period(m).strftime("%b %Y"))
sel_cats = fb.multiselect("Categories", sorted(tx_all["category"].unique()), placeholder="All categories")
sel_months = sel_months or months
tx = tx_all[tx_all["month"].isin(sel_months)]
if sel_cats:
    tx = tx[tx["category"].isin(sel_cats)]
if tx.empty:
    st.warning("No transactions match the filters.")
    st.stop()

view = st.segmented_control("View", ["📊 Dashboard", "🧾 Transactions", "🎯 Budget planner", "🤖 AI insights",
                                     "📥 Report & export"], default="📊 Dashboard", label_visibility="collapsed")
view = view or "📊 Dashboard"
fmt = lambda x, d=0: money(x, SYM, d)  # noqa: E731
ins: InsightsResult | None = ss.insights


def kpi_row(k: dict) -> None:
    rate = k["savings_rate"]
    cards = [
        ("Income", fmt(k["income"]), EMERALD, f"{k['months']} month(s)"),
        ("Expenses", fmt(k["expenses"]), CORAL, f"≈ {fmt(k['avg_monthly_expense'])} / month"),
        ("Net savings", fmt(k["net"]), EMERALD if k["net"] >= 0 else CORAL,
         f"+ {fmt(k['moved_to_savings'])} moved to savings"),
        ("Savings rate", f"{rate:.1f}%", EMERALD if rate >= 20 else GOLD if rate >= 0 else CORAL,
         "20%+ is a common target"),
    ]
    for col, (label, value, color, sub) in zip(st.columns(4), cards):
        col.markdown(f'<div class="kpi" style="--c:{color}"><div class="l">{label}</div><div class="v">{value}</div>'
                     f'<div class="s">{sub}</div></div>', unsafe_allow_html=True)


def chart_layout(fig: go.Figure, h: int = 340) -> go.Figure:
    fig.update_layout(height=h, margin=dict(l=10, r=10, t=40, b=10), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", font=dict(family="DM Sans", color=INK),
                      legend=dict(orientation="h", y=-0.15))
    return fig


def donut(t: pd.DataFrame) -> go.Figure:
    cats = an.category_totals(t)
    fig = go.Figure(go.Pie(labels=cats["category"], values=cats["total"], hole=0.62, sort=False,
                           marker=dict(colors=[CATEGORY_COLORS.get(c, "#94A3B8") for c in cats["category"]],
                                       line=dict(color="white", width=2)),
                           hovertemplate="%{label}<br>" + SYM + "%{value:,.0f} (%{percent})<extra></extra>",
                           texttemplate=[f"{v:.0f}%" if v >= 4 else "" for v in cats["share"]],
                           textposition="inside", insidetextorientation="horizontal"))
    fig.add_annotation(text=f"<b>{fmt(cats['total'].sum())}</b><br><span style='font-size:11px'>spent</span>",
                       showarrow=False, font=dict(size=15, color=INK))
    chart_layout(fig, 380)
    fig.update_layout(title="Where the money went", legend=dict(orientation="v", x=1.02, y=0.5, font=dict(size=11)))
    return fig


def recurring_table(t: pd.DataFrame) -> pd.DataFrame:
    rec = an.recurring(t)
    notes = {n.merchant.lower(): n for n in (ins.recurring_payments if ins else [])}
    rec["subscription"] = [("✅" if notes[m.lower()].is_subscription else "") if m.lower() in notes
                           else ("✅" if c == "Subscriptions" else "") for m, c in zip(rec["merchant"], rec["category"])]
    rec["AI note"] = [notes[m.lower()].note if m.lower() in notes else "" for m in rec["merchant"]]
    return rec


def flagged(t: pd.DataFrame) -> None:
    unu = an.unusual(t)
    ai = {u.txn_id: u for u in (ins.unusual_transactions if ins else [])}
    if unu.empty:
        st.success("Nothing unusual found by the rules.")
    sev_col = {"high": CORAL, "medium": GOLD, "low": "#0EA5E9"}
    for r in unu.itertuples():
        a = ai.get(r.id)
        color = sev_col[a.severity] if a else "#94A3B8"
        st.markdown(f'<div class="flag" style="--c:{color}"><b>{fmt(-r.amount)}</b> · {r.merchant} · '
                    f'{r.date:%d %b %Y} <span class="muted">({a.severity if a else "rule"})</span><br>'
                    f'<span class="muted">{(a.reason if a else r.rule)}</span></div>', unsafe_allow_html=True)


# ---------- views ----------
if view == "📊 Dashboard":
    k = an.kpis(tx)
    kpi_row(k)
    st.write("")
    left, right = st.columns([1, 1], gap="large")
    left.plotly_chart(donut(tx), width="stretch")
    mon = an.monthly(tx)
    mon["label"] = [pd.Period(m).strftime("%b %Y") for m in mon["month"]]
    fig = go.Figure([
        go.Bar(name="Income", x=mon["label"], y=mon["income"], marker_color=EMERALD),
        go.Bar(name="Expenses", x=mon["label"], y=mon["expenses"], marker_color=CORAL),
        go.Scatter(name="Net", x=mon["label"], y=mon["net"], mode="lines+markers", line=dict(color=GOLD, width=3)),
    ])
    fig.update_layout(title="Monthly trend", barmode="group", yaxis_tickprefix=SYM)
    right.plotly_chart(chart_layout(fig, 380), width="stretch")

    left, right = st.columns([1, 1], gap="large")
    mer = an.top_merchants(tx, 10).iloc[::-1]
    fig = go.Figure(go.Bar(x=mer["total"], y=mer["merchant"], orientation="h", marker_color="#0D9488",
                           text=[fmt(v) for v in mer["total"]], textposition="outside",
                           hovertemplate="%{y}: " + SYM + "%{x:,.0f}<extra></extra>"))
    fig.update_traces(cliponaxis=False)
    fig.update_layout(title="Top merchants", xaxis_tickprefix=SYM, xaxis_range=[0, mer["total"].max() * 1.25])
    left.plotly_chart(chart_layout(fig, 400), width="stretch")
    with right:
        st.markdown("##### ⚠️ Flagged unusual transactions")
        flagged(tx)
    st.markdown("##### 🔁 Recurring payments & subscriptions")
    rec = recurring_table(tx)
    if rec.empty:
        st.info("No recurring payments detected (needs at least two months of data).")
    else:
        st.dataframe(rec, hide_index=True, width="stretch", column_config={
            "typical_amount": st.column_config.NumberColumn("Typical", format=f"{SYM}%,.0f"),
            "merchant": "Merchant", "category": "Category", "frequency": "How often", "payments": "Payments",
            "last_paid": "Last paid", "subscription": "Subscription"})
        st.caption(f"Recurring outflow ≈ {fmt(rec['typical_amount'].sum())} per cycle.")

elif view == "🧾 Transactions":
    st.markdown("#### Fix categories — the charts recompute instantly")
    same_merchant = st.toggle("Apply a category change to every transaction from the same merchant", value=True)
    show = tx[["id", "date", "description", "merchant", "category", "amount"]].reset_index(drop=True)
    edited = st.data_editor(
        show, hide_index=True, width="stretch", height=430, disabled=["id", "date", "description", "amount"],
        key=f"editor_{ss.edit_rev}_{'-'.join(sel_months)}_{'-'.join(sel_cats)}",
        column_config={
            "id": st.column_config.NumberColumn("#", width="small"),
            "date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
            "description": st.column_config.TextColumn("Description (local only)", width="medium"),
            "merchant": st.column_config.TextColumn("Merchant"),
            "category": st.column_config.SelectboxColumn("Category", options=CATEGORIES, required=True),
            "amount": st.column_config.NumberColumn("Amount", format=f"{SYM}%,.2f"),
        })
    changed = edited[(edited["category"] != show["category"]) | (edited["merchant"] != show["merchant"])]
    if len(changed):
        full = ss.tx.set_index("id")
        for r in changed.itertuples():
            old = full.loc[r.id]
            if same_merchant and r.category != old["category"]:
                full.loc[full["merchant"] == old["merchant"], "category"] = r.category
            full.loc[r.id, ["category", "merchant"]] = [r.category, r.merchant]
        ss.tx = full.reset_index()
        tx = ss.tx[ss.tx["id"].isin(tx["id"])]
        if same_merchant:
            ss.edit_rev += 1  # redraw the editor so the other rows of that merchant show the new category
            st.rerun()
        st.toast(f"Updated {len(changed)} row(s)")
    k = an.kpis(tx)
    kpi_row(k)
    cats = an.category_totals(tx)
    fig = px.bar(cats, x="category", y="total", color="category", color_discrete_map=CATEGORY_COLORS,
                 title="Spending by category (live)", text=[fmt(v) for v in cats["total"]])
    fig.update_layout(showlegend=False, yaxis_tickprefix=SYM, xaxis_title=None, yaxis_title=None)
    st.plotly_chart(chart_layout(fig, 330), width="stretch")

elif view == "🎯 Budget planner":
    st.markdown("#### Set a monthly budget per category")
    cats = an.category_totals(tx).set_index("category")
    suggest = {b.category: b.suggested_monthly_budget for b in (ins.budget_suggestions if ins else [])}
    budget_cats = sorted([c for c in EXPENSE_CATS if c in cats.index or c in suggest],
                         key=lambda c: -float(cats["monthly_avg"].get(c, 0.0)))
    st.caption(f"Compared with your average monthly spending over {tx['month'].nunique()} selected month(s). "
               + ("Defaults come from the AI suggestions." if suggest else "Defaults are your average, rounded."))
    if st.button("↺ Reset to suggestions"):
        for c in budget_cats:
            ss.pop(f"bud_{c}", None)
    budgets = {}
    for c in budget_cats:
        avg = float(cats["monthly_avg"].get(c, 0.0))
        default = suggest.get(c, round(avg / 100) * 100)
        ss.setdefault(f"bud_{c}", float(default))
        a, b, d = st.columns([2, 1.2, 3])
        a.markdown(f"<div style='padding-top:.45rem'><span style='color:{CATEGORY_COLORS.get(c)}'>●</span> "
                   f"<b>{c}</b><br><span class='muted'>avg {fmt(avg)} / month</span></div>", unsafe_allow_html=True)
        budgets[c] = b.number_input("Budget", key=f"bud_{c}", min_value=0.0, step=500.0, label_visibility="collapsed")
        used = avg / budgets[c] * 100 if budgets[c] else 0
        diff = budgets[c] - avg
        status = f"✅ {fmt(diff)} left" if diff >= 0 else f"🔴 {fmt(-diff)} over"
        d.progress(min(used, 100) / 100, text=f"{used:.0f}% used · {status}")
    ss.budgets = budgets
    bs = an.budget_status(tx, budgets)
    tot_b, tot_s = bs["budget"].sum(), bs["avg_monthly_spend"].sum()
    a, b, c = st.columns(3)
    a.metric("Total monthly budget", fmt(tot_b))
    b.metric("Average monthly spend", fmt(tot_s))
    c.metric("Over budget in", f"{int((bs['difference'] < 0).sum())} categories",
             delta=fmt(tot_b - tot_s), delta_color="normal")
    fig = go.Figure([go.Bar(name="Budget", x=bs["category"], y=bs["budget"], marker_color="#A7F3D0"),
                     go.Bar(name="Avg spend", x=bs["category"], y=bs["avg_monthly_spend"],
                            marker_color=[CORAL if d < 0 else EMERALD for d in bs["difference"]])])
    fig.update_layout(title="Budget vs average monthly spend", barmode="group", yaxis_tickprefix=SYM)
    st.plotly_chart(chart_layout(fig, 360), width="stretch")

elif view == "🤖 AI insights":
    st.warning(f"⚖️ {DISCLAIMER}")
    if not demo_mode:
        payload = an.insights_payload(tx)
        a, b = st.columns([3, 1])
        a.markdown("Sends **only aggregated totals** (categories, months, top merchants, candidate recurring and "
                   "unusual items) in **one** request. Uses your current filters and category fixes.")
        with a.expander("🔍 See exactly what will be sent"):
            st.json(payload, expanded=False)
        if b.button("✨ Generate insights", type="primary", width="stretch", disabled=not api_key):
            try:
                with st.spinner(f"Asking {model}…"):
                    ss.insights = insights(make_client(api_key), model, payload, CODE)
                ss.ins_source = f"Gemini ({model})"
                for c in [c for c in ss if str(c).startswith("bud_")]:
                    del ss[c]
                st.rerun()
            except AnalyzerError as e:
                st.error(str(e))
    if ins:
        st.caption(f"Source: {ss.ins_source}")
        a, b = st.columns([1, 3], gap="large")
        g = go.Figure(go.Indicator(mode="gauge+number", value=ins.health_score, title={"text": "Budget health"},
                                   gauge={"axis": {"range": [0, 100]}, "bar": {"color": EMERALD},
                                          "steps": [{"range": [0, 45], "color": "#FEE2E2"},
                                                    {"range": [45, 70], "color": "#FEF3C7"},
                                                    {"range": [70, 100], "color": "#D1FAE5"}]}))
        a.plotly_chart(chart_layout(g, 240), width="stretch")
        b.markdown(f"#### Summary\n{ins.summary}")
        st.markdown("#### Spending patterns")
        cols = st.columns(2)
        for i, p in enumerate(ins.spending_patterns):
            cols[i % 2].markdown(f'<div class="pattern"><b>{p.title}</b><br>{p.detail}</div>', unsafe_allow_html=True)
        a, b = st.columns(2, gap="large")
        with a:
            st.markdown("#### 💡 Saving tips")
            st.markdown("\n".join(f"{i}. {t}" for i, t in enumerate(ins.saving_tips, 1)))
        with b:
            st.markdown("#### 🎯 Suggested monthly budgets")
            st.dataframe(pd.DataFrame([b.model_dump() for b in ins.budget_suggestions]), hide_index=True,
                         width="stretch", column_config={
                             "category": "Category", "rationale": "Why",
                             "suggested_monthly_budget": st.column_config.NumberColumn("Budget", format=f"{SYM}%,.0f")})
        st.markdown("#### 🔁 Recurring payments (AI view)")
        st.dataframe(pd.DataFrame([r.model_dump() for r in ins.recurring_payments]), hide_index=True, width="stretch")
    elif demo_mode is False:
        st.info("Click **Generate insights** to get patterns, recurring payments, unusual items and saving tips.")

else:  # Report & export
    st.markdown("#### Download your report")
    st.caption("The report uses the current filters, your category fixes and the budgets from the Budget planner "
               "(or the AI suggestions).")
    budgets = ss.budgets or None
    note = f"Categories: {ss.cat_source}. Insights: {ss.ins_source or 'not generated'}."
    pdf = build_pdf(tx, CODE, ins, budgets, source_note=note)
    out_csv = tx[["date", "masked", "description", "merchant", "category", "amount"]].copy()
    out_csv["date"] = out_csv["date"].dt.strftime("%Y-%m-%d")
    masked_only = st.toggle("Use masked descriptions in the CSV/JSON", value=True)
    if masked_only:
        out_csv = out_csv.drop(columns="description").rename(columns={"masked": "description"})
    else:
        out_csv = out_csv.drop(columns="masked")
    k = an.kpis(tx)
    export = {
        "kpis": k, "currency": CODE, "categories_source": ss.cat_source, "insights_source": ss.ins_source,
        "category_totals": an.category_totals(tx).round(2).to_dict("records"),
        "monthly": an.monthly(tx).round(2).to_dict("records"),
        "recurring": an.recurring(tx).round(2).to_dict("records"),
        "budgets": ss.budgets, "insights": ins.model_dump() if ins else None,
        "transactions": out_csv.to_dict("records"),
    }
    a, b, c = st.columns(3)
    a.download_button("📄 PDF report", pdf, "expense_report.pdf", "application/pdf", type="primary", width="stretch")
    b.download_button("🧾 Categorised CSV", out_csv.to_csv(index=False).encode("utf-8-sig"), "transactions_categorised.csv",
                      "text/csv", width="stretch")
    c.download_button("🗂️ Analysis JSON", json.dumps(export, indent=1, default=str, ensure_ascii=False),
                      "expense_analysis.json", "application/json", width="stretch")
    st.markdown("**The PDF contains:** summary & KPIs · spending patterns · category donut and table · monthly trend "
                "chart · top merchants · recurring payments · unusual transactions · budget plan with progress bars · "
                "saving tips · largest payments (masked) · disclaimer.")
    st.dataframe(out_csv.head(20), hide_index=True, width="stretch")
