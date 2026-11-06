"""All numeric work, done locally with pandas (nothing here calls an API)."""

from __future__ import annotations

import pandas as pd

from .schema import INCOME_CATEGORIES

NOT_SPENDING = {"Savings & Investments"}
_DISCRETIONARY = {"Food & Dining", "Groceries", "Transport", "Shopping", "Health", "Transfers Out", "Entertainment"}  # money moved to savings is not counted as an expense

# Small offline fallback used before (or instead of) the Gemini categorisation.
_RULES = [
    ("Salary & Income", ("salary", "payroll", "bonus", "honorarium", "interest credit")),
    ("Rent & Housing", ("rent", "house", "flat", "landlord", "service charge")),
    ("Bills & Utilities", ("desco", "dpdc", "electric", "titas", "gas bill", "wasa", "water", "utility", "bill pay")),
    ("Mobile & Internet", ("recharge", "topup", "top-up", "internet", "broadband", "data pack", "isp")),
    ("Subscriptions", ("netflix", "spotify", "stream", "subscription", "premium", "cloud", "gym", "membership")),
    ("Groceries", ("grocery", "super shop", "supershop", "bazar", "basket", "mart")),
    ("Food & Dining", ("restaurant", "cafe", "coffee", "food", "pizza", "burger", "biryani", "kacchi", "tea")),
    ("Transport", ("ride", "uber", "pathao", "fuel", "petrol", "cng", "bus", "metro", "parking")),
    ("Health", ("pharma", "pharmacy", "hospital", "clinic", "diagnostic", "doctor", "medic")),
    ("Education", ("school", "tuition", "course", "university", "college", "book")),
    ("Entertainment", ("cinema", "movie", "game", "concert", "ticket")),
    ("Travel", ("air", "hotel", "resort", "travel", "tour", "bus ticket")),
    ("Cash Withdrawal", ("atm", "cash out", "cashout", "withdrawal")),
    ("Fees & Charges", ("fee", "charge", "vat", "excise", "commission")),
    ("Savings & Investments", ("dps", "fdr", "savings transfer", "sanchaypatra", "deposit scheme")),
    ("Shopping", ("shop", "store", "fashion", "online", "daraz", "electronics", "mall")),
]


def rule_category(key: str, amount_sign: int) -> str:
    for cat, words in _RULES:
        if any(w in key for w in words):
            if amount_sign > 0 and cat not in INCOME_CATEGORIES:
                break
            return cat
    if amount_sign > 0:
        return "Transfers In"
    if "send money" in key or "transfer" in key or "fund" in key:
        return "Transfers Out"
    return "Other"


def default_merchant(key: str) -> str:
    stop = {"payment", "purchase", "pos", "to", "from", "at", "for", "via", "txn", "trxid", "ref", "id", "no", "debit",
            "credit", "card", "the"}
    words = [w for w in key.split() if w not in stop]
    return " ".join(words[:3]).title() or "Unknown"


def apply_categories(tx: pd.DataFrame, by_key: dict[str, tuple[str, str]] | None = None) -> pd.DataFrame:
    """Add `merchant` and `category`. `by_key` maps description key -> (merchant, category) from Gemini."""
    tx = tx.copy()
    by_key = by_key or {}
    merchants, cats = [], []
    for key, amt in zip(tx["key"], tx["amount"]):
        if key in by_key:
            m, c = by_key[key]
            if amt > 0 and c not in INCOME_CATEGORIES and c != "Other":
                c = "Transfers In"  # refunds / reversals of spending categories still count as money in
        else:
            m, c = default_merchant(key), rule_category(key, 1 if amt > 0 else -1)
        merchants.append(m)
        cats.append(c)
    tx["merchant"] = merchants
    tx["category"] = cats
    return tx


def is_expense(tx: pd.DataFrame) -> pd.Series:
    return (tx["amount"] < 0) & ~tx["category"].isin(NOT_SPENDING)


def kpis(tx: pd.DataFrame) -> dict:
    income = float(tx.loc[tx["amount"] > 0, "amount"].sum())
    expenses = float(-tx.loc[is_expense(tx), "amount"].sum())
    saved = float(-tx.loc[(tx["amount"] < 0) & tx["category"].isin(NOT_SPENDING), "amount"].sum())
    net = income - expenses
    months = max(tx["month"].nunique(), 1)
    return {
        "income": income, "expenses": expenses, "net": net, "moved_to_savings": saved,
        "savings_rate": (net / income * 100) if income else 0.0,
        "months": months, "avg_monthly_expense": expenses / months, "transactions": int(len(tx)),
        "start": tx["date"].min().strftime("%d %b %Y"), "end": tx["date"].max().strftime("%d %b %Y"),
    }


def category_totals(tx: pd.DataFrame) -> pd.DataFrame:
    exp = tx[is_expense(tx)]
    months = max(tx["month"].nunique(), 1)
    out = (exp.groupby("category")["amount"].agg(total="sum", count="size").reset_index())
    out["total"] = -out["total"]
    out["monthly_avg"] = out["total"] / months
    out["share"] = out["total"] / out["total"].sum() * 100 if len(out) else 0
    return out.sort_values("total", ascending=False).reset_index(drop=True)


def monthly(tx: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for m, g in tx.groupby("month"):
        inc = g.loc[g["amount"] > 0, "amount"].sum()
        exp = -g.loc[is_expense(g), "amount"].sum()
        rows.append({"month": m, "income": float(inc), "expenses": float(exp), "net": float(inc - exp)})
    return pd.DataFrame(rows, columns=["month", "income", "expenses", "net"])


def top_merchants(tx: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    exp = tx[is_expense(tx)]
    out = exp.groupby("merchant")["amount"].agg(total="sum", count="size").reset_index()
    out["total"] = -out["total"]
    return out.sort_values("total", ascending=False).head(n).reset_index(drop=True)


def recurring(tx: pd.DataFrame) -> pd.DataFrame:
    """Expense merchants paid in 2+ different months with a steady amount."""
    exp = tx[tx["amount"] < 0]
    rows = []
    for merchant, g in exp.groupby("merchant"):
        if g["month"].nunique() < 2 or len(g) < 2:
            continue
        amt = -g["amount"]
        cv = amt.std(ddof=0) / amt.mean() if amt.mean() else 1
        # Bills may vary a little; everyday spending must be near-identical to count as recurring.
        if cv > (0.02 if g["category"].mode().iat[0] in _DISCRETIONARY else 0.15):
            continue
        gap = g["date"].sort_values().diff().dt.days.dropna().median()
        freq = "weekly" if gap <= 10 else "monthly" if 20 <= gap <= 40 else "quarterly" if 80 <= gap <= 100 else "irregular"
        rows.append({"merchant": merchant, "category": g["category"].mode().iat[0], "typical_amount": float(amt.median()),
                     "frequency": freq, "payments": int(len(g)), "last_paid": g["date"].max().strftime("%d %b %Y")})
    cols = ["merchant", "category", "typical_amount", "frequency", "payments", "last_paid"]
    return pd.DataFrame(rows, columns=cols).sort_values("typical_amount", ascending=False).reset_index(drop=True)


def unusual(tx: pd.DataFrame, limit: int = 12) -> pd.DataFrame:
    """Rule-based candidates: far above the category's usual size, very large overall, or duplicate-looking."""
    exp = tx[tx["amount"] < 0].copy()
    if exp.empty:
        return exp.assign(rule="")
    exp["spend"] = -exp["amount"]
    # Compare with the merchant's own usual size when it has history, otherwise with its category.
    m_med = exp.groupby("merchant")["spend"].transform("median")
    m_cnt = exp.groupby("merchant")["spend"].transform("size")
    med = m_med.where(m_cnt >= 3, exp.groupby("category")["spend"].transform("median"))
    cnt = m_cnt.where(m_cnt >= 3, exp.groupby("category")["spend"].transform("size"))
    overall = exp["spend"].quantile(0.97)
    dup = exp.duplicated(subset=["date", "merchant", "spend"], keep=False)
    steady = set(recurring(tx)["merchant"])  # expected bills (rent etc.) are not "unusual"
    rules = []
    for r, m, c, d in zip(exp.itertuples(), med, cnt, dup):
        if d:
            rules.append("Same merchant, amount and day appears more than once")
        elif r.merchant in steady:
            rules.append("")
        elif c >= 3 and r.spend >= 3 * m and r.spend > 500:
            rules.append(f"{r.spend / m:.1f}x the usual {r.category} payment")
        elif r.spend >= overall and r.spend > 5000:
            rules.append("Among the largest payments in the statement")
        else:
            rules.append("")
    exp["rule"] = rules
    out = exp[exp["rule"] != ""].sort_values("spend", ascending=False).head(limit)
    return out[["id", "date", "merchant", "category", "amount", "masked", "rule"]].reset_index(drop=True)


def budget_status(tx: pd.DataFrame, budgets: dict[str, float]) -> pd.DataFrame:
    """Average monthly spend per category vs the user's monthly budget."""
    cats = category_totals(tx).set_index("category")
    rows = []
    for cat, budget in budgets.items():
        spent = float(cats["monthly_avg"].get(cat, 0.0)) if len(cats) else 0.0
        rows.append({"category": cat, "budget": float(budget), "avg_monthly_spend": spent,
                     "difference": float(budget) - spent,
                     "used_pct": (spent / budget * 100) if budget else 0.0})
    return pd.DataFrame(rows, columns=["category", "budget", "avg_monthly_spend", "difference", "used_pct"])


def insights_payload(tx: pd.DataFrame, top_n: int = 12) -> dict:
    """Aggregated, masked numbers sent to Gemini for insights (no raw descriptions, no personal IDs)."""
    k = kpis(tx)
    cats = category_totals(tx)
    rec = recurring(tx)
    unu = unusual(tx)
    dow = tx[is_expense(tx)].assign(day=lambda d: d["date"].dt.day_name()).groupby("day")["amount"].sum().abs()
    return {
        "period": f"{k['start']} to {k['end']} ({k['months']} months, {k['transactions']} transactions)",
        "totals": {key: round(v, 2) for key, v in k.items() if isinstance(v, float)},
        "monthly": monthly(tx).round(2).to_dict("records"),
        "categories": cats.round(2).to_dict("records"),
        "top_merchants": top_merchants(tx, top_n).round(2).to_dict("records"),
        "spend_by_weekday": {d: round(float(v), 2) for d, v in dow.items()},
        "recurring_candidates": rec.round(2).to_dict("records"),
        "unusual_candidates": [
            {"txn_id": int(r.id), "date": r.date.strftime("%Y-%m-%d"), "merchant": r.merchant, "category": r.category,
             "amount": round(float(r.amount), 2), "rule": r.rule} for r in unu.itertuples()
        ],
    }
