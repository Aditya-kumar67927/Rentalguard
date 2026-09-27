"""Duplicate / near-duplicate listing detection.

Pipeline for every description::

    raw text -> lowercase -> strip punctuation -> collapse whitespace
             -> (a) SHA-1 of normalised text      -> exact-duplicate hash map, O(1)
             -> (b) word 3-gram shingles -> MinHash signature -> LSH band buckets
             -> (c) TF-IDF (word 1-2 grams) vector -> cosine similarity

Why LSH?  Comparing a new listing against all n stored listings is O(n) per
query, and finding all duplicate pairs in a corpus is O(n^2) comparisons.
MinHash LSH (banding) turns this into an inverted-index lookup: each document
is hashed into ``b`` buckets and only documents sharing at least one bucket
become *candidates*; the exact TF-IDF cosine is then computed only for those
candidates. With b=32 bands of r=4 rows the probability that two documents
with Jaccard similarity J become candidates is ``1 - (1 - J^4)^32``
(≈0.87 at J=0.5, ≈0.99 at J=0.6, ≈0.23 at J=0.3).

See docs/architecture.md for complexity analysis and scripts/benchmark_duplicates.py
for a measured comparison against the brute-force approach.
"""
from __future__ import annotations

import hashlib
import zlib
from collections import defaultdict
from typing import Any

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer

from app.utils.text import normalize_text

MERSENNE_PRIME = (1 << 61) - 1
MAX_HASH = (1 << 32) - 1

DUPLICATE_THRESHOLD = 0.90      # "Possible duplicate"
SIMILAR_THRESHOLD = 0.75        # "Very similar wording"
REPORT_THRESHOLD = 0.50         # minimum similarity returned by similar()
PRICE_CONFLICT_RATIO = 0.30     # >30% rent difference between near-identical texts


def shingles(text: str, k: int = 3) -> set[int]:
    """Set of 32-bit hashes of word k-grams (a set removes repeated shingles)."""
    words = text.split()
    if len(words) < k:
        return {zlib.crc32(text.encode())} if text else set()
    return {zlib.crc32(" ".join(words[i:i + k]).encode()) for i in range(len(words) - k + 1)}


class MinHashLSH:
    def __init__(self, num_perm: int = 128, bands: int = 32, seed: int = 42):
        if num_perm % bands:
            raise ValueError("num_perm must be divisible by bands")
        self.num_perm, self.bands, self.rows = num_perm, bands, num_perm // bands
        rng = np.random.default_rng(seed)
        # Coefficients < 2^32 keep a*x + b below 2^64 (no uint64 overflow) for 32-bit shingles
        self.a = rng.integers(1, MAX_HASH, num_perm, dtype=np.uint64)
        self.b = rng.integers(0, MAX_HASH, num_perm, dtype=np.uint64)
        # One inverted index (hash map: band-hash -> doc ids) per band
        self.buckets: list[dict[bytes, list[int]]] = [defaultdict(list) for _ in range(bands)]

    def signature(self, shingle_set: set[int]) -> np.ndarray:
        if not shingle_set:
            return np.full(self.num_perm, MAX_HASH, dtype=np.uint64)
        x = np.fromiter(shingle_set, dtype=np.uint64)[:, None]
        # (a*x + b) mod p mod 2^32, vectorised over all permutations; take min per column
        hv = ((x * self.a + self.b) % MERSENNE_PRIME) & MAX_HASH
        return hv.min(axis=0)

    def _band_keys(self, sig: np.ndarray):
        for i in range(self.bands):
            yield i, sig[i * self.rows:(i + 1) * self.rows].tobytes()

    def insert(self, doc_id: int, sig: np.ndarray) -> None:
        for i, key in self._band_keys(sig):
            self.buckets[i][key].append(doc_id)

    def candidates(self, sig: np.ndarray) -> set[int]:
        found: set[int] = set()
        for i, key in self._band_keys(sig):
            found.update(self.buckets[i].get(key, ()))
        return found


class DuplicateDetector:
    """Stores reference listings and answers "which stored listings look like this one?"."""

    def __init__(self, num_perm: int = 128, bands: int = 32):
        self.lsh = MinHashLSH(num_perm, bands)
        self.vectorizer: TfidfVectorizer | None = None
        self._base_matrix: sparse.csr_matrix | None = None
        self._extra_rows: list[sparse.csr_matrix] = []
        self.meta: list[dict[str, Any]] = []          # position -> listing metadata
        self.id_to_pos: dict[str, int] = {}             # hash map: listing id -> position
        self.exact: dict[str, list[int]] = defaultdict(list)  # hash map: text digest -> positions

    # ------------------------------------------------------------------
    @staticmethod
    def digest(norm_text: str) -> str:
        return hashlib.sha1(norm_text.encode()).hexdigest()

    def fit(self, texts: list[str], metas: list[dict[str, Any]]) -> "DuplicateDetector":
        norm = [normalize_text(t) for t in texts]
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1,
                                          max_features=60000, dtype=np.float32)
        self._base_matrix = self.vectorizer.fit_transform(norm).tocsr()
        self._extra_rows = []
        self.meta, self.id_to_pos = [], {}
        self.exact = defaultdict(list)
        for pos, (t, m) in enumerate(zip(norm, metas)):
            self._register(pos, t, m)
        return self

    def _register(self, pos: int, norm_text: str, meta: dict[str, Any]) -> None:
        self.meta.append(meta)
        self.id_to_pos[str(meta["id"])] = pos
        if norm_text:
            self.exact[self.digest(norm_text)].append(pos)
            self.lsh.insert(pos, self.lsh.signature(shingles(norm_text)))

    def add(self, text: str, meta: dict[str, Any]) -> None:
        """Incrementally index a new listing (vocabulary stays fixed)."""
        if self.vectorizer is None:
            raise RuntimeError("DuplicateDetector must be fitted before add()")
        if str(meta["id"]) in self.id_to_pos:
            return
        norm = normalize_text(text)
        self._extra_rows.append(self.vectorizer.transform([norm]).tocsr())
        self._register(len(self.meta), norm, meta)

    def __len__(self) -> int:
        return len(self.meta)

    def _row(self, pos: int) -> sparse.csr_matrix:
        base_n = self._base_matrix.shape[0]
        return self._base_matrix[pos] if pos < base_n else self._extra_rows[pos - base_n]

    def _rows(self, positions: list[int]) -> sparse.csr_matrix:
        return sparse.vstack([self._row(p) for p in positions]).tocsr()

    # ------------------------------------------------------------------
    def similar(self, text: str, top_k: int = 5, exclude_id: str | None = None,
                min_similarity: float = REPORT_THRESHOLD) -> list[dict[str, Any]]:
        """Top-k stored listings by cosine similarity among LSH/exact candidates."""
        if self.vectorizer is None or not text:
            return []
        norm = normalize_text(text)
        if not norm:
            return []
        cands = set(self.exact.get(self.digest(norm), []))
        cands |= self.lsh.candidates(self.lsh.signature(shingles(norm)))
        if exclude_id is not None and str(exclude_id) in self.id_to_pos:
            cands.discard(self.id_to_pos[str(exclude_id)])
        if not cands:
            return []
        positions = sorted(cands)
        q = self.vectorizer.transform([norm])
        sims = (self._rows(positions) @ q.T).toarray().ravel()   # rows are L2-normalised -> cosine
        order = np.argsort(-sims)[:top_k]
        return [{"similarity": round(float(sims[i]), 4), **self.meta[positions[i]]}
                for i in order if sims[i] >= min_similarity]

    def similar_bruteforce(self, text: str, top_k: int = 5) -> list[tuple[int, float]]:
        """O(n) reference implementation used by tests/benchmarks to measure LSH recall."""
        norm = normalize_text(text)
        q = self.vectorizer.transform([norm])
        full = sparse.vstack([self._base_matrix, *self._extra_rows]).tocsr() if self._extra_rows else self._base_matrix
        sims = (full @ q.T).toarray().ravel()
        order = np.argsort(-sims)[:top_k]
        return [(int(i), float(sims[i])) for i in order]

    # ------------------------------------------------------------------
    def analyze(self, listing: dict[str, Any], exclude_id: str | None = None) -> dict[str, Any]:
        text = listing.get("description") or ""
        if len(text.split()) < 8:
            return {"available": False, "max_similarity": 0.0, "matches": [], "level": "NOT_APPLICABLE",
                    "possible_duplicate": False, "conflicting_duplicate": False,
                    "explanation": "Description too short for duplicate analysis."}
        matches = self.similar(text, top_k=5, exclude_id=exclude_id)
        best = matches[0] if matches else None
        max_sim = best["similarity"] if best else 0.0
        conflicts: list[str] = []
        if best and max_sim >= DUPLICATE_THRESHOLD:
            rent = listing.get("rent")
            for m in matches:
                if m["similarity"] < DUPLICATE_THRESHOLD:
                    break
                if rent and m.get("rent") and abs(m["rent"] - rent) / max(m["rent"], rent) > PRICE_CONFLICT_RATIO:
                    conflicts.append(f"near-identical text listed at ₹{m['rent']:,.0f} (vs ₹{rent:,.0f})")
                # Compare zones, not localities: brokers legitimately reuse text for
                # neighbouring localities (e.g. "Wadala" vs "Wadala East").
                zone = listing.get("_zone")
                if zone and zone != "Unknown" and m.get("zone") not in (None, "Unknown", zone):
                    conflicts.append(f"near-identical text listed in a different zone ({m.get('locality')}, {m['zone']})")
            conflicts = sorted(set(conflicts))[:3]

        if max_sim >= DUPLICATE_THRESHOLD:
            level = "POSSIBLE_DUPLICATE"
            msg = (f"Description is {max_sim:.0%} similar to an existing listing"
                   + (f"; {conflicts[0]}." if conflicts else " with consistent details (likely a repost)."))
        elif max_sim >= SIMILAR_THRESHOLD:
            level = "SIMILAR"
            msg = f"Wording is {max_sim:.0%} similar to another listing (common for broker templates)."
        else:
            level = "UNIQUE"
            msg = "No closely matching listing found."
        public = [{k: m.get(k) for k in ("id", "similarity", "locality", "zone", "bhk", "rent", "source")} for m in matches]
        return {"available": True, "max_similarity": round(max_sim, 4), "level": level,
                "possible_duplicate": max_sim >= DUPLICATE_THRESHOLD,
                "conflicting_duplicate": bool(conflicts), "conflicts": conflicts,
                "matches": public, "explanation": msg}
