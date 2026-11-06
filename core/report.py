"""Multi-page PDF report built with ReportLab (charts are drawn with reportlab.graphics, no images)."""

from __future__ import annotations

import io
from datetime import date
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from . import analytics as an
from . import theme
from .common import DISCLAIMER
from .schema import InsightsResult

INK = colors.HexColor(theme.INK)
EMERALD = colors.HexColor(theme.EMERALD)
MINT = colors.HexColor(theme.MINT)
GOLD = colors.HexColor(theme.GOLD)
CORAL = colors.HexColor(theme.CORAL)
MUTED = colors.HexColor(theme.MUTED)
LIGHT = colors.HexColor("#F0FDF4")
GRID = colors.HexColor("#D1D5DB")


def _cat_color(cat: str) -> colors.Color:
    return colors.HexColor(theme.CATEGORY_COLORS.get(cat, "#94A3B8"))


def _styles():
    ss = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=ss["Title"], textColor=INK, fontSize=22, spaceAfter=2, alignment=0),
        "subtitle": ParagraphStyle("st", parent=ss["Normal"], textColor=MUTED, fontSize=10, spaceAfter=6),
        "h2": ParagraphStyle("h2", parent=ss["Heading2"], textColor=EMERALD, spaceBefore=10, spaceAfter=5,
                             keepWithNext=1),
        "h3": ParagraphStyle("h3", parent=ss["Heading3"], textColor=INK, spaceBefore=4, spaceAfter=2, keepWithNext=1),
        "body": ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=13),
        "small": ParagraphStyle("s", parent=ss["BodyText"], fontSize=8, leading=10.5, textColor=MUTED),
        "cell": ParagraphStyle("c", parent=ss["BodyText"], fontSize=8.5, leading=10.5),
        "big": ParagraphStyle("big", parent=ss["Normal"], fontSize=13.5, leading=17, alignment=TA_CENTER),
        "num": ParagraphStyle("n", parent=ss["BodyText"], fontSize=8.5, leading=10.5, alignment=TA_RIGHT),
        "label": ParagraphStyle("lbl", parent=ss["Normal"], fontSize=8, textColor=MUTED, alignment=TA_CENTER),
    }


def _p(text: str, style) -> Paragraph:
    return Paragraph(escape(str(text)), style)


def _bullets(items: list[str], style) -> ListFlowable:
    return ListFlowable([ListItem(_p(i, style), leftIndent=10) for i in items],
                        bulletType="bullet", start="•", leftIndent=12, bulletFontSize=8)


def _table(rows: list[list], widths: list[float], align_right: tuple[int, ...] = ()) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    style += [("ALIGN", (c, 0), (c, -1), "RIGHT") for c in align_right]
    t.setStyle(TableStyle(style))
    return t


class _Fmt:
    def __init__(self, code: str):
        self.code = code

    def __call__(self, x: float, decimals: int = 0) -> str:
        return theme.money(x, self.code, decimals)


def _kpi_cards(k: dict, fmt: _Fmt, st, health: int | None) -> Table:
    def card(value: str, label: str, color) -> list:
        return [Paragraph(f'<font color="{color.hexval()}"><b>{escape(value)}</b></font>', st["big"]),
                _p(label, st["label"])]

    rate = k["savings_rate"]
    cells = [card(fmt(k["income"]), "Income", EMERALD), card(fmt(k["expenses"]), "Expenses", CORAL),
             card(fmt(k["net"]), "Net savings", EMERALD if k["net"] >= 0 else CORAL),
             card(f"{rate:.1f}%", "Savings rate", EMERALD if rate >= 20 else GOLD if rate >= 0 else CORAL)]
    if health is not None:
        cells.append(card(f"{health}/100", "Budget health", EMERALD if health >= 70 else GOLD if health >= 45 else CORAL))
    n = len(cells)
    t = Table([cells], colWidths=[174 * mm / n] * n)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, EMERALD), ("INNERGRID", (0, 0), (-1, -1), 0.6, colors.white),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _donut(cats: pd.DataFrame, fmt: _Fmt) -> Drawing:
    d = Drawing(174 * mm, 72 * mm)
    top = cats.head(8)
    rest = cats.iloc[8:]["total"].sum()
    labels = list(top["category"]) + (["All other"] if rest > 0 else [])
    values = list(top["total"]) + ([rest] if rest > 0 else [])
    pie = Pie()
    pie.x, pie.y, pie.width, pie.height = 8 * mm, 4 * mm, 62 * mm, 62 * mm
    pie.data = [float(v) for v in values] or [1]
    pie.labels = None
    pie.innerRadiusFraction = 0.55
    pie.slices.strokeColor = colors.white
    pie.slices.strokeWidth = 1.2
    for i, lab in enumerate(labels):
        pie.slices[i].fillColor = _cat_color(lab)
    d.add(pie)
    total = sum(values)
    d.add(String(39 * mm, 37 * mm, fmt(total), fontSize=10, fontName="Helvetica-Bold", fillColor=INK,
                 textAnchor="middle"))
    d.add(String(39 * mm, 32 * mm, "total spent", fontSize=7.5, fillColor=MUTED, textAnchor="middle"))
    lg = Legend()
    lg.x, lg.y = 80 * mm, 64 * mm
    lg.alignment = "right"
    lg.fontSize = 8
    lg.dy = lg.dx = 7
    lg.deltay = 11
    lg.columnMaximum = 10
    lg.colorNamePairs = [(_cat_color(lab), f"{lab}  {fmt(v)}  ({v / total * 100:.0f}%)")
                         for lab, v in zip(labels, values)] if total else []
    d.add(lg)
    return d


def _monthly_chart(mon: pd.DataFrame, fmt: _Fmt) -> Drawing:
    d = Drawing(174 * mm, 62 * mm)
    c = VerticalBarChart()
    c.x, c.y, c.width, c.height = 18 * mm, 10 * mm, 120 * mm, 46 * mm
    c.data = [list(mon["income"]), list(mon["expenses"])]
    c.categoryAxis.categoryNames = [pd.Period(m).strftime("%b %Y") for m in mon["month"]]
    c.categoryAxis.labels.fontSize = 8
    c.valueAxis.valueMin = 0
    c.valueAxis.labels.fontSize = 7
    c.valueAxis.labelTextFormat = lambda v: f"{v / 1000:,.0f}k"
    c.valueAxis.visibleGrid = True
    c.valueAxis.gridStrokeColor = GRID
    c.bars[0].fillColor = EMERALD
    c.bars[1].fillColor = CORAL
    c.bars.strokeColor = None
    c.groupSpacing = 8
    c.barSpacing = 2
    d.add(c)
    for i, (label, col) in enumerate([("Income", EMERALD), ("Expenses", CORAL)]):
        d.add(Rect(145 * mm, (50 - i * 7) * mm, 4 * mm, 4 * mm, fillColor=col, strokeColor=None))
        d.add(String(151 * mm, (50.8 - i * 7) * mm, label, fontSize=8.5, fillColor=INK))
    return d


def _merchant_chart(mer: pd.DataFrame, fmt: _Fmt) -> Drawing:
    mer = mer.iloc[::-1]  # biggest on top
    h = max(30, 7 * len(mer) + 10)
    d = Drawing(174 * mm, h * mm)
    c = HorizontalBarChart()
    c.x, c.y, c.width, c.height = 48 * mm, 4 * mm, 112 * mm, (h - 8) * mm
    c.data = [list(mer["total"])]
    c.categoryAxis.categoryNames = [m[:26] for m in mer["merchant"]]
    c.categoryAxis.labels.fontSize = 8
    c.categoryAxis.labels.dx = -3
    c.valueAxis.valueMin = 0
    c.valueAxis.labels.fontSize = 7
    c.valueAxis.labelTextFormat = lambda v: f"{v / 1000:,.0f}k"
    c.valueAxis.visibleGrid = True
    c.valueAxis.gridStrokeColor = GRID
    c.bars[0].fillColor = colors.HexColor("#0D9488")
    c.bars.strokeColor = None
    c.barLabelFormat = lambda v: fmt(v)
    c.barLabels.fontSize = 7
    c.barLabels.boxAnchor = "w"
    c.barLabels.dx = 3
    d.add(c)
    return d


def _progress(pct: float, width: float = 34 * mm) -> Drawing:
    d = Drawing(width, 4 * mm)
    d.add(Rect(0, 1, width, 3 * mm, fillColor=colors.HexColor("#E5E7EB"), strokeColor=None, rx=3, ry=3))
    col = EMERALD if pct <= 85 else GOLD if pct <= 100 else CORAL
    d.add(Rect(0, 1, width * min(pct, 100) / 100, 3 * mm, fillColor=col, strokeColor=None, rx=3, ry=3))
    return d


def _make_page_decor(title: str):
    def decor(canvas, doc):
        canvas.saveState()
        w, h = A4
        canvas.setFillColor(INK)
        canvas.rect(0, h - 11 * mm, w, 11 * mm, stroke=0, fill=1)
        canvas.setFillColor(EMERALD)
        canvas.rect(0, h - 12.2 * mm, w, 1.2 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(18 * mm, h - 7.3 * mm, "PERSONAL EXPENSE ANALYZER")
        canvas.setFont("Helvetica", 8.5)
        canvas.drawRightString(w - 18 * mm, h - 7.3 * mm, title)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 9 * mm, "Budgeting guidance only, not financial or investment advice. "
                                           "AI text may contain mistakes; numbers are computed locally.")
        canvas.drawRightString(w - 18 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()
    return decor


def build_pdf(tx: pd.DataFrame, currency_code: str, insights: InsightsResult | None,
              budgets: dict[str, float] | None = None, source_note: str = "") -> bytes:
    st = _styles()
    fmt = _Fmt(currency_code)
    k = an.kpis(tx)
    cats = an.category_totals(tx)
    mon = an.monthly(tx)
    mer = an.top_merchants(tx, 10)
    rec = an.recurring(tx)
    unu = an.unusual(tx)
    budgets = budgets or {}
    if not budgets and insights:
        budgets = {b.category: b.suggested_monthly_budget for b in insights.budget_suggestions}

    buf = io.BytesIO()
    period = f"{k['start']} – {k['end']}"
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=20 * mm,
                            bottomMargin=16 * mm, title="Personal Expense Report", author="Personal Expense Analyzer")
    W = doc.width
    hdr = lambda t: Paragraph(f"<b>{escape(t)}</b>", ParagraphStyle("hc", parent=st["cell"], textColor=colors.white))
    cell = lambda t: _p(t, st["cell"])
    num = lambda t: _p(t, st["num"])

    # ---- page 1: summary ----
    s = [
        _p("Personal Expense Report", st["title"]),
        _p(f"Statement period {period}  •  {k['transactions']} transactions  •  {k['months']} month(s)  •  "
           f"currency {currency_code}  •  generated {date.today():%d %B %Y}", st["subtitle"]),
        _kpi_cards(k, fmt, st, insights.health_score if insights else None),
        Spacer(1, 4),
        _p(f"Average monthly spending: {fmt(k['avg_monthly_expense'])}.  Moved to savings/DPS: "
           f"{fmt(k['moved_to_savings'])} (not counted as an expense).", st["small"]),
        _p("Summary", st["h2"]),
        _p(insights.summary if insights else "AI insights were not generated for this report. All figures below are "
           "computed locally from the statement.", st["body"]),
    ]
    if source_note:
        s.append(_p(source_note, st["small"]))
    if insights and insights.spending_patterns:
        s += [_p("Spending patterns", st["h2"])]
        s += [KeepTogether([_p(pt.title, st["h3"]), _p(pt.detail, st["body"])]) for pt in insights.spending_patterns]
    box = Table([[Paragraph(f"<b>Disclaimer.</b> {escape(DISCLAIMER)} Personal identifiers (card, account and phone "
                            "numbers) were masked before any text was sent to the AI model.", st["cell"])]],
                colWidths=[W])
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF3C7")),
                             ("BOX", (0, 0), (-1, -1), 0.6, GOLD), ("LEFTPADDING", (0, 0), (-1, -1), 6),
                             ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    s += [Spacer(1, 8), box, PageBreak()]

    # ---- page 2: where the money went ----
    s += [_p("1. Where the money went", st["h2"]), _donut(cats, fmt),
          _table([[hdr("Category"), hdr("Total"), hdr("Per month"), hdr("Share"), hdr("Txns")]] +
                 [[cell(r.category), num(fmt(r.total)), num(fmt(r.monthly_avg)), num(f"{r.share:.1f}%"),
                   num(str(r.count))] for r in cats.itertuples()],
                 [62 * mm, 32 * mm, 32 * mm, 24 * mm, W - 150 * mm], align_right=(1, 2, 3, 4)),
          PageBreak()]

    # ---- page 3: trends and merchants ----
    s += [_p("2. Monthly trend", st["h2"]), _monthly_chart(mon, fmt),
          _table([[hdr("Month"), hdr("Income"), hdr("Expenses"), hdr("Net"), hdr("Savings rate")]] +
                 [[cell(pd.Period(r.month).strftime("%B %Y")), num(fmt(r.income)), num(fmt(r.expenses)),
                   num(fmt(r.net)), num(f"{(r.net / r.income * 100) if r.income else 0:.1f}%")]
                  for r in mon.itertuples()],
                 [44 * mm, 34 * mm, 34 * mm, 34 * mm, W - 146 * mm], align_right=(1, 2, 3, 4)),
          _p("3. Top merchants by spending", st["h2"]), _merchant_chart(mer, fmt), PageBreak()]

    # ---- page 4: recurring and unusual ----
    notes = {n.merchant.lower(): n for n in (insights.recurring_payments if insights else [])}
    s += [_p("4. Recurring payments and subscriptions", st["h2"])]
    if len(rec):
        s.append(_table([[hdr("Merchant"), hdr("Category"), hdr("Typical"), hdr("How often"), hdr("Note")]] +
                        [[cell(r.merchant), cell(r.category), num(fmt(r.typical_amount)), cell(r.frequency),
                          cell(notes[r.merchant.lower()].note if r.merchant.lower() in notes else "")]
                         for r in rec.itertuples()],
                        [36 * mm, 30 * mm, 24 * mm, 20 * mm, W - 110 * mm], align_right=(2,)))
        s.append(_p(f"Recurring total: about {fmt(rec['typical_amount'].sum())} per cycle.", st["small"]))
    else:
        s.append(_p("No recurring payments detected (needs at least two months of data).", st["body"]))
    s += [_p("5. Unusual transactions to check", st["h2"])]
    ai_unu = {u.txn_id: u for u in (insights.unusual_transactions if insights else [])}
    if len(unu):
        s.append(_table([[hdr("Date"), hdr("Merchant"), hdr("Amount"), hdr("Why flagged"), hdr("Level")]] +
                        [[cell(r.date.strftime("%d %b %Y")), cell(r.merchant), num(fmt(-r.amount)),
                          cell(ai_unu[r.id].reason if r.id in ai_unu else r.rule),
                          cell(ai_unu[r.id].severity if r.id in ai_unu else "rule")]
                         for r in unu.itertuples()],
                        [22 * mm, 36 * mm, 24 * mm, W - 98 * mm, 16 * mm], align_right=(2,)))
    else:
        s.append(_p("Nothing unusual was found by the rules.", st["body"]))
    s.append(PageBreak())

    # ---- page 5: budget plan and tips ----
    s += [_p("6. Monthly budget plan", st["h2"])]
    if budgets:
        bs = an.budget_status(tx, budgets).sort_values("budget", ascending=False)
        s.append(_table([[hdr("Category"), hdr("Budget"), hdr("Avg spend"), hdr("Left / over"), hdr("Used")]] +
                        [[cell(r.category), num(fmt(r.budget)), num(fmt(r.avg_monthly_spend)),
                          Paragraph(f'<font color="{(EMERALD if r.difference >= 0 else CORAL).hexval()}">'
                                    f"{escape(fmt(r.difference))}</font>", st["num"]),
                          Table([[_progress(r.used_pct), cell(f"{r.used_pct:.0f}%")]], colWidths=[36 * mm, 12 * mm],
                                style=[("LEFTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")])]
                         for r in bs.itertuples()],
                        [40 * mm, 24 * mm, 24 * mm, 24 * mm, W - 112 * mm], align_right=(1, 2, 3)))
        s.append(_p(f"Total budget {fmt(sum(budgets.values()))} per month vs average spending "
                    f"{fmt(k['avg_monthly_expense'])}.", st["small"]))
    else:
        s.append(_p("No budgets set.", st["body"]))
    if insights and insights.saving_tips:
        s += [_p("7. Saving tips", st["h2"]), _bullets(insights.saving_tips, st["body"])]
    s.append(PageBreak())

    # ---- appendix ----
    big = tx[tx["amount"] < 0].nsmallest(30, "amount")
    s += [_p("Appendix: 30 largest payments (descriptions masked)", st["h2"]),
          _table([[hdr("Date"), hdr("Description"), hdr("Category"), hdr("Amount")]] +
                 [[cell(r.date.strftime("%d %b %Y")), cell(r.masked[:70]), cell(r.category), num(fmt(-r.amount))]
                  for r in big.itertuples()],
                 [22 * mm, W - 98 * mm, 44 * mm, 32 * mm], align_right=(3,))]

    decor = _make_page_decor(period)
    doc.build(s, onFirstPage=decor, onLaterPages=decor)
    return buf.getvalue()
