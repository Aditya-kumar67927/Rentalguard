"""Benchmark: all-pairs near-duplicate search, brute force vs MinHash LSH.

Brute force computes every pairwise cosine similarity - n(n-1)/2 comparisons,
O(n^2). LSH only scores pairs that share at least one band bucket.

Outputs docs/benchmark_duplicates.json. Usage:
    python scripts/benchmark_duplicates.py [--threshold 0.9]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ml.model_loader import DUPLICATE_INDEX  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.9)
    args = parser.parse_args()
    det = joblib.load(ROOT / "ml_models" / DUPLICATE_INDEX)
    X = det._base_matrix
    n = X.shape[0]
    thr = args.threshold

    # --- brute force: X @ X.T in row blocks (all n^2 similarities) --------
    t = time.perf_counter()
    brute_pairs: set[tuple[int, int]] = set()
    block = 1000
    for s in range(0, n, block):
        sims = (X[s:s + block] @ X.T).toarray()
        rows, cols = np.nonzero(sims >= thr)
        for r, c in zip(rows + s, cols):
            if r < c:
                brute_pairs.add((int(r), int(c)))
    brute_time = time.perf_counter() - t
    brute_comparisons = n * (n - 1) // 2

    # --- LSH: candidate pairs from shared buckets, then exact cosine ------
    t = time.perf_counter()
    cand: set[tuple[int, int]] = set()
    for band in det.lsh.buckets:
        for ids in band.values():
            if len(ids) < 2:
                continue
            ids = sorted(ids)
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    cand.add((ids[i], ids[j]))
    cand_list = list(cand)
    lsh_pairs: set[tuple[int, int]] = set()
    if cand_list:
        a = np.fromiter((p[0] for p in cand_list), dtype=np.int64)
        b = np.fromiter((p[1] for p in cand_list), dtype=np.int64)
        sims = np.asarray(X[a].multiply(X[b]).sum(axis=1)).ravel()
        lsh_pairs = {cand_list[i] for i in np.nonzero(sims >= thr)[0]}
    lsh_time = time.perf_counter() - t

    recall = len(lsh_pairs & brute_pairs) / len(brute_pairs) if brute_pairs else 1.0
    result = {
        "documents": n, "threshold": thr,
        "bruteforce": {"comparisons": brute_comparisons, "seconds": round(brute_time, 2),
                       "pairs_found": len(brute_pairs)},
        "lsh": {"num_perm": det.lsh.num_perm, "bands": det.lsh.bands, "rows_per_band": det.lsh.rows,
                "candidate_pairs_scored": len(cand), "seconds": round(lsh_time, 2),
                "pairs_found": len(lsh_pairs), "recall_vs_bruteforce": round(recall, 4),
                "comparison_reduction": round(1 - len(cand) / brute_comparisons, 4)},
        "note": "LSH signatures are pre-computed at index-build time (scripts/create_features.py); "
                "the LSH timing covers candidate generation + exact scoring only.",
    }
    out = ROOT / "docs" / "benchmark_duplicates.json"
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
