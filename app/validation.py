"""Input validation for the JSON API (whitelist-based, no external deps)."""
from __future__ import annotations

import re
from typing import Any

from app.ml.preprocessing import FURNISHING_VALUES, PROPERTY_TYPES, normalize_furnishing, normalize_property_type

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[A-Za-z]{2,}$")
MAX_DESCRIPTION = 5000


class ValidationError(Exception):
    def __init__(self, errors: dict[str, str]):
        super().__init__("validation failed")
        self.errors = errors


def _number(value: Any, field: str, errors: dict, *, lo: float, hi: float, required: bool,
            integer: bool = False) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            errors[field] = "This field is required."
        return None
    if isinstance(value, bool):
        errors[field] = "Must be a number."
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("₹", "").strip()
    try:
        num = float(value)
    except (TypeError, ValueError):
        errors[field] = "Must be a number."
        return None
    if num != num or num in (float("inf"), float("-inf")):
        errors[field] = "Must be a finite number."
        return None
    if integer and not num.is_integer():
        errors[field] = "Must be a whole number."
        return None
    if not lo <= num <= hi:
        errors[field] = f"Must be between {lo:,.0f} and {hi:,.0f}."
        return None
    return num


def _string(value: Any, field: str, errors: dict, *, max_len: int, required: bool, min_len: int = 0) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            errors[field] = "This field is required."
        return None
    if not isinstance(value, str):
        errors[field] = "Must be text."
        return None
    value = value.strip()
    if len(value) < min_len:
        errors[field] = f"Must be at least {min_len} characters."
        return None
    if len(value) > max_len:
        errors[field] = f"Must be at most {max_len:,} characters."
        return None
    return value


def validate_listing(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError({"_body": "Expected a JSON object."})
    errors: dict[str, str] = {}
    out: dict[str, Any] = {
        "locality": _string(payload.get("locality"), "locality", errors, max_len=120, required=True, min_len=2),
        "rent": _number(payload.get("rent"), "rent", errors, lo=500, hi=5_000_000, required=True),
        "deposit": _number(payload.get("deposit"), "deposit", errors, lo=0, hi=100_000_000, required=False),
        "bhk": _number(payload.get("bhk"), "bhk", errors, lo=1, hi=10, required=True, integer=True),
        "area_sqft": _number(payload.get("area_sqft"), "area_sqft", errors, lo=100, hi=20_000, required=False),
        "bathrooms": _number(payload.get("bathrooms"), "bathrooms", errors, lo=0, hi=10, required=False, integer=True),
        "description": _string(payload.get("description"), "description", errors, max_len=MAX_DESCRIPTION,
                               required=False) or "",
        "contact": _string(payload.get("contact"), "contact", errors, max_len=100, required=False),
    }
    furnishing = payload.get("furnishing")
    if furnishing not in (None, "") and normalize_furnishing(furnishing) == "unknown" and \
            str(furnishing).lower() != "unknown":
        errors["furnishing"] = f"Must be one of: {', '.join(sorted(FURNISHING_VALUES))}."
    out["furnishing"] = normalize_furnishing(furnishing)
    ptype = payload.get("property_type")
    if ptype not in (None, "") and normalize_property_type(ptype) == "other" and str(ptype).lower() != "other":
        errors["property_type"] = f"Must be one of: {', '.join(sorted(PROPERTY_TYPES))}."
    out["property_type"] = normalize_property_type(ptype)
    if errors:
        raise ValidationError(errors)
    for f in ("rent", "deposit", "bathrooms"):
        if out[f] is not None:
            out[f] = int(round(out[f]))
    if out["deposit"] == 0:
        out["deposit"] = None
    return out


def validate_registration(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValidationError({"_body": "Expected a JSON object."})
    errors: dict[str, str] = {}
    name = _string(payload.get("name"), "name", errors, max_len=80, required=True)
    email = _string(payload.get("email"), "email", errors, max_len=254, required=True)
    password = payload.get("password")
    if email and not EMAIL_RE.match(email):
        errors["email"] = "Enter a valid e-mail address."
    if not isinstance(password, str) or len(password) < 8:
        errors["password"] = "Password must be at least 8 characters."
    elif len(password) > 128:
        errors["password"] = "Password must be at most 128 characters."
    elif password.isdigit() or password.isalpha():
        errors["password"] = "Use a mix of letters and numbers."
    if errors:
        raise ValidationError(errors)
    return {"name": name, "email": email.lower(), "password": password}
