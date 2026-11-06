"""PDF statements: line parsing (no OCR needed), text-layer PDFs and scanned (image-only) PDFs via Tesseract."""

from __future__ import annotations

import io
import shutil
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.parser import apply_mapping, guess_mapping, read_table  # noqa: E402
from core.pdf_reader import parse_statement_lines  # noqa: E402

TODAY = date(2026, 11, 6)

# Shaped like OCR output of a US checking statement: MM/DD dates with no year, Debit/Credit/Balance columns,
# one OCR slip (".26" read as "26"), and a second page that lists the same transactions again by type.
OCR_LINES = """Summary of Your Account
Beginning balance on October 10 $69.96 Avg Collected Balance $643.24
Date Description Debit Credit Balance
10/02 POS PURCHASE 4.23 65.73
10/03 PREAUTHORIZED CREDIT 763.01 828.74
10/05 CHECK 1234 9.98 818.76
10/22 ATMWITHDRAWAL 140.00 678.76
11/09 INTEREST CREDIT 26 679.02
11/09 SERVICE CHARGE 12.00 667.02
Page 2 of 2
Deposits and Other Credits
Date Description Amount
10/03 PREAUTHORIZED CREDIT PAYROLL0987654678990 763.01
11/09 INTERESTCREDIT 0.26
Withdrawals and Other Debits
10/02 POSPURCHASE TERMINAL 24349201 SHOP WICHITA KS 4.23
1234 10/05 $9.98 1238 10/28 $91.06""".splitlines()


def test_balance_statement_signs_dedup_and_ocr_slip():
    rows = parse_statement_lines(OCR_LINES, TODAY)
    assert rows == [
        ("2025-10-02", "POS PURCHASE", -4.23),
        ("2025-10-03", "PREAUTHORIZED CREDIT", 763.01),
        ("2025-10-05", "CHECK 1234", -9.98),
        ("2025-10-22", "ATMWITHDRAWAL", -140.0),
        ("2025-11-09", "INTEREST CREDIT", 0.26),  # repaired from the balance change
        ("2025-11-09", "SERVICE CHARGE", -12.0),
    ]  # 9 Nov 2026 is still in the future on 6 Nov 2026, so the undated statement is placed in 2025


def test_no_balance_column_uses_dr_cr_and_headings():
    lines = ["Money In", "05/10/2026 Salary FakeCorp 50,000.00", "Money Out",
             "06/10/2026 FreshBasket Demo 1,250.50", "07/10/2026 Refund ShopEase 300.00 Cr",
             "08/10/2026 bKash Cash Out 2,000.00 Dr", "31/10/2026 Fee (55.50)"]
    rows = parse_statement_lines(lines, TODAY)
    assert rows == [("2026-10-05", "Salary FakeCorp", 50000.0), ("2026-10-06", "FreshBasket Demo", -1250.5),
                    ("2026-10-07", "Refund ShopEase", 300.0), ("2026-10-08", "bKash Cash Out", -2000.0),
                    ("2026-10-31", "Fee", -55.5)]


def test_day_month_order_and_year_rollover():
    rows = parse_statement_lines(["12/28 Grocery 10.00 90.00", "01/03 Grocery 5.00 85.00"], TODAY)
    assert rows == [("2025-12-28", "Grocery", -10.0), ("2026-01-03", "Grocery", -5.0)]  # 28 > 12: month first
    rows = parse_statement_lines(["28/12 Opening 1.00 Dr", "03/01 Shop 5.00 Dr"], TODAY)
    assert [r[0] for r in rows] == ["2025-12-28", "2026-01-03"]


def test_iso_dates_are_not_swapped_by_dayfirst():
    raw = pd.DataFrame({"Date": ["2026-10-02", "2026-11-09"], "Description": ["a", "b"], "Amount": ["-1", "2"]})
    tx, _ = apply_mapping(raw, guess_mapping(raw))
    assert tx["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-10-02", "2026-11-09"]


def _statement_pdf(lines: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 780
    for ln in lines:
        c.setFont("Helvetica", 11)
        c.drawString(50, y, ln)
        y -= 18
    c.save()
    return buf.getvalue()


SIMPLE = ["Demo Bank (FICTIONAL) statement", "Beginning balance $1,000.00",
          "Date Description Debit Credit Balance", "10/02/2026 SALARY FAKECORP 5,000.00 6,000.00",
          "10/05/2026 FRESHBASKET DEMO 250.75 5,749.25", "10/09/2026 RIDENOW DEMO 120.00 5,629.25"]
EXPECTED = [5000.0, -250.75, -120.0]


def test_text_layer_pdf():
    raw = read_table(_statement_pdf(SIMPLE), "s.pdf")
    assert raw.attrs["ocr"] is False
    tx, _ = apply_mapping(raw, guess_mapping(raw))
    assert tx["amount"].tolist() == EXPECTED


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract OCR not installed")
def test_scanned_pdf_is_read_with_ocr():
    import pypdfium2 as pdfium
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    image = pdfium.PdfDocument(_statement_pdf(SIMPLE))[0].render(scale=200 / 72).to_pil()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawImage(ImageReader(image), 0, 0, *A4)  # image only: no text layer
    c.save()
    assert pdfium.PdfDocument(buf.getvalue())[0].get_textpage().get_text_range().strip() == ""
    raw = read_table(buf.getvalue(), "scan.pdf")
    assert raw.attrs["ocr"] is True
    tx, _ = apply_mapping(raw, guess_mapping(raw))
    assert tx["amount"].tolist() == EXPECTED
    # 10/02, 10/05, 10/09 fit both orders; one week (Oct 2-9) beats seven months (Feb 10 - Sep 10)
    assert tx["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-10-02", "2026-10-05", "2026-10-09"]
