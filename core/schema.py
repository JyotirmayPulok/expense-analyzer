"""Structured output schemas returned by Gemini (Pydantic models)."""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field

CATEGORIES = [
    "Salary & Income",
    "Transfers In",
    "Food & Dining",
    "Groceries",
    "Transport",
    "Shopping",
    "Bills & Utilities",
    "Mobile & Internet",
    "Rent & Housing",
    "Health",
    "Education",
    "Entertainment",
    "Subscriptions",
    "Travel",
    "Transfers Out",
    "Cash Withdrawal",
    "Fees & Charges",
    "Savings & Investments",
    "Other",
]
INCOME_CATEGORIES = {"Salary & Income", "Transfers In"}

Category = Literal[
    "Salary & Income", "Transfers In", "Food & Dining", "Groceries", "Transport", "Shopping",
    "Bills & Utilities", "Mobile & Internet", "Rent & Housing", "Health", "Education", "Entertainment",
    "Subscriptions", "Travel", "Transfers Out", "Cash Withdrawal", "Fees & Charges",
    "Savings & Investments", "Other",
]


# ---------- request 1: categorisation ----------
class CategorizedItem(BaseModel):
    id: int = Field(description="The id of the description exactly as given in the input")
    merchant: str = Field(description="Short clean merchant / counterparty name, e.g. 'FreshBasket'")
    category: Category


class CategorizationResult(BaseModel):
    items: List[CategorizedItem] = Field(description="Exactly one entry per input id")


# ---------- request 2: insights ----------
class SpendingPattern(BaseModel):
    title: str = Field(description="Short headline, e.g. 'Weekend dining is 40% of food spend'")
    detail: str = Field(description="One or two sentences with the numbers that support it")


class RecurringNote(BaseModel):
    merchant: str
    typical_amount: float = Field(description="Typical amount per payment, positive number")
    frequency: Literal["weekly", "monthly", "quarterly", "irregular"]
    is_subscription: bool = Field(description="True for a cancellable service subscription")
    note: str = Field(description="One sentence: keep, review or cancel, and why")


class UnusualNote(BaseModel):
    txn_id: int = Field(description="Transaction id from the candidate list")
    reason: str = Field(description="Why it stands out, in one sentence")
    severity: Literal["low", "medium", "high"]


class BudgetSuggestion(BaseModel):
    category: Category
    suggested_monthly_budget: float = Field(description="Suggested monthly limit in the statement currency")
    rationale: str = Field(description="One short sentence")


class InsightsResult(BaseModel):
    summary: str = Field(description="3-4 sentence overview of the person's money flow")
    health_score: int = Field(description="0-100 budgeting health score (savings rate, stability, essentials share)")
    spending_patterns: List[SpendingPattern] = Field(description="4-6 patterns")
    recurring_payments: List[RecurringNote]
    unusual_transactions: List[UnusualNote]
    saving_tips: List[str] = Field(description="5-7 practical, general saving tips tied to this data")
    budget_suggestions: List[BudgetSuggestion] = Field(description="One per expense category that has spending")
