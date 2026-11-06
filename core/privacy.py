"""Mask personal identifiers before any text leaves the machine."""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# Card numbers: 13-19 digits with optional spaces/dashes, or already partly masked (e.g. 4321-XXXX-XXXX-1234).
_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b|\b\d{4}[ -]?(?:[X*x]{4}[ -]?){1,3}\d{2,4}\b|\b[X*x]{4,}[ -]?\d{3,4}\b")
# Bangladeshi mobile numbers (+880 1XXXXXXXXX / 01XXXXXXXXX) and other international numbers.
_PHONE = re.compile(r"(?<!\d)(?:\+?88)?0?1[3-9]\d{2}[ -]?\d{6}(?!\d)|\+\d{1,3}[ -]?\d{3,4}[ -]?\d{3,4}[ -]?\d{0,4}")
# Account numbers and long references: 7+ digits, or "A/C" style labels followed by digits.
_ACCOUNT = re.compile(r"(?i)\b(?:a/?c|acc(?:ount)?|acct)\.?\s*(?:no\.?|number|#)?\s*[:#-]?\s*[\dX*-]{4,}|\b\d{7,}\b")
# Mixed letter+digit tokens of 8+ characters (transaction IDs such as TrxID 9F3K2L1M8A).
_REF = re.compile(r"\b(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{8,}\b")
_SPACES = re.compile(r"\s+")


def mask_text(text: str) -> str:
    """Replace emails, card, phone, account numbers and long reference IDs with placeholders."""
    if not text:
        return ""
    s = str(text)
    s = _EMAIL.sub("[EMAIL]", s)
    s = _PHONE.sub("[PHONE]", s)
    s = _CARD.sub("[CARD]", s)
    s = _ACCOUNT.sub("[ACCOUNT]", s)
    s = _REF.sub("[REF]", s)
    return _SPACES.sub(" ", s).strip()


def normalize_description(text: str) -> str:
    """Masked + lower-cased key used to deduplicate descriptions (drops masked IDs and digits)."""
    s = mask_text(text).lower()
    s = re.sub(r"\[(?:email|phone|card|account|ref)\]", " ", s)
    s = re.sub(r"\b(?:trx\s?id|txn\s?id|ref(?:erence)?|no)\b\.?", " ", s)
    s = re.sub(r"\d+", " ", s)
    s = re.sub(r"[^a-z&ঀ-৿ ]+", " ", s)
    return _SPACES.sub(" ", s).strip() or "unknown"
