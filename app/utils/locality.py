"""Locality normalisation shared by the data pipeline and the web app.

The same function must be used offline (cleaning the dataset) and online
(normalising user input) so that "Andheri-West", "andheri (W)" and
"Andheri West" all resolve to the same lookup key: ``"andheri west"``.
"""
from __future__ import annotations

import re

_DIRECTIONS = {
    "w": "west", "west": "west",
    "e": "east", "east": "east",
    "n": "north", "north": "north",
    "s": "south", "south": "south",
}

# Hand-curated aliases for well-known sub-areas / abbreviations. Only
# mappings that are unambiguous are listed; everything else falls back to
# substring matching against the list of known localities.
ALIASES = {
    "bkc": "bandra kurla complex",
    "lokhandwala": "andheri west",
    "lokhandwala complex": "andheri west",
    "pali hill": "bandra west",
    "thakur village": "kandivali east",
    "evershine nagar": "malad west",
    "hiranandani gardens": "powai",
    "hiranandani gardens powai": "powai",
    "raheja vihar": "powai",
    "lower parel west": "lower parel",
    "navi mumbai": "navi mumbai",
    "koperkhairane": "koparkhairane",
    "kopar khairane": "koparkhairane",
    "vashi navi mumbai": "vashi",
}

_PUNCT_RE = re.compile(r"[()\[\]{}.,/\\_\-–—:;'\"]+")
_WS_RE = re.compile(r"\s+")
_SECTOR_RE = re.compile(r"\bsec(?:tor)?\s*[- ]?\s*(\d+[a-z]?)\b")


def locality_key(raw: str | None) -> str:
    """Return a canonical lowercase key for a locality string.

    >>> locality_key("Andheri (West)")
    'andheri west'
    >>> locality_key("andheri-W")
    'andheri west'
    """
    if not raw:
        return ""
    text = str(raw).lower().strip()
    text = _SECTOR_RE.sub(lambda m: f"sector {m.group(1)}", text)
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    # Drop a trailing city suffix such as ", Mumbai"
    text = re.sub(r"\s+mumbai$", "", text) if text != "navi mumbai" else text
    tokens = text.split(" ")
    if len(tokens) > 1 and tokens[-1] in _DIRECTIONS:
        tokens[-1] = _DIRECTIONS[tokens[-1]]
    key = " ".join(tokens)
    return ALIASES.get(key, key)


def display_name(key: str) -> str:
    """Human readable title-case version of a key."""
    return " ".join(w.upper() if w == "bkc" else w.capitalize() for w in key.split(" "))


def resolve_group(key: str, known_groups: set[str]) -> str:
    """Map a (possibly sub-) locality key to the longest known group it contains.

    "hiranandani gardens powai" -> "powai" when "powai" is a known group.
    Longest match wins so that "chembur east" beats "chembur".
    Generic "sector 10"-style n-grams are never used as a group because the
    same sector numbers repeat across Navi Mumbai nodes.

    Complexity: a key of k tokens has O(k^2) contiguous n-grams, each tested
    against a hash set in O(1) average -> O(k^2), independent of the number
    of known groups.
    """
    if not key:
        return ""
    if key in known_groups:
        return key
    tokens = key.split(" ")
    n = len(tokens)
    for length in range(n - 1, 0, -1):  # longest first
        for start in range(0, n - length + 1):
            cand = " ".join(tokens[start:start + length])
            if cand in known_groups and not _GENERIC_RE.match(cand):
                return cand
    return key


_GENERIC_RE = re.compile(r"^(sector|sec|phase|plot|road|nagar|east|west|north|south)(\s+\w+)?$")
