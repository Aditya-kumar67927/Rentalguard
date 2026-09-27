"""Text helpers: cleaning scraped descriptions, normalisation and PII redaction."""
from __future__ import annotations

import re
import unicodedata

_READ_MORE_RE = re.compile(r"\.\.\.\s*read more", re.I)
_VIEW_LESS_RE = re.compile(r"\s*-\s*view less\s*$", re.I)
_PREFIX_RE = re.compile(r"^\s*description\s*:\s*", re.I)
_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9₹ ]+")

# Indian mobile numbers (optionally +91 / 0 prefixed, spaces or dashes allowed)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?|0)?[6-9]\d{2}[\s-]?\d{3}[\s-]?\d{4}(?!\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def clean_scraped_description(text: str | None) -> str:
    """Remove 99acres UI artefacts ('Description :', '... read more', '- view less').

    The scraper captured the collapsed and expanded text together, so the
    '... read more' marker sits in the middle of a word; deleting it restores
    the original sentence.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    text = _PREFIX_RE.sub("", text)
    text = _READ_MORE_RE.sub("", text)
    text = _VIEW_LESS_RE.sub("", text)
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    text = text.replace("�", " ")
    return _WS_RE.sub(" ", text).strip()


def normalize_text(text: str | None) -> str:
    """lowercase -> strip punctuation -> collapse whitespace (duplicate pipeline)."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text)).lower()
    text = _NON_ALNUM_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def redact_contacts(text: str | None) -> str:
    """Replace phone numbers and e-mail addresses so they are never displayed."""
    if not text:
        return ""
    text = EMAIL_RE.sub("[email hidden]", text)
    return PHONE_RE.sub("[phone hidden]", text)


def extract_contacts(text: str | None) -> list[str]:
    """Return raw phone/e-mail identifiers found in text (for hashing only)."""
    if not text:
        return []
    phones = [re.sub(r"\D", "", p)[-10:] for p in PHONE_RE.findall(text)]
    emails = [e.lower() for e in EMAIL_RE.findall(text)]
    return phones + emails
