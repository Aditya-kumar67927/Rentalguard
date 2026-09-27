"""Search helpers that demonstrate (and need) classic data structures.

* ``LocalityIndex`` - sorted array + binary search (``bisect``) for prefix
  autocomplete: O(log n + m) per query instead of an O(n) scan.
* ``top_k`` - bounded min-heap for "k highest-priority items" over a stream:
  O(n log k) time, O(k) memory, without materialising or fully sorting n rows.
"""
from __future__ import annotations

import bisect
import heapq
from typing import Any, Callable, Iterable, TypeVar

T = TypeVar("T")


class LocalityIndex:
    def __init__(self, entries: dict[str, dict[str, Any]]):
        # entries: key -> {"display", "zone", "n"}
        self._keys = sorted(entries)          # sorted once, O(n log n)
        self._entries = entries

    @classmethod
    def from_price_analyzer(cls, price) -> "LocalityIndex":
        if price is None:
            return cls({})
        return cls({k: {"display": v["display"], "zone": v["zone"], "n": v["n"]}
                    for k, v in price.localities.items()})

    def __len__(self) -> int:
        return len(self._keys)

    def prefix(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        from app.utils.locality import locality_key
        q = locality_key(query) if query else ""
        if not q:
            return []
        lo = bisect.bisect_left(self._keys, q)
        hi = bisect.bisect_right(self._keys, q + "￿")   # end of the prefix range
        hits = self._keys[lo:hi]
        # Rank the matches by popularity (listing count), most common first
        best = heapq.nlargest(limit, hits, key=lambda k: self._entries[k]["n"])
        return [{"key": k, **self._entries[k]} for k in best]


def top_k(items: Iterable[T], k: int, key: Callable[[T], Any]) -> list[T]:
    """Return the k items with the largest key, highest first, using a size-k min-heap."""
    if k <= 0:
        return []
    heap: list[tuple[Any, int, T]] = []
    for i, item in enumerate(items):
        entry = (key(item), -i, item)     # -i: stable tie-break (earlier item wins)
        if len(heap) < k:
            heapq.heappush(heap, entry)
        elif entry[:2] > heap[0][:2]:
            heapq.heapreplace(heap, entry)
    return [e[2] for e in sorted(heap, key=lambda e: e[:2], reverse=True)]
