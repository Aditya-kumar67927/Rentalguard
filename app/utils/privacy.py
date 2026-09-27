"""Pseudonymisation of contact identifiers.

Phone numbers, e-mails and dealer names are never stored or displayed in
clear text. They are normalised and hashed with a salted SHA-256; only the
hash is persisted. The same salt is used when cleaning the dataset and at
runtime so that a contact typed by a user can be matched against the
dataset's (hashed) dealers.
"""
from __future__ import annotations

import hashlib
import os
import re

DEFAULT_SALT = "rentalguard-dataset-v1"


def normalize_contact(value: str) -> str:
    v = str(value).strip().lower()
    digits = re.sub(r"\D", "", v)
    if "@" not in v and len(digits) >= 10 and len(digits) >= len(re.sub(r"\s", "", v)) - 3:
        return digits[-10:]             # phone number: keep the 10-digit subscriber number
    return re.sub(r"\s+", " ", v)


def hash_contact(value, salt: str | None = None) -> str | None:
    if value is None or (isinstance(value, float) and value != value):
        return None
    norm = normalize_contact(value)
    if not norm:
        return None
    salt = salt or os.environ.get("RG_DATASET_SALT", DEFAULT_SALT)
    return hashlib.sha256(f"{salt}:{norm}".encode()).hexdigest()[:16]
