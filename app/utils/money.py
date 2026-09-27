"""Parsing Indian-format money amounts and extracting deposits from free text."""
from __future__ import annotations

import re

_UNIT = {"lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
         "l": 100_000, "k": 1_000, "thousand": 1_000, "cr": 10_000_000, "crore": 10_000_000}

_NUM = r"(\d[\d,\s]*(?:\.\d+)?)"
_UNITS = r"(lakhs?|lacs?|l|k|thousand|crores?|cr)?\b"

# Absolute deposit amount *after* the word deposit: "deposit of rs. 5,00,000"
_DEP_AFTER = re.compile(
    r"deposit\s*(?:amount\s*)?(?:of|is|:|-|\?|=)?\s*(?:rs\.?|inr|₹)?\s*" + _NUM + r"\s*" + _UNITS
    + r"(?!\s*(?:months?|mnths?))", re.I)
# Amount *before* deposit: "1 lakh deposit", "rs 80000 deposit"
_DEP_BEFORE = re.compile(r"(?:rs\.?|₹)?\s*" + _NUM + r"\s*" + _UNITS + r"\s*(?:security\s+)?deposit", re.I)
# Months of rent: "deposit of 6 months rent", "6 months rent as the security deposit"
_DEP_MONTHS_AFTER = re.compile(r"deposit\s*(?:of\s*)?(\d{1,2}(?:\.\d)?)\s*(?:months?|mnths?)", re.I)
_DEP_MONTHS_BEFORE = re.compile(
    r"(\d{1,2}(?:\.\d)?)\s*(?:months?|mnths?)'?s?\s*(?:rent\s*)?(?:as\s*(?:the\s*)?)?(?:security\s*)?deposit", re.I)

_BATH_RE = re.compile(r"(\d)\s*bath(?:room)?s?\b", re.I)


def parse_amount(number: str, unit: str | None = None) -> float | None:
    """'7, 00,000' -> 700000 ; ('1.5', 'lakh') -> 150000 ; '₹35,000' -> 35000."""
    if number is None:
        return None
    cleaned = re.sub(r"[^\d.]", "", str(number))
    if not cleaned or cleaned.count(".") > 1:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if unit:
        unit = unit.lower()
        value *= _UNIT.get(unit, _UNIT.get(unit.rstrip("s"), 1))
    return value


def _plausible(deposit: float | None, rent: float | None) -> bool:
    if deposit is None or deposit <= 0 or deposit > 1e8:
        return False
    if rent and rent > 0:
        return 0.5 * rent <= deposit <= 36 * rent
    return True


def extract_deposit(text: str | None, rent: float | None = None) -> float | None:
    """Best-effort security-deposit extraction; returns None when unsure.

    Candidates outside [0.5x, 36x] monthly rent are rejected as parse noise.
    """
    if not text or "deposit" not in text.lower():
        return None
    if rent:
        for rx in (_DEP_MONTHS_AFTER, _DEP_MONTHS_BEFORE):
            m = rx.search(text)
            if m:
                months = float(m.group(1))
                if 0.5 <= months <= 24:
                    return round(months * rent)
    for rx in (_DEP_AFTER, _DEP_BEFORE):
        for m in rx.finditer(text):
            value = parse_amount(m.group(1), m.group(2))
            if _plausible(value, rent):
                return round(value)
    return None


def extract_bathrooms(text: str | None) -> int | None:
    if not text:
        return None
    m = _BATH_RE.search(text)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 8 else None
    return None
