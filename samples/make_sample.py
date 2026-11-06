"""Generate the SYNTHETIC demo statement and its pre-generated demo analysis.

All names, numbers and phone/card/account numbers here are fake. Run:  python samples/make_sample.py
"""

from __future__ import annotations

import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import analytics as an  # noqa: E402
from core.parser import apply_mapping, guess_mapping, read_table  # noqa: E402
from core.schema import InsightsResult  # noqa: E402

random.seed(42)
CARD = "4321-XXXX-XXXX-9876"
rows: list[tuple[date, str, float]] = []  # (date, description, signed amount)


def add(d: date, desc: str, amount: float) -> None:
    rows.append((d, desc, round(amount, 2)))


def trx() -> str:
    return "TrxID " + "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10))


months = [(2026, 8), (2026, 9), (2026, 10)]
for y, m in months:
    d = lambda day: date(y, m, day)  # noqa: E731
    add(d(1), "SALARY CREDIT FAKECORP FICTIONAL LTD", 98000)
    add(d(3), "FUND TRANSFER RENT TO LANDLORD A/C 1234567890", -25000)
    add(d(4), "DPS INSTALLMENT DEMO BANK SAVINGS SCHEME", -5000)
    add(d(6), f"BILL PAY DESCO DEMO ELECTRICITY {trx()}", -random.choice([1840, 2150, 2380]))
    add(d(7), "TITAS DEMO GAS BILL PAYMENT", -1080)
    add(d(8), "LINKNET DEMO ISP HOME INTERNET", -1200)
    add(d(9), f"POS PURCHASE CARD {CARD} STREAMFLIX DEMO SUBSCRIPTION", -799)
    add(d(12), f"POS PURCHASE CARD {CARD} TUNEBOX MUSIC PREMIUM", -299)
    add(d(15), "CLOUDVAULT DEMO STORAGE PLAN", -260)
    add(d(5), "FITZONE DEMO GYM MEMBERSHIP", -2500)
    if m != 9:
        add(d(18), f"bKash Received from 01711223344 {trx()}", random.choice([9500, 12000]))
    for day in sorted(random.sample(range(1, 29), 4)):
        add(d(day), f"Mobile Recharge 01912345678 {trx()}", -random.choice([299, 399, 499]))
    for day in sorted(random.sample(range(2, 29), 6)):
        add(d(day), f"POS PURCHASE CARD {CARD} FRESHBASKET DEMO SUPERSHOP", -random.randint(8, 36) * 100)
    for day in sorted(random.sample(range(1, 29), 7)):
        wk = date(y, m, day).weekday() >= 4  # Fri/Sat are the weekend in Bangladesh
        place = random.choice(["KACCHI CORNER DEMO RESTAURANT", "CAFE PLACEHOLDER", "FOODDASH DEMO DELIVERY"])
        add(d(day), f"POS PURCHASE CARD {CARD} {place}", -random.randint(12, 32) * 50 * (1.6 if wk else 1))
    for day in sorted(random.sample(range(1, 29), 10)):
        add(d(day), f"RIDENOW DEMO RIDE {trx()}", -random.randint(15, 45) * 10)
    add(d(20), "FUEL STATION DEMO PUMP", -random.choice([1500, 2000]))
    add(d(22), f"MEDICARE DEMO PHARMACY {trx()}", -random.randint(4, 18) * 100)
    add(d(25), f"bKash Cash Out Agent 01812345678 {trx()}", -3000)
    add(d(25), "Cash Out Charge", -55.5)
    for day in sorted(random.sample(range(5, 28), 2)):
        add(d(day), f"SHOPEASE DEMO ONLINE ORDER {trx()}", -random.randint(9, 40) * 100)
    add(d(27), f"bKash Send Money to 01698765432 {trx()}", -random.choice([2000, 3000]))
    add(d(28), "ACCOUNT MAINTENANCE FEE AND VAT", -172.5)

# One-off / unusual items
add(date(2026, 9, 14), f"POS PURCHASE CARD {CARD} GADGETHUB DEMO ELECTRONICS", -38500)
add(date(2026, 10, 19), f"POS PURCHASE CARD {CARD} FOODDASH DEMO DELIVERY", -1450)
add(date(2026, 10, 19), f"POS PURCHASE CARD {CARD} FOODDASH DEMO DELIVERY", -1450)
add(date(2026, 10, 10), "SKYHOP DEMO AIR TICKET DAC-CXB", -7800)
add(date(2026, 8, 21), "BOOKNOOK DEMO BOOKS AND COURSES", -1350)
add(date(2026, 9, 30), "INTEREST CREDIT SAVINGS", 312.4)

rows.sort(key=lambda r: r[0])
bal = 54000.0
lines = [
    "Demo Bank Ltd (FICTIONAL) - Account Statement - SYNTHETIC SAMPLE DATA",
    "Account holder: Demo Person, A/C 0099887766554 (fake)",
    "",
    "Txn Date,Description,Debit,Credit,Balance",
]
for dt, desc, amt in rows:
    bal += amt
    debit = f"{-amt:,.2f}" if amt < 0 else ""
    credit = f"{amt:,.2f}" if amt > 0 else ""
    lines.append(f'{dt:%d/%m/%Y},"{desc}","{debit}","{credit}","{bal:,.2f}"')
csv_path = ROOT / "samples" / "sample_statement.csv"
csv_path.write_text("\n".join(lines) + "\n")

# ---------- pre-generated "AI" output for Demo mode (hand-written from the real numbers) ----------
MERCHANTS = {
    "salary": ("FakeCorp Fictional Ltd", "Salary & Income"), "landlord": ("Landlord (rent)", "Rent & Housing"),
    "dps": ("Demo Bank DPS", "Savings & Investments"), "desco": ("DESCO (demo)", "Bills & Utilities"),
    "titas": ("Titas Gas (demo)", "Bills & Utilities"), "linknet": ("LinkNet ISP", "Mobile & Internet"),
    "streamflix": ("StreamFlix", "Subscriptions"), "tunebox": ("TuneBox Music", "Subscriptions"),
    "cloudvault": ("CloudVault", "Subscriptions"), "fitzone": ("FitZone Gym", "Subscriptions"),
    "received": ("bKash transfer in", "Transfers In"), "recharge": ("Mobile recharge", "Mobile & Internet"),
    "freshbasket": ("FreshBasket", "Groceries"), "kacchi": ("Kacchi Corner", "Food & Dining"),
    "cafe": ("Cafe Placeholder", "Food & Dining"), "fooddash": ("FoodDash", "Food & Dining"),
    "ridenow": ("RideNow", "Transport"), "fuel": ("Fuel Station", "Transport"),
    "medicare": ("MediCare Pharmacy", "Health"), "cash out agent": ("bKash cash out", "Cash Withdrawal"),
    "cash out charge": ("bKash cash-out fee", "Fees & Charges"), "shopease": ("ShopEase", "Shopping"),
    "send money": ("bKash send money", "Transfers Out"), "maintenance": ("Bank fees", "Fees & Charges"),
    "gadgethub": ("GadgetHub Electronics", "Shopping"), "skyhop": ("SkyHop Air", "Travel"),
    "booknook": ("BookNook", "Education"), "interest": ("Savings interest", "Salary & Income"),
}
raw = read_table(csv_path.read_bytes(), csv_path.name)
tx, _ = apply_mapping(raw, guess_mapping(raw))
categories = {}
for key in tx["key"].unique():
    hit = next(v for k, v in MERCHANTS.items() if k in key)
    categories[key] = list(hit)
tx = an.apply_categories(tx, {k: tuple(v) for k, v in categories.items()})
k = an.kpis(tx)
cats = an.category_totals(tx).set_index("category")
mon = an.monthly(tx).set_index("month")
rec = an.recurring(tx)
unu = an.unusual(tx)
sub_total = float(rec.loc[rec["category"] == "Subscriptions", "typical_amount"].sum())
food = cats.loc["Food & Dining"]
gadget_id = int(tx.loc[tx["key"].str.contains("gadgethub"), "id"].iat[0])
dup_ids = tx.loc[tx["key"].str.contains("fooddash") & (tx["amount"] == -1450), "id"].tolist()
air_id = int(tx.loc[tx["key"].str.contains("skyhop"), "id"].iat[0])


def bdt(x: float) -> str:
    return f"BDT {x:,.0f}"


budget_plan = {
    "Rent & Housing": 25000, "Groceries": 12500, "Food & Dining": 8000, "Transport": 4500, "Bills & Utilities": 3300,
    "Mobile & Internet": 2400, "Subscriptions": 3200, "Shopping": 5000, "Health": 1200, "Cash Withdrawal": 3000,
    "Transfers Out": 2500, "Fees & Charges": 250, "Travel": 1500, "Education": 600,
}
insights = InsightsResult(
    summary=(f"Over {k['months']} months you received {bdt(k['income'])} and spent {bdt(k['expenses'])}, "
             f"leaving {bdt(k['net'])} (a {k['savings_rate']:.0f}% savings rate) plus {bdt(k['moved_to_savings'])} "
             "already moved into a DPS. Rent is the single biggest cost. September was the tightest month because "
             "of a one-off electronics purchase. Day-to-day spending on food, rides and subscriptions is steady but "
             "has room to trim."),
    health_score=68,
    spending_patterns=[
        {"title": "Rent is over a quarter of spending",
         "detail": f"Rent & Housing is {bdt(cats.loc['Rent & Housing', 'total'])} "
                   f"({cats.loc['Rent & Housing', 'share']:.0f}% of expenses). That is normal for Dhaka but leaves "
                   "less room elsewhere."},
        {"title": "September spending spiked",
         "detail": f"Expenses were {bdt(mon.loc['2026-09', 'expenses'])} in September vs "
                   f"{bdt(mon.loc['2026-08', 'expenses'])} in August, mainly the GadgetHub purchase."},
        {"title": "Eating out is a steady habit",
         "detail": f"Food & Dining averaged {bdt(food['monthly_avg'])} a month over {int(food['count'])} orders; "
                   "weekend (Fri/Sat) orders are noticeably larger."},
        {"title": "Many small ride payments add up",
         "detail": f"Transport totalled {bdt(cats.loc['Transport', 'total'])}, mostly small RideNow trips of "
                   "BDT 150-450 each."},
        {"title": "Subscriptions are a fixed monthly cost",
         "detail": f"Four subscriptions cost about {bdt(sub_total)} every month, before you use any of them."},
    ],
    recurring_payments=[
        {"merchant": r.merchant, "typical_amount": r.typical_amount, "frequency": r.frequency,
         "is_subscription": r.category == "Subscriptions",
         "note": {"Landlord (rent)": "Essential; keep.", "Demo Bank DPS": "Good habit; keep this savings transfer.",
                  "FitZone Gym": "Review: keep only if you go at least 8 times a month.",
                  "StreamFlix": "Consider pausing in busy months.",
                  "TuneBox Music": "Low cost; keep if used daily.",
                  "CloudVault": "Check if a free storage tier is enough."}.get(
                      r.merchant, "Regular bill; check the amount each month.")}
        for r in rec.itertuples()
    ],
    unusual_transactions=[
        {"txn_id": gadget_id, "reason": "A one-off BDT 38,500 electronics purchase, about 10x a normal shopping payment.",
         "severity": "high"},
        *[{"txn_id": int(i), "reason": "Two identical FoodDash charges on the same day; check it was not a double charge.",
           "severity": "medium"} for i in dup_ids],
        {"txn_id": air_id, "reason": "Air ticket; a one-off travel cost worth planning for in advance.", "severity": "low"},
    ],
    saving_tips=[
        "Set up an automatic savings transfer on payday (the 1st), before any spending starts.",
        "Keep a small 'big purchase' fund each month so items like the GadgetHub buy do not squeeze one month.",
        f"Review the four subscriptions (about {bdt(sub_total)}/month); cancelling one saves BDT 3,000+ a year.",
        "Plan two home-cooked weekend meals; food delivery on Fri/Sat is your largest food cost.",
        "Group short trips or use the bus or metro for regular routes to cut many small ride payments.",
        "Withdraw cash less often: each bKash cash out costs a fee of about BDT 55.",
        "Build an emergency fund of 3-6 months of essential costs before increasing discretionary spending.",
    ],
    budget_suggestions=[
        {"category": c, "suggested_monthly_budget": float(v),
         "rationale": f"Recent average {bdt(cats['monthly_avg'].get(c, 0))}/month."}
        for c, v in budget_plan.items()
    ],
)
demo = {"source": "Pre-generated demo data (not from a live Gemini call)", "model": "demo data",
        "currency": "BDT", "categories": categories, "insights": insights.model_dump()}
(ROOT / "samples" / "sample_analysis.json").write_text(json.dumps(demo, indent=1, ensure_ascii=False))
print(f"{len(rows)} rows, {len(categories)} unique descriptions -> {csv_path.name}, sample_analysis.json")
print({kk: round(v) if isinstance(v, float) else v for kk, v in k.items()})
print(unu[["id", "merchant", "amount", "rule"]].to_string())
print(rec[["merchant", "typical_amount", "frequency"]].to_string())
