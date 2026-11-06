"""Read bank / mobile-wallet statements (CSV, XLSX, text or scanned PDF) into a clean pandas DataFrame."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pandas as pd

from .common import AnalyzerError
from .pdf_reader import pdf_to_frame
from .privacy import mask_text, normalize_description

SUPPORTED_TYPES = ["csv", "xlsx", "xls", "pdf"]
MAX_ROWS = 2000  # rows kept after parsing; the UI says so

AMOUNT_MODES = {
    "signed": "One amount column (negative = money out)",
    "debit_credit": "Separate debit (out) and credit (in) columns",
    "type_column": "Amount column + a Dr/Cr (type) column",
}

_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


@dataclass
class Mapping:
    date: str
    description: str
    mode: str = "signed"
    amount: str | None = None
    debit: str | None = None
    credit: str | None = None
    type_col: str | None = None
    dayfirst: bool = True
    flip_sign: bool = False  # for statements that show spending as positive numbers


def read_table(data: bytes, filename: str) -> pd.DataFrame:
    """Load the raw table. Finds the header row even when the bank adds a few title lines on top."""
    ext = filename.rsplit(".", 1)[-1].lower()
    used_ocr = False
    try:
        if ext == "csv":
            text = data.decode("utf-8-sig", errors="replace")
            lines = text.splitlines()
            skip = _header_row([ln.split(",") for ln in lines[:30]])
            df = pd.read_csv(io.StringIO(text), skiprows=skip, dtype=str, skip_blank_lines=True)
        elif ext in ("xlsx", "xls"):
            raw = pd.read_excel(io.BytesIO(data), header=None, dtype=str)
            skip = _header_row(raw.head(30).fillna("").values.tolist())
            df = pd.read_excel(io.BytesIO(data), skiprows=skip, dtype=str)
        elif ext == "pdf":
            df, used_ocr = pdf_to_frame(data)
        else:
            raise AnalyzerError(f"Unsupported file type: .{ext}")
    except AnalyzerError:
        raise
    except Exception as exc:
        raise AnalyzerError(f"Could not read the file: {exc}") from exc
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")] if len(df.columns) > 2 else df
    if df.empty or len(df.columns) < 2:
        raise AnalyzerError("No table found in the file. Export the statement as CSV or Excel and try again.")
    df.attrs["ocr"] = used_ocr
    return df


def _header_row(rows: list[list]) -> int:
    keys = ("date", "description", "details", "particular", "narration", "amount", "debit", "credit", "withdraw")
    for i, row in enumerate(rows):
        cells = " ".join(str(c).lower() for c in row)
        if sum(k in cells for k in keys) >= 2:
            return i
    return 0


def guess_mapping(df: pd.DataFrame) -> Mapping:
    cols = list(df.columns)
    low = {c: c.lower() for c in cols}

    def find(*keys, exclude=()):
        for k in keys:
            for c in cols:
                if k in low[c] and not any(e in low[c] for e in exclude):
                    return c
        return None

    date = find("date", "time") or cols[0]
    desc = find("description", "details", "particular", "narration", "remarks", "merchant", "note") or cols[1]
    debit = find("debit", "withdraw", "money out", "paid out", "dr", exclude=("date",))
    credit = find("credit", "deposit", "money in", "paid in", "cr", exclude=("date", "card", "description"))
    amount = find("amount", "amt", exclude=("balance",))
    type_col = find("type", "dr/cr", "cr/dr", exclude=("amount",))
    if debit and credit and debit != credit:
        return Mapping(date, desc, "debit_credit", debit=debit, credit=credit)
    if amount and type_col:
        vals = df[type_col].astype(str).str.strip().str.lower().unique()[:20]
        if any(v in ("dr", "cr", "debit", "credit", "in", "out") for v in vals):
            return Mapping(date, desc, "type_column", amount=amount, type_col=type_col)
    return Mapping(date, desc, "signed", amount=amount or cols[-1])


def to_number(series: pd.Series) -> pd.Series:
    """'৳ 1,250.00', '(500)', '1,200 Dr', '১২০০' -> floats (sign kept, NaN when empty)."""
    s = series.astype(str).str.translate(_BN_DIGITS).str.strip()
    neg = s.str.startswith("(") & s.str.endswith(")") | s.str.contains(r"^-|-\s*$", regex=True)
    s = s.str.replace(r"[^\d.]", "", regex=True).replace("", None)
    out = pd.to_numeric(s, errors="coerce")
    return out.where(~neg, -out)


def apply_mapping(raw: pd.DataFrame, m: Mapping) -> tuple[pd.DataFrame, int]:
    """Return (transactions, rows_dropped). Columns: id, date, month, description, masked, key, amount."""
    for col in (m.date, m.description, m.amount, m.debit, m.credit, m.type_col):
        if col and col not in raw.columns:
            raise AnalyzerError(f"Column '{col}' is not in the file.")
    df = pd.DataFrame()
    dates = raw[m.date].astype(str).str.translate(_BN_DIGITS).str.strip()
    # ISO dates (2026-10-02) are never day-first; parsing them with dayfirst=True would swap day and month.
    iso = dates.str.match(r"^\d{4}-\d{1,2}-\d{1,2}")
    df["date"] = pd.to_datetime(dates.where(~iso), dayfirst=m.dayfirst, errors="coerce", format="mixed")
    df.loc[iso, "date"] = pd.to_datetime(dates[iso].str[:10], errors="coerce", format="%Y-%m-%d")
    df["description"] = raw[m.description].fillna("").astype(str).str.strip()
    if m.mode == "debit_credit":
        debit = to_number(raw[m.debit]).abs().fillna(0)
        credit = to_number(raw[m.credit]).abs().fillna(0)
        df["amount"] = credit - debit
        df.loc[(debit == 0) & (credit == 0), "amount"] = float("nan")
    elif m.mode == "type_column":
        amt = to_number(raw[m.amount]).abs()
        t = raw[m.type_col].astype(str).str.strip().str.lower()
        is_out = t.str.startswith(("dr", "debit", "out", "withdraw", "payment", "send", "cash out"))
        df["amount"] = amt.where(~is_out, -amt)
    else:
        df["amount"] = to_number(raw[m.amount])
    if m.flip_sign:
        df["amount"] = -df["amount"]
    before = len(df)
    df = df.dropna(subset=["date", "amount"])
    df = df[df["amount"] != 0]
    dropped = before - len(df)
    df = df.sort_values("date", kind="stable").head(MAX_ROWS).reset_index(drop=True)
    if df.empty:
        raise AnalyzerError("No valid rows after mapping. Check the date and amount columns.")
    df.insert(0, "id", range(1, len(df) + 1))
    df["month"] = df["date"].dt.strftime("%Y-%m")
    df["masked"] = df["description"].map(mask_text)
    df["key"] = df["description"].map(normalize_description)
    return df, dropped
