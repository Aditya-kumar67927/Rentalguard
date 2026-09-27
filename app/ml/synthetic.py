"""Synthetic risk-labelled dataset generator.

WHY SYNTHETIC: the public Mumbai rental data has no fraud labels, and no
openly licensed, labelled Indian rental-scam dataset was found (docs/dataset.md).
Treating ordinary listings as "not scam" and inventing scams by keyword would
make the task trivial and the metrics meaningless, so labels come from a
*generative simulation*:

* every sample starts from a **real cleaned listing** (real rent, locality,
  area, description, hashed dealer);
* a latent class is drawn: legitimate (≈75%) or risky (≈25%);
* each class applies *tactics* with overlapping probabilities:
  - legitimate listings sometimes have genuine discounts, missing area,
    short text, broker templates, routine "token after visit" wording, or
    "urgent requirement" wording;
  - risky listings use a random subset of bait pricing, risky wording
    (regex-detectable, paraphrased/misspelled, or undetectable), cloned
    descriptions from other listings, inflated deposits, missing details;
* ~3% of labels are flipped to model annotation noise;
* features are then computed by the **same analyzers used in production**
  (price, deposit, text, duplicate, contact), so train/serve skew is avoided.

The resulting model learns how to *combine* weak signals; its metrics measure
how well it recovers this simulation, not real-world fraud-detection accuracy.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd

from app.ml.features import risk_feature_vector
from app.services.risk_engine import RiskEngine

RISKY_RATE = 0.25
LABEL_NOISE = 0.03

# Risky snippets; tagged by whether the rule layer is expected to catch them.
RISKY_SNIPPETS = [
    "Send token amount before viewing.",
    "Please transfer the advance and I will courier the keys.",
    "I am currently in Dubai so a physical viewing is not possible.",
    "Owner is abroad, pay the booking amount to reserve the flat.",
    "Pay immediately or the property will be given to someone else.",
    "Many people are interested, transfer the deposit today to confirm.",
    "No physical viewing, only video tour available.",
    "Pay the security deposit to my agent's account before visit.",
    "Keys will be sent after payment is received.",
    "Contact on WhatsApp only.",
    "Send 10000 rs advance to block the flat, visit later.",
    "Kindly deposit the amount in my account and I will share the address.",
    "Payment through gift card or crypto accepted.",
    "Share the OTP to complete the booking.",
    "snd advnce paymnt befor visting the flat",
    "i m out of india at present, pay first n move in directly",
    "first pay deposit online then only site visit will be arranged",
    "hurry, offer valid today only",
    "Owner is working in the USA, caretaker will hand over keys after the transfer.",
    "Rent is very low because owner wants a good tenant quickly, no brokers, book online now.",
    "Genuine owner, amazing deal, will not last.",   # deliberately weak / hard to detect
    "Flat is fully ready, documents will be shared after booking.",
]
BENIGN_SNIPPETS = [
    "Token amount to be paid after site visit and finalisation.",
    "Urgent requirement of tenant, family preferred.",
    "Owner is an NRI, the agent will show the flat.",
    "Immediately available.",
    "Brokers please do not call.",
    "Rent slightly negotiable for a good tenant.",
    "Call to schedule a visit this weekend.",
    "Deposit negotiable.",
    "Pay token amount to book once you like the flat.",
]


def _pick(rng: np.random.Generator, items: list[str], k: int) -> list[str]:
    return [items[i] for i in rng.choice(len(items), size=min(k, len(items)), replace=False)]


def generate(df: pd.DataFrame, engine: RiskEngine, n: int = 6000, seed: int = 7,
             progress: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base_idx = rng.integers(0, len(df), size=n)
    deposit_ratios = df["deposit_ratio"].dropna().to_numpy()
    rows: list[dict[str, Any]] = []
    t0 = time.time()

    for i, bi in enumerate(base_idx):
        b = df.iloc[bi]
        risky = rng.random() < RISKY_RATE
        tactics: list[str] = []
        rent = float(b.rent) * float(np.exp(rng.normal(0, 0.12)))
        desc = str(b.description) if isinstance(b.description, str) else ""
        area = None if pd.isna(b.area_sqft) else float(b.area_sqft)
        # Deposit is kept as a *ratio* and applied to the final rent below, so changing
        # the rent (bait price / discount) does not silently inflate deposit/rent.
        dep_ratio = float(b.deposit_ratio) if not pd.isna(b.deposit_ratio) else (
            float(rng.choice(deposit_ratios)) if rng.random() < 0.5 else None)
        inflated_ratio = None
        # Contact distribution is identical for both classes: no signal is invented here.
        contact_hash = None if pd.isna(b.contact_hash) or rng.random() < 0.3 else b.contact_hash
        exclude = b.listing_id

        if not risky:
            if rng.random() < 0.08:
                rent *= rng.uniform(0.5, 0.8); tactics.append("genuine_discount")
            if rng.random() < 0.05:
                area = None; tactics.append("missing_area")
            if rng.random() < 0.03:
                desc = " ".join(desc.split()[:8]); tactics.append("short_text")
            if rng.random() < 0.15:
                desc += " " + " ".join(_pick(rng, BENIGN_SNIPPETS, 1)); tactics.append("benign_wording")
            if rng.random() < 0.04:
                desc += " " + " ".join(_pick(rng, RISKY_SNIPPETS, 1)); tactics.append("risky_wording_legit")
        else:
            used = False
            if rng.random() < 0.6:
                rent *= rng.uniform(0.3, 0.75); tactics.append("bait_price"); used = True
            if rng.random() < 0.35:
                other = df.iloc[int(rng.integers(0, len(df)))]
                if isinstance(other.description, str) and len(other.description.split()) >= 8:
                    desc = other.description; tactics.append("cloned_text"); used = True
            if rng.random() < 0.25:
                inflated_ratio = rng.uniform(8, 20); tactics.append("inflated_deposit"); used = True
            if rng.random() < 0.3:
                area = None; tactics.append("missing_area")
            if rng.random() < 0.2:
                desc = " ".join(desc.split()[:10]); tactics.append("short_text")
            if rng.random() < 0.7 or not used:
                desc += " " + " ".join(_pick(rng, RISKY_SNIPPETS, int(rng.integers(1, 4))))
                tactics.append("risky_wording")

        ratio = inflated_ratio or dep_ratio
        deposit = rent * ratio if ratio else None
        listing = {"locality": b.location_raw, "rent": round(rent), "bhk": float(b.bhk), "area_sqft": area,
                   "bathrooms": None if pd.isna(b.bathrooms) else float(b.bathrooms),
                   "furnishing": b.furnishing, "property_type": b.property_type,
                   "deposit": round(deposit) if deposit else None, "description": desc, "contact_hash": contact_hash}
        parts = engine.components(listing, exclude_id=exclude)
        rule_points = min(80, sum(c["points"] for c in engine.rule_contributions(parts, listing)))
        feats = risk_feature_vector(parts["price"], parts["deposit"], parts["text"], parts["duplicates"],
                                    parts["contact"], listing)
        label = int(risky)
        if rng.random() < LABEL_NOISE:
            label = 1 - label
        rows.append({**feats, "rule_points": rule_points, "risk_label": label, "latent_risky": int(risky),
                     "tactics": ";".join(tactics), "base_listing_id": b.listing_id})
        if progress and (i + 1) % 1000 == 0:
            print(f"  generated {i + 1}/{n} ({time.time() - t0:.0f}s)")
    return pd.DataFrame(rows)
