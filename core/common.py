"""Prompts, payload builders and the user-facing error type."""

from __future__ import annotations

import json

import pandas as pd

from .schema import CATEGORIES

MAX_UNIQUE_DESCRIPTIONS = 400  # descriptions sent in the single categorisation request


class AnalyzerError(Exception):
    """Error with a message that is safe to show to the user."""


DISCLAIMER = (
    "This tool gives general budgeting guidance only. It is not financial, tax or investment advice. "
    "Check important decisions with a qualified professional."
)

CATEGORIZE_SYSTEM = f"""You categorise personal bank and mobile-wallet transactions (often from Bangladesh: \
bKash, Nagad, Rocket, local banks, shops and bill payers).

For every input line return its id, a short clean merchant/counterparty name and ONE category from this list:
{", ".join(CATEGORIES)}.

Rules:
- "sign" tells you the money direction: "in" = money received, "out" = money spent, "both" = seen both ways.
- Money "in" is usually "Salary & Income" or "Transfers In". Never give an "out" line an income category.
- Placeholders like [PHONE], [CARD], [ACCOUNT], [REF] are masked personal data; ignore them.
- Streaming, music, cloud storage, software and gym memberships are "Subscriptions".
- Mobile recharge, data packs and home internet are "Mobile & Internet". Electricity, gas, water are "Bills & Utilities".
- "Cash out" from a wallet or ATM is "Cash Withdrawal". Sending money to a person is "Transfers Out".
- If unsure, use "Other". Return exactly one item per input id."""

INSIGHTS_SYSTEM = """You are a friendly, practical personal-budgeting coach. You receive aggregated numbers from \
one person's statement (already computed exactly; trust them, do not recompute) plus a short list of candidate \
recurring and unusual transactions found by simple rules.

Write specific, data-backed guidance:
- Quote real figures from the data with the currency code. Never invent transactions or amounts.
- recurring_payments: confirm or reject the candidates; mark true subscriptions.
- unusual_transactions: pick only candidates that genuinely look unusual (very large, one-off, duplicate-looking).
- budget_suggestions: realistic monthly limits for each expense category with spending, usually near or a bit \
below the recent monthly average; essentials (rent, utilities, groceries, health) should not be cut sharply.
- saving_tips: general, practical habits (e.g. a savings transfer on payday, reviewing subscriptions). \
Do NOT recommend specific stocks, funds, crypto, loans or other financial products. This is budgeting guidance, \
not financial or investment advice."""


def unique_descriptions(tx: pd.DataFrame) -> pd.DataFrame:
    """One row per normalised description: uid, masked sample text, money direction, count."""
    g = tx.groupby("key", sort=False)
    out = pd.DataFrame({
        "text": g["masked"].first(),
        "n_in": g["amount"].apply(lambda s: int((s > 0).sum())),
        "n_out": g["amount"].apply(lambda s: int((s < 0).sum())),
        "count": g.size(),
    }).reset_index()
    out["sign"] = out.apply(lambda r: "both" if r.n_in and r.n_out else "in" if r.n_in else "out", axis=1)
    out = out.sort_values("count", ascending=False, kind="stable").reset_index(drop=True)
    out.insert(0, "uid", range(1, len(out) + 1))
    return out


def categorize_prompt(uniq: pd.DataFrame) -> str:
    lines = [{"id": int(r.uid), "text": r.text, "sign": r.sign} for r in uniq.head(MAX_UNIQUE_DESCRIPTIONS).itertuples()]
    return ("Categorise these transaction descriptions (JSON lines, personal data already masked):\n"
            + "\n".join(json.dumps(x, ensure_ascii=False) for x in lines))


def insights_prompt(summary: dict, currency: str) -> str:
    return (f"Currency: {currency}\n\n<statement_summary>\n{json.dumps(summary, indent=1, ensure_ascii=False)}\n"
            "</statement_summary>\n\nProduce the structured budgeting insights.")
