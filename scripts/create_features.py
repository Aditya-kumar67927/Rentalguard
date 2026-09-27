"""Build the runtime artifacts from the cleaned dataset.

Outputs (ml_models/):
  price_baselines.json   peer-group rent statistics, locality index, deposit norms
  contact_stats.json     hashed contact -> listing / locality counts
  duplicate_index.joblib TF-IDF + MinHash-LSH index of dataset descriptions

Usage: python scripts/create_features.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ml.features import build_contact_stats, build_price_baselines  # noqa: E402
from app.ml.model_loader import CONTACT_STATS, DUPLICATE_INDEX, PRICE_BASELINES  # noqa: E402
from app.services.duplicate_detector import DuplicateDetector  # noqa: E402

DATA = ROOT / "data" / "processed" / "listings_clean.csv"
OUT = ROOT / "ml_models"


def dataset_meta(df: pd.DataFrame) -> list[dict]:
    return [{"id": r.listing_id, "rent": float(r.rent), "bhk": float(r.bhk), "locality": r.locality,
             "locality_group": r.locality_group, "zone": r.zone, "source": "dataset"}
            for r in df.itertuples()]


def main() -> None:
    if not DATA.exists():
        sys.exit("Processed data missing. Run: python scripts/clean_data.py")
    OUT.mkdir(exist_ok=True)
    df = pd.read_csv(DATA)

    t = time.time()
    baselines = build_price_baselines(df)
    (OUT / PRICE_BASELINES).write_text(json.dumps(baselines), encoding="utf-8")
    sizes = {k: len(v) for k, v in baselines["levels"].items()}
    print(f"[features] price baselines: {sizes} peer groups, {len(baselines['localities'])} localities "
          f"({time.time() - t:.1f}s)")

    contacts = build_contact_stats(df)
    (OUT / CONTACT_STATS).write_text(json.dumps(contacts), encoding="utf-8")
    print(f"[features] contact stats: {len(contacts)} hashed contacts")

    t = time.time()
    detector = DuplicateDetector().fit(df["description"].fillna("").tolist(), dataset_meta(df))
    joblib.dump(detector, OUT / DUPLICATE_INDEX, compress=3)
    print(f"[features] duplicate index: {len(detector)} documents, "
          f"vocab {len(detector.vectorizer.vocabulary_)} ({time.time() - t:.1f}s)")


if __name__ == "__main__":
    main()
