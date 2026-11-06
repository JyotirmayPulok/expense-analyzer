"""Offline tests: masking, pandas parsing on the sample file, analytics, PDF, and mocked Gemini calls."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import httpx
import pandas as pd
import pytest
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import analytics as an  # noqa: E402
from core import gemini_llm  # noqa: E402
from core.common import AnalyzerError, unique_descriptions  # noqa: E402
from core.parser import Mapping, apply_mapping, guess_mapping, read_table, to_number  # noqa: E402
from core.privacy import mask_text, normalize_description  # noqa: E402
from core.report import build_pdf  # noqa: E402
from core.schema import InsightsResult  # noqa: E402

SAMPLE = ROOT / "samples" / "sample_statement.csv"


# ---------- masking ----------
@pytest.mark.parametrize("text, hidden, placeholder", [
    ("POS PURCHASE CARD 4321-XXXX-XXXX-9876 FRESHBASKET", "9876", "[CARD]"),
    ("POS 4111 1111 1111 1111 SHOP", "1111", "[CARD]"),
    ("bKash Send Money to 01698765432", "01698765432", "[PHONE]"),
    ("Recharge +8801912345678 done", "1912345678", "[PHONE]"),
    ("FUND TRANSFER TO A/C 1234567890 RENT", "1234567890", "[ACCOUNT]"),
    ("Payment ref 20261003998877", "20261003998877", "["),
    ("RIDENOW TrxID 9F3K2L1M8A", "9F3K2L1M8A", "[REF]"),
    ("Invoice sent to demo.person@example.com", "demo.person@example.com", "[EMAIL]"),
])
def test_mask_hides_identifiers(text, hidden, placeholder):
    out = mask_text(text)
    assert hidden not in out and placeholder in out, out


def test_mask_keeps_normal_words_and_small_numbers():
    assert mask_text("KACCHI CORNER 2 PLATES 450") == "KACCHI CORNER 2 PLATES 450"
    assert mask_text("DESCO ELECTRICITY AUG 2026") == "DESCO ELECTRICITY AUG 2026"


def test_normalize_groups_same_merchant():
    a = normalize_description("RIDENOW DEMO RIDE TrxID ABCD1234EF")
    b = normalize_description("RIDENOW DEMO RIDE TrxID ZZZZ9999QQ")
    assert a == b == "ridenow demo ride"


# ---------- parsing ----------
def test_parse_sample_csv():
    raw = read_table(SAMPLE.read_bytes(), SAMPLE.name)  # skips the 3 title lines on top
    m = guess_mapping(raw)
    assert (m.date, m.description, m.mode, m.debit, m.credit) == ("Txn Date", "Description", "debit_credit", "Debit", "Credit")
    tx, dropped = apply_mapping(raw, m)
    assert len(tx) == 143 and dropped == 0
    assert tx["date"].min() == pd.Timestamp("2026-08-01") and tx["date"].max() == pd.Timestamp("2026-10-28")
    assert tx["month"].nunique() == 3
    assert (tx.loc[tx["description"].str.contains("SALARY"), "amount"] == 98000).all()
    assert (tx.loc[tx["description"].str.contains("LANDLORD"), "amount"] == -25000).all()
    assert not tx["masked"].str.contains("01698765432|9876|1234567890").any()


def test_parse_xlsx_signed_and_type_column():
    df = pd.DataFrame({"Date": ["2026-10-01", "2026-10-02", "2026-10-03"], "Details": ["Salary", "Shop", "Cafe"],
                       "Amount": ["50,000", "1,200.50", "৳ ৩০০"], "Dr/Cr": ["Cr", "Dr", "Dr"]})
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    raw = read_table(buf.getvalue(), "s.xlsx")
    m = guess_mapping(raw)
    assert m.mode == "type_column"
    tx, _ = apply_mapping(raw, m)
    assert tx["amount"].tolist() == [50000.0, -1200.5, -300.0]
    tx2, _ = apply_mapping(raw, Mapping("Date", "Details", "signed", amount="Amount", flip_sign=True))
    assert tx2["amount"].tolist() == [-50000.0, -1200.5, -300.0]


def test_to_number_formats():
    s = to_number(pd.Series(["(500)", "-1,250.75", "1,000 Dr", "", "abc"]))
    assert s.iloc[0] == -500 and s.iloc[1] == -1250.75 and s.iloc[2] == 1000 and s.iloc[3:].isna().all()


# ---------- analytics + PDF on the demo data ----------
@pytest.fixture(scope="module")
def demo_tx():
    raw = read_table(SAMPLE.read_bytes(), SAMPLE.name)
    tx, _ = apply_mapping(raw, guess_mapping(raw))
    demo = json.loads((ROOT / "samples" / "sample_analysis.json").read_text())
    return an.apply_categories(tx, {k: tuple(v) for k, v in demo["categories"].items()}), demo


def test_kpis_and_detection(demo_tx):
    tx, _ = demo_tx
    k = an.kpis(tx)
    assert round(k["income"]) == 313312 and round(k["expenses"]) == 277386 and k["moved_to_savings"] == 15000
    assert abs(k["savings_rate"] - k["net"] / k["income"] * 100) < 1e-9
    assert abs(an.category_totals(tx)["share"].sum() - 100) < 1e-6
    rec = set(an.recurring(tx)["merchant"])
    assert {"Landlord (rent)", "StreamFlix", "FitZone Gym"} <= rec and "RideNow" not in rec
    unu = an.unusual(tx)
    assert "GadgetHub Electronics" in set(unu["merchant"]) and "Landlord (rent)" not in set(unu["merchant"])
    assert (unu["merchant"] == "FoodDash").sum() == 2  # the duplicate charge


def test_insights_payload_has_no_raw_identifiers(demo_tx):
    tx, _ = demo_tx
    text = json.dumps(an.insights_payload(tx))
    for secret in ("01698765432", "1234567890", "9876", "01812345678"):
        assert secret not in text


def test_pdf_builds(demo_tx):
    tx, demo = demo_tx
    pdf = build_pdf(tx, "BDT", InsightsResult(**demo["insights"]))
    assert pdf[:5] == b"%PDF-" and len(pdf) > 10_000
    assert build_pdf(tx, "USD", None)[:5] == b"%PDF-"  # works without AI insights too


# ---------- Gemini, mocked offline ----------
def _client(handler) -> genai.Client:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return genai.Client(api_key="t", http_options=types.HttpOptions(httpx_client=http))


def _reply(obj: dict) -> dict:
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(obj)}]},
                            "finishReason": "STOP"}]}


def test_categorize_one_request_masked(demo_tx):
    tx, _ = demo_tx
    uniq = unique_descriptions(tx)
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        body = json.loads(req.content)
        text = body["contents"][0]["parts"][0]["text"]
        ids = [json.loads(ln)["id"] for ln in text.splitlines()[1:]]
        items = [{"id": i, "merchant": f"M{i}", "category": "Groceries"} for i in ids]
        return httpx.Response(200, json=_reply({"items": items}))

    by_key = gemini_llm.categorize(_client(handler), "gemini-3.5-flash-lite", uniq)
    assert len(calls) == 1  # ONE batched request
    sent = calls[0].content.decode()
    assert "responseSchema" in sent or "response_json_schema" in sent or "responseJsonSchema" in sent
    for secret in ("01698765432", "1234567890", "9876", "01912345678"):
        assert secret not in sent
    assert len(by_key) == len(uniq)
    out = an.apply_categories(tx, by_key)
    assert (out.loc[out["amount"] > 0, "category"] == "Transfers In").all()  # income never gets a spending category


def test_insights_parses(demo_tx):
    tx, demo = demo_tx
    handler = lambda req: httpx.Response(200, json=_reply(demo["insights"]))  # noqa: E731
    res = gemini_llm.insights(_client(handler), "gemini-3.5-flash-lite", an.insights_payload(tx), "BDT")
    assert isinstance(res, InsightsResult) and res.health_score == 68


@pytest.mark.parametrize("status, needle", [
    (429, "free-tier limit"), (400, "rejected"), (403, "Invalid Gemini API key"), (404, "isn't available"),
])
def test_api_errors_are_friendly_and_not_retried(demo_tx, status, needle):
    tx, _ = demo_tx
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(status, json={"error": {"code": status, "message": "quota / bad thing",
                                                      "status": "RESOURCE_EXHAUSTED"}})

    with pytest.raises(AnalyzerError, match=needle):
        gemini_llm.categorize(_client(handler), "gemini-3.5-flash-lite", unique_descriptions(tx))
    assert len(calls) == 1  # no automatic retries


def test_incomplete_json_is_reported():
    handler = lambda req: httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [  # noqa
        {"text": '{"summary": "cut'}]}, "finishReason": "MAX_TOKENS"}]})
    with pytest.raises(AnalyzerError, match="incomplete"):
        gemini_llm.insights(_client(handler), "m", {"a": 1}, "BDT")


def test_list_models_fallback_and_order():
    models = {"models": [
        {"name": "models/gemini-3.6-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-3.5-flash-image", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
    ]}
    orig = gemini_llm.make_client
    gemini_llm.make_client = lambda key: _client(lambda req: httpx.Response(200, json=models))
    try:
        assert gemini_llm.list_models("k") == ["gemini-3.5-flash-lite", "gemini-3.6-flash"]
    finally:
        gemini_llm.make_client = orig
