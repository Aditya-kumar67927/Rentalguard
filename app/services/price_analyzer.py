"""Price and security-deposit anomaly analysis.

Expected rent comes from two explainable sources:

1. **Peer estimate** - robust statistics (median, MAD) of comparable listings,
   looked up in a hash map with a fallback hierarchy:
   ``locality + BHK -> locality group + BHK -> zone + BHK -> city + BHK``.
   When the built-up area is known the estimate is ``median rent/sq.ft x area``.
2. **Model estimate** (optional) - a gradient-boosted regressor trained on the
   same dataset (see app/ml/train.py).

The two are blended in log-space with a shrinkage weight that trusts the
peer estimate more when the peer group is large: ``w = n / (n + 15)``.

The anomaly score is a robust z-score: ``z = ln(actual / expected) / sigma``
where sigma is the peer group's MAD-based standard deviation of log price.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.ml.features import bhk_bucket
from app.ml.preprocessing import price_feature_frame
from app.utils.locality import display_name, locality_key, resolve_group

SHRINKAGE_K = 15
SIGMA_FLOOR = 0.20
LEVEL_LABELS = {"locality": "same locality", "group": "same area", "zone": "same zone", "city": "all of Mumbai"}


@dataclass
class Location:
    key: str
    group: str
    zone: str
    display: str
    known: bool


class PriceAnalyzer:
    def __init__(self, baselines: dict[str, Any], model: Any | None = None):
        self.baselines = baselines
        self.levels: dict[str, dict] = baselines.get("levels", {})
        self.localities: dict[str, dict] = baselines.get("localities", {})
        self.group_zone: dict[str, str] = baselines.get("group_zone", {})
        self.model_groups = set(baselines.get("model_groups", []))
        self.known_groups = set(self.group_zone)
        self.deposit_stats: dict[str, dict] = baselines.get("deposit", {})
        self.model = model

    @classmethod
    def from_file(cls, path: Path, model: Any | None = None) -> "PriceAnalyzer":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), model)

    # ------------------------------------------------------------------
    def resolve_location(self, raw: str | None) -> Location:
        key = locality_key(raw)
        info = self.localities.get(key)
        if info:
            return Location(key, info["group"], info["zone"], info["display"], True)
        group = resolve_group(key, self.known_groups)
        zone = self.group_zone.get(group, "Unknown")
        return Location(key, group, zone, display_name(key) if key else "", group in self.known_groups)

    def peer_stats(self, loc: Location, bhk: int) -> tuple[str, str, dict] | None:
        candidates = [("locality", loc.key, loc.display), ("group", loc.group, display_name(loc.group)),
                      ("zone", loc.zone, loc.zone), ("city", None, "Mumbai")]
        for level, name, label in candidates:
            table = self.levels.get(level, {})
            k = f"{bhk}" if level == "city" else f"{name}|{bhk}"
            if name == "" or (level == "zone" and name == "Unknown"):
                continue
            if k in table:
                return level, label, table[k]
        return None

    def _model_estimate(self, listing: dict, loc: Location, peer: dict) -> float | None:
        if self.model is None:
            return None
        # Only 3 training rows lack an area, so the model's missing-value branch is
        # unreliable; impute the peer group's median area instead.
        area = listing.get("area_sqft") or peer.get("median_area")
        if not area:
            return None
        try:
            frame = price_feature_frame([{
                "locality_group": loc.group, "zone": loc.zone,
                "furnishing": listing.get("furnishing"), "property_type": listing.get("property_type"),
                "bhk": listing.get("bhk"), "area_sqft": area,
                "bathrooms": listing.get("bathrooms"),
            }], self.model_groups)
            return float(np.exp(self.model.predict(frame)[0]))
        except Exception:  # model problems must never break the analysis
            return None

    # ------------------------------------------------------------------
    def analyze(self, listing: dict) -> dict[str, Any]:
        rent = listing.get("rent")
        bhk = bhk_bucket(listing.get("bhk"))
        if not rent or rent <= 0 or bhk is None:
            return {"available": False, "anomaly_level": "UNKNOWN",
                    "explanation": "Rent and BHK are required for price analysis."}
        loc = self.resolve_location(listing.get("locality"))
        peers = self.peer_stats(loc, bhk)
        if peers is None:
            return {"available": False, "anomaly_level": "UNKNOWN",
                    "explanation": "No comparable listings available."}
        level, label, st = peers
        area = listing.get("area_sqft")

        if area and "median_ppsf" in st:
            raw = st["median_ppsf"] * area
            # Guard against implausible areas: stay within 0.5x - 2x the peer median rent
            peer_est = float(np.clip(raw, 0.5 * st["median_rent"], 2.0 * st["median_rent"]))
            sigma = st.get("sigma_log_ppsf") or st["sigma_log_rent"]
            basis = f"median rent per sq.ft (₹{st['median_ppsf']:.0f}) × {area:,.0f} sq.ft"
        else:
            peer_est = st["median_rent"]
            sigma = st["sigma_log_rent"]
            basis = "median rent"
        sigma = max(SIGMA_FLOOR, sigma if sigma and not math.isnan(sigma) else SIGMA_FLOOR)

        model_est = self._model_estimate(listing, loc, st)
        n = st["n"]
        # Only locality-level peers are "specific"; broader levels get less weight
        n_eff = n if level == "locality" else n / 4
        w_peer = n_eff / (n_eff + SHRINKAGE_K) if model_est else 1.0
        expected = math.exp(w_peer * math.log(peer_est) + (1 - w_peer) * math.log(model_est)) \
            if model_est else peer_est

        log_ratio = math.log(rent / expected)
        z = log_ratio / sigma
        ratio = rent / expected
        low, high = expected * math.exp(-0.6745 * sigma), expected * math.exp(0.6745 * sigma)
        deviation = (expected - rent) / expected * 100

        if z <= -2.5 or ratio < 0.45:
            anomaly = "HIGH"
            msg = (f"Listed rent is {deviation:.0f}% below the estimated comparable rent. "
                   "Unusually low rent is a common feature of bait listings; verify the property in person.")
        elif z <= -1.5 or ratio < 0.65:
            anomaly = "MODERATE"
            msg = f"Listed rent is {deviation:.0f}% below comparable listings - lower than usual."
        elif z >= 2.5:
            anomaly = "ABOVE_MARKET"
            msg = f"Listed rent is {-deviation:.0f}% above comparable listings (informational, not a risk signal)."
        else:
            anomaly = "NORMAL"
            msg = "Listed rent is within the typical range for comparable listings."

        return {
            "available": True,
            "actual_rent": round(rent),
            "expected_rent": round(expected, -2),
            "expected_range": [round(low, -2), round(high, -2)],
            "deviation_percent": round(deviation, 1),
            "log_ratio": round(log_ratio, 4),
            "z_score": round(z, 2),
            "anomaly_level": anomaly,
            "peer_group": {"level": level, "label": LEVEL_LABELS[level], "name": label, "bhk": bhk,
                           "count": n, "median_rent": st["median_rent"]},
            "peer_estimate": round(peer_est, -2),
            "model_estimate": round(model_est, -2) if model_est else None,
            "peer_weight": round(w_peer, 2),
            "method": f"Peer {basis} for {bhk} BHK in {label} ({LEVEL_LABELS[level]}, n={n})"
                      + (f", blended with ML estimate (peer weight {w_peer:.2f})" if model_est else ""),
            "location": {"key": loc.key, "display": loc.display, "group": loc.group, "zone": loc.zone,
                         "known": loc.known},
            "explanation": msg,
        }

    # ------------------------------------------------------------------
    def analyze_deposit(self, listing: dict, zone: str | None = None) -> dict[str, Any]:
        rent, deposit = listing.get("rent"), listing.get("deposit")
        if not deposit or not rent or rent <= 0:
            return {"available": False, "level": "NOT_PROVIDED", "ratio": None,
                    "explanation": "No security deposit provided - ask the landlord to confirm it in writing."}
        ratio = deposit / rent
        key = f"zone|{zone}"
        st = self.deposit_stats.get(key) or self.deposit_stats.get("city")
        scope = zone if key in self.deposit_stats else "Mumbai"
        if not st:
            st = {"median": 4.4, "p95": 6.0, "p99": 7.5, "p05": 2.0, "n": 0}
        if ratio > max(st["p99"], 10):
            level, msg = "HIGH", (f"Deposit of {ratio:.1f}× monthly rent is unusually high compared with similar "
                                  f"listings in {scope} (typical {st['median']:.1f}×).")
        elif ratio > st["p95"]:
            level, msg = "ELEVATED", (f"Deposit of {ratio:.1f}× monthly rent is higher than most listings in "
                                      f"{scope} (typical {st['median']:.1f}×).")
        elif ratio < 1:
            level, msg = "LOW", (f"Deposit is below one month's rent ({ratio:.1f}×), lower than typical. "
                                 "Not a risk indicator on its own.")
        else:
            level, msg = "NORMAL", f"Deposit of {ratio:.1f}× monthly rent is typical for {scope}."
        return {"available": True, "level": level, "ratio": round(ratio, 2), "deposit": round(deposit),
                "peer_median_ratio": st["median"], "peer_p95_ratio": st["p95"], "peer_n": st["n"],
                "scope": scope, "explanation": msg}
