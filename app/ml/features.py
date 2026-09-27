"""Offline statistics (price baselines, deposit norms, contact counts) and the
runtime risk feature vector.

The baselines are plain dictionaries (hash maps) serialised to JSON so the
web app can look up "median rent for 2 BHK in Andheri West" in O(1).
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

MIN_PEERS = 8
BHK_CAP = 5


def bhk_bucket(bhk: float | int | None) -> int | None:
    if bhk is None or (isinstance(bhk, float) and math.isnan(bhk)):
        return None
    return int(min(max(round(float(bhk)), 1), BHK_CAP))


def _mad_sigma(values: np.ndarray) -> float:
    """Robust standard deviation estimate: 1.4826 * MAD."""
    if len(values) < 2:
        return float("nan")
    med = np.median(values)
    return float(1.4826 * np.median(np.abs(values - med)))


def _group_stats(g: pd.DataFrame) -> dict[str, float]:
    rent = g["rent"].to_numpy(float)
    ppsf = g["rent_per_sqft"].dropna().to_numpy(float)
    stats = {
        "n": int(len(g)),
        "median_rent": float(np.median(rent)),
        "q25_rent": float(np.percentile(rent, 25)),
        "q75_rent": float(np.percentile(rent, 75)),
        "sigma_log_rent": _mad_sigma(np.log(rent)),
    }
    if len(ppsf) >= 3:
        stats.update({
            "median_ppsf": float(np.median(ppsf)),
            "sigma_log_ppsf": _mad_sigma(np.log(ppsf)),
            "median_area": float(g["area_sqft"].median()),
        })
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in stats.items()}


def build_price_baselines(df: pd.DataFrame) -> dict[str, Any]:
    """Peer-group statistics at four levels of geographic granularity."""
    data = df[~df["price_outlier"].astype(bool)].copy()
    data["bhk_b"] = data["bhk"].map(bhk_bucket)

    def level(cols: list[str]) -> dict[str, dict]:
        out = {}
        for keys, g in data.groupby(cols):
            if len(g) < MIN_PEERS:
                continue
            keys = keys if isinstance(keys, tuple) else (keys,)
            out["|".join(str(k) for k in keys)] = _group_stats(g)
        return out

    counts = df["locality_key"].value_counts()
    localities = {}
    for key, g in df.groupby("locality_key"):
        localities[key] = {
            "display": str(g["locality"].iloc[0]),
            "group": str(g["locality_group"].mode().iloc[0]),
            "zone": str(g["zone"].mode().iloc[0]),
            "n": int(counts[key]),
        }
    group_zone = df.groupby("locality_group")["zone"].agg(lambda s: s.mode().iloc[0]).to_dict()
    group_counts = df["locality_group"].value_counts()

    return {
        "version": 1,
        "min_peers": MIN_PEERS,
        "levels": {
            "locality": level(["locality_key", "bhk_b"]),
            "group": level(["locality_group", "bhk_b"]),
            "zone": level(["zone", "bhk_b"]),
            "city": level(["bhk_b"]),
        },
        "localities": localities,
        "group_zone": group_zone,
        "model_groups": sorted(group_counts[group_counts >= 10].index.tolist()),
        "deposit": build_deposit_stats(df),
    }


def build_deposit_stats(df: pd.DataFrame) -> dict[str, dict]:
    def stats(r: pd.Series) -> dict[str, float]:
        return {"n": int(len(r)), "median": round(float(r.median()), 3),
                "p05": round(float(r.quantile(.05)), 3), "p95": round(float(r.quantile(.95)), 3),
                "p99": round(float(r.quantile(.99)), 3)}

    d = df.dropna(subset=["deposit_ratio"])
    out = {"city": stats(d["deposit_ratio"])}
    for zone, g in d.groupby("zone"):
        if len(g) >= 30:
            out[f"zone|{zone}"] = stats(g["deposit_ratio"])
    return out


def build_contact_stats(df: pd.DataFrame) -> dict[str, dict]:
    """contact_hash -> {listings, localities}. Hash-map for O(1) lookup."""
    d = df.dropna(subset=["contact_hash"])
    agg = d.groupby("contact_hash").agg(listings=("listing_id", "size"),
                                        localities=("locality_group", "nunique"))
    return {h: {"listings": int(r.listings), "localities": int(r.localities)} for h, r in agg.iterrows()}


# --------------------------------------------------------------------------
# Risk feature vector (identical at training and inference time)
# --------------------------------------------------------------------------
RISK_FEATURES = [
    "price_log_ratio", "price_z", "price_available",
    "deposit_ratio_rel", "deposit_provided",
    "advance_payment", "payment_before_viewing", "no_viewing", "owner_away",
    "urgency_score", "unusual_payment", "off_platform", "semantic_risk",
    "dup_similarity", "dup_conflict",
    "contact_log_listings", "contact_reported",
    "desc_log_len", "missing_area", "n_text_categories",
]


def risk_feature_vector(price: dict, deposit: dict, text: dict, dup: dict, contact: dict,
                        listing: dict) -> dict[str, float]:
    """Flatten analyzer outputs into the numeric vector consumed by the risk model."""
    price_ok = price.get("available", False)
    dep_ratio = deposit.get("ratio")
    dep_median = deposit.get("peer_median_ratio") or 4.4
    cats = text.get("categories", {})
    desc = listing.get("description") or ""
    return {
        "price_log_ratio": float(price.get("log_ratio", 0.0)) if price_ok else 0.0,
        "price_z": float(np.clip(price.get("z_score", 0.0), -6, 6)) if price_ok else 0.0,
        "price_available": 1.0 if price_ok else 0.0,
        "deposit_ratio_rel": float(np.log(dep_ratio / dep_median)) if dep_ratio else 0.0,
        "deposit_provided": 1.0 if dep_ratio else 0.0,
        "advance_payment": float(bool(cats.get("advance_payment"))),
        "payment_before_viewing": float(bool(cats.get("payment_before_viewing"))),
        "no_viewing": float(bool(cats.get("no_viewing"))),
        "owner_away": float(bool(cats.get("owner_away"))),
        "urgency_score": float(text.get("urgency_score", 0.0)),
        "unusual_payment": float(bool(cats.get("unusual_payment"))),
        "off_platform": float(bool(cats.get("off_platform"))),
        "semantic_risk": float(text.get("semantic_risk_similarity", 0.0)),
        "dup_similarity": float(dup.get("max_similarity", 0.0)),
        "dup_conflict": float(bool(dup.get("conflicting_duplicate"))),
        "contact_log_listings": float(np.log1p(contact.get("listings_per_contact", 0) or 0)),
        "contact_reported": float(bool(contact.get("reported_count", 0))),
        "desc_log_len": float(np.log1p(len(desc))),
        "missing_area": 0.0 if listing.get("area_sqft") else 1.0,
        "n_text_categories": float(sum(1 for v in cats.values() if v)),
    }
