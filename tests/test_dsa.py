"""Tests for the data-structure helpers used across the app."""
import heapq
import random

import pytest

from app.security import SlidingWindowLimiter
from app.utils.locality import resolve_group
from app.utils.search import LocalityIndex, top_k


@pytest.mark.parametrize("k", [0, 1, 5, 50])
def test_top_k_matches_full_sort(k):
    rng = random.Random(1)
    items = [rng.randint(0, 100) for _ in range(200)]
    assert top_k(items, k, key=lambda x: x) == sorted(items, reverse=True)[:k]
    assert top_k(items, k, key=lambda x: x) == heapq.nlargest(k, items)


def test_top_k_is_stable_for_ties():
    items = [("a", 5), ("b", 5), ("c", 1)]
    assert [i[0] for i in top_k(items, 2, key=lambda t: t[1])] == ["a", "b"]


def test_locality_prefix_search():
    idx = LocalityIndex({"andheri west": {"display": "Andheri West", "zone": "A", "n": 50},
                         "andheri east": {"display": "Andheri East", "zone": "A", "n": 70},
                         "powai": {"display": "Powai", "zone": "C", "n": 90}})
    res = idx.prefix("Andh")
    assert [r["display"] for r in res] == ["Andheri East", "Andheri West"]   # ranked by count
    assert idx.prefix("zzz") == []
    assert [r["display"] for r in idx.prefix("andheri-w")] == ["Andheri West"]


def test_sliding_window_limiter():
    lim = SlidingWindowLimiter(max_events=3, window_seconds=60)
    for _ in range(3):
        assert not lim.blocked("k")
        lim.hit("k")
    assert lim.blocked("k")
    assert not lim.blocked("other")
    lim.reset("k")
    assert not lim.blocked("k")


def test_resolve_group_longest_match_and_generic_guard():
    groups = {"powai", "chembur", "chembur east", "sector 10", "kharghar"}
    assert resolve_group("hiranandani gardens powai", groups) == "powai"
    assert resolve_group("chembur east camp", groups) == "chembur east"
    assert resolve_group("sector 10 kharghar", groups) == "kharghar"
    assert resolve_group("unknown place", groups) == "unknown place"
