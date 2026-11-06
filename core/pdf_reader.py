"""Turn a bank-statement PDF (text-based or scanned) into Date / Description / Amount rows.

1. Text comes from the PDF's text layer; pages without one (scanned / image-only) are read with
   local OCR (Tesseract via pytesseract). Nothing is sent to any server.
2. Transaction lines are lines that START with a date and END with money amounts.
3. If most lines also carry a running balance, the signed amount is taken from the balance change
   (this also repairs OCR slips such as ".26" read as "26") and only those balance lines are used,
   so a second "by type" listing of the same transactions is not counted twice.
4. Otherwise the sign comes from "-", "( )", Dr/Cr, the section heading (Deposits / Withdrawals) or keywords.
"""

from __future__ import annotations

import re
from datetime import date

import pandas as pd

from .common import AnalyzerError

MAX_PDF_PAGES = 30
OCR_DPI = 300

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE_NUM = re.compile(r"^(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2}|\d{4}))?(?=\s)")
_DATE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?=\s)")
_DATE_DMY_NAME = re.compile(r"^(\d{1,2})[ -]([A-Za-z]{3})[a-z]*\.?[ -,]*(\d{4}|\d{2})?(?=\s)")
_DATE_MDY_NAME = re.compile(r"^([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s*(\d{4})?(?=\s)")
# Money: 1,234.56 / 1234.56 / .26 / $9.98 / (12.00) / -12.00, optionally followed by Dr or Cr.
_MONEY = re.compile(r"^\(?[-+]?[$৳€£₹]?\s?(?:\d{1,3}(?:,\d{3})+|\d+)?\.\d{2}\)?(?:\s?(?:dr|cr)\.?)?$", re.I)
_OPENING = re.compile(r"(?i)(?:beginning|opening|previous|brought\s+forward)\s+balance.*?\(?-?[$৳€£₹]?\s?(\d[\d,]*\.\d{2})")
_CREDIT_WORDS = ("credit", "deposit", "salary", "payroll", "interest", "refund", "received", "cash in", "transfer in",
                 "reversal", "remittance")
_IN_HEADINGS = ("deposits", "credits", "money in", "paid in", "receipts")
_OUT_HEADINGS = ("withdrawals", "debits", "money out", "paid out", "charges", "fees", "payments", "checks paid",
                 "purchases")


def pdf_to_frame(data: bytes, today: date | None = None) -> tuple[pd.DataFrame, bool]:
    """Return (rows with Date (ISO), Description, Amount (signed), whether OCR was used)."""
    lines, used_ocr = _pdf_lines(data)
    rows = parse_statement_lines(lines, today or date.today())
    if not rows:
        hint = ("The pages were read with OCR, but no line starts with a date and ends with an amount."
                if used_ocr else "No line starts with a date and ends with an amount.")
        raise AnalyzerError(f"No transaction lines found in this PDF. {hint} Try a CSV/Excel export instead.")
    return pd.DataFrame(rows, columns=["Date", "Description", "Amount"]), used_ocr


# ---------- text extraction ----------
def _pdf_lines(data: bytes) -> tuple[list[str], bool]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover
        raise AnalyzerError("PDF support needs pypdfium2 (pip install pypdfium2).") from exc
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as exc:
        raise AnalyzerError("This PDF could not be opened (damaged or password-protected).") from exc
    if len(pdf) > MAX_PDF_PAGES:
        raise AnalyzerError(f"This PDF has {len(pdf)} pages; the limit is {MAX_PDF_PAGES}.")
    lines, used_ocr = [], False
    for i in range(len(pdf)):
        text = pdf[i].get_textpage().get_text_range()
        if len(text.strip()) < 20:  # no text layer: a scanned / image-only page
            text = _ocr_page(pdf[i])
            used_ocr = True
        lines += [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    return [ln for ln in lines if ln], used_ocr


def _ocr_page(page) -> str:
    try:
        import pytesseract
    except ImportError as exc:
        raise AnalyzerError("This PDF is scanned (image only). Reading it needs OCR: "
                            "pip install pytesseract and install Tesseract (brew install tesseract).") from exc
    image = page.render(scale=OCR_DPI / 72).to_pil().convert("L")
    try:
        return pytesseract.image_to_string(image, config="--psm 6")
    except pytesseract.TesseractNotFoundError as exc:
        raise AnalyzerError("This PDF is scanned (image only) and the Tesseract OCR program is not installed. "
                            "Install it (macOS: brew install tesseract; Ubuntu: apt install tesseract-ocr) "
                            "or upload a CSV/Excel export instead.") from exc


# ---------- line parsing ----------
def _money(tok: str) -> float | None:
    if not _MONEY.match(tok):
        return None
    neg = tok.startswith("(") or tok.startswith("-") or re.search(r"dr\.?$", tok, re.I) is not None
    val = float(re.sub(r"[^\d.]", "", re.sub(r"(?i)(dr|cr)\.?$", "", tok)))
    return -val if neg else val


def _split_date(line: str):
    """(kind, parts, rest) for a line that starts with a date, else None."""
    if m := _DATE_ISO.match(line):
        return "iso", (int(m[1]), int(m[2]), int(m[3])), line[m.end():]
    if m := _DATE_NUM.match(line):
        return "num", (int(m[1]), int(m[2]), m[3]), line[m.end():]
    if (m := _DATE_DMY_NAME.match(line)) and m[2].lower()[:3] in _MONTHS:
        return "name", (int(m[1]), _MONTHS[m[2].lower()[:3]], m[3]), line[m.end():]
    if (m := _DATE_MDY_NAME.match(line)) and m[1].lower()[:3] in _MONTHS:
        return "name", (int(m[2]), _MONTHS[m[1].lower()[:3]], m[3]), line[m.end():]
    return None


def _explicit(tok: str) -> bool:
    """The token itself says in or out: (12.00), -12.00, 12.00 Dr, 12.00 Cr."""
    return tok.startswith(("(", "-")) or re.search(r"(?i)(dr|cr)\.?$", tok) is not None


def _trailing_money(rest: str) -> tuple[str, list[float], bool]:
    toks = rest.split()
    # join "1,234.56 Dr" -> one token
    joined: list[str] = []
    for t in toks:
        if joined and re.fullmatch(r"(?i)(dr|cr)\.?", t) and _money(joined[-1]) is not None:
            joined[-1] += " " + t
        else:
            joined.append(t)
    vals: list[float] = []
    explicit = False
    while joined and (v := _money(joined[-1])) is not None and len(vals) < 3:
        explicit = explicit or (len(vals) == 0 and _explicit(joined[-1]))
        vals.insert(0, v)
        joined.pop()
    return " ".join(joined).strip(" -_—|"), vals, explicit


def _year(y: str | None) -> int | None:
    if not y:
        return None
    y = int(y)
    return y + 2000 if y < 100 else y


def parse_statement_lines(lines: list[str], today: date) -> list[tuple[str, str, float]]:
    cands = []  # (line index, date kind, date parts, description, money values, heading sign)
    heading = 0
    for idx, line in enumerate(lines):
        low = line.lower()
        hit = _split_date(line)
        if hit is None:
            if len(low) < 60 and not re.search(r"\d+\.\d{2}", low):
                if any(h in low for h in _IN_HEADINGS):
                    heading = 1
                elif any(h in low for h in _OUT_HEADINGS):
                    heading = -1
            continue
        kind, parts, rest = hit
        desc, vals, explicit = _trailing_money(rest)
        if vals and desc:
            cands.append([idx, kind, parts, desc, vals, heading, explicit])
    if not cands:
        return []

    dates = _resolve_dates(cands, today)
    if dates is None:
        return []

    balance_mode = sum(len(c[4]) >= 2 for c in cands) >= 0.5 * len(cands)
    rows: list[tuple[str, str, float]] = []
    if balance_mode:
        bal_idx = {c[0] for c in cands if len(c[4]) >= 2}
        m = next((m for ln in lines if (m := _OPENING.search(ln))), None)
        prev = float(m[1].replace(",", "")) if m else None
        for c, d in zip(cands, dates):
            idx, _, _, desc, vals, head, _ = c
            if len(vals) < 2 and not ({idx - 1, idx + 1} & bal_idx):
                continue  # a single-amount line outside the balance table (e.g. a "by type" re-listing)
            balance = vals[-1]
            listed = abs(vals[-2]) if len(vals) >= 2 else None
            if len(vals) == 1:  # the amount was lost or merged into the text by OCR; drop a stray small number
                desc = re.sub(r"\s\d{1,3}$", "", desc)
            if prev is not None:
                delta = round(balance - prev, 2)
                amount = delta if (listed is None or _same_digits(listed, abs(delta))) else _signed(listed, desc, head)
            elif listed is not None:
                amount = _signed(listed, desc, head)
            else:
                prev = balance
                continue
            prev = balance
            if amount:
                rows.append((d, desc, amount))
    else:
        for c, d in zip(cands, dates):
            _, _, _, desc, vals, head, explicit = c
            v = vals[-1] if len(vals) == 1 else vals[0]
            amount = v if (explicit or v < 0) else _signed(v, desc, head)
            if amount:
                rows.append((d, desc, amount))
    return rows


def _same_digits(a: float, b: float) -> bool:
    """True if two amounts agree, allowing for a decimal point OCR dropped (".26" read as "26")."""
    if abs(a - b) < 0.015:
        return True
    da, db = re.sub(r"\D", "", f"{a:.2f}").lstrip("0"), re.sub(r"\D", "", f"{b:.2f}").lstrip("0")
    return bool(da) and (da == db or da == db.rstrip("0") or da.rstrip("0") == db.rstrip("0"))


def _signed(value: float, desc: str, heading: int) -> float:
    if value < 0:
        return value
    low = desc.lower()
    if heading:
        return value * heading
    return value if any(w in low for w in _CREDIT_WORDS) else -value


def _resolve_dates(cands: list, today: date) -> list[str] | None:
    """Decide day/month order and missing years, then return ISO date strings."""
    nums = [c[2] for c in cands if c[1] == "num"]
    if any(a > 12 for a, _, _ in nums):
        dayfirst = True
    elif any(b > 12 for _, b, _ in nums):
        dayfirst = False
    else:  # both readings are possible: keep the one where dates run in order over the shortest period
        def score(df: bool) -> tuple[int, int]:
            seq = [(b, a) if df else (a, b) for a, b, _ in nums]
            disorder = sum(1 for x, y in zip(seq, seq[1:]) if y < x)
            days = [m * 31 + d for m, d in seq]
            return disorder, max(days) - min(days)
        dayfirst = score(True) <= score(False)

    md: list[tuple[int, int, int | None]] = []  # (month, day, year or None)
    for c in cands:
        kind, p = c[1], c[2]
        if kind == "iso":
            md.append((p[1], p[2], p[0]))
        elif kind == "num":
            d, m = (p[0], p[1]) if dayfirst else (p[1], p[0])
            md.append((m, d, _year(p[2])))
        else:
            md.append((p[1], p[0], _year(p[2])))

    # Missing years: count Dec -> Jan rollovers and end the statement in the current year,
    # unless its latest date would then be in the future (then it is last year's statement).
    rollovers = sum(1 for x, y in zip(md, md[1:]) if y[0] < x[0] - 6)

    def build(end_year: int) -> list[date | None]:
        year, prev_m, out = end_year - rollovers, None, []
        for m, d, y in md:
            if prev_m is not None and m < prev_m - 6:
                year += 1
            prev_m = m
            try:
                out.append(date(y or year, m, d))
            except ValueError:
                out.append(None)
        return out

    dates = build(today.year)
    undated = [dt for dt, (_, _, y) in zip(dates, md) if dt and y is None]
    if undated and max(undated) > today:
        dates = build(today.year - 1)
    return [dt.isoformat() if dt else "" for dt in dates]
