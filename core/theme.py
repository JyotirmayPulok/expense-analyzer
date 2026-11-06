"""Shared colours (app + PDF) and currency settings."""

CURRENCIES = {  # label -> (symbol for the UI, code for the PDF)
    "BDT (৳)": ("৳", "BDT"),
    "USD ($)": ("$", "USD"),
    "EUR (€)": ("€", "EUR"),
    "GBP (£)": ("£", "GBP"),
    "INR (₹)": ("₹", "INR"),
}

INK = "#0B3B2E"       # deep forest green
EMERALD = "#059669"
MINT = "#D1FAE5"
GOLD = "#D97706"
CORAL = "#E11D48"
MUTED = "#64748B"

CATEGORY_COLORS = {
    "Rent & Housing": "#0F766E", "Groceries": "#16A34A", "Food & Dining": "#F59E0B", "Transport": "#0EA5E9",
    "Shopping": "#DB2777", "Bills & Utilities": "#7C3AED", "Mobile & Internet": "#6366F1", "Subscriptions": "#E11D48",
    "Health": "#14B8A6", "Education": "#84CC16", "Entertainment": "#F97316", "Travel": "#06B6D4",
    "Transfers Out": "#A16207", "Cash Withdrawal": "#78716C", "Fees & Charges": "#9F1239",
    "Savings & Investments": "#065F46", "Salary & Income": "#059669", "Transfers In": "#34D399", "Other": "#94A3B8",
}


def money(x: float, symbol: str, decimals: int = 0) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}{symbol}{abs(x):,.{decimals}f}" if len(symbol) == 1 else f"{sign}{symbol} {abs(x):,.{decimals}f}"
