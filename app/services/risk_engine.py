"""Risk engine: combines every analyzer into one explainable risk assessment.

Scoring is additive so every point can be traced to evidence:

* **Rule indicators** each contribute a fixed number of points (table below).
  Their sum is capped at ``RULE_CAP`` (80).
* **ML model** contributes ``round(probability x ML_MAX_POINTS)`` (max 20).
  The model is trained on a documented synthetic dataset (docs/ml.md) and is
  a secondary signal - if it is missing the score is rule-only.

risk_score = min(80, sum(rule points)) + ML points, in [0, 100].

The output is a *risk assessment*, never a fraud verdict.
"""
from __future__ import annotations

from typing import Any

from app.ml.features import risk_feature_vector
from app.services.contact_analyzer import ContactAnalyzer, DbCounter
from app.services.duplicate_detector import DuplicateDetector
from app.services.price_analyzer import PriceAnalyzer
from app.services.text_analyzer import TextAnalyzer

RULE_CAP = 80
ML_MAX_POINTS = 20

POINTS = {
    "price_high": 25, "price_moderate": 12,
    "deposit_high": 15, "deposit_elevated": 8,
    "payment_before_viewing": 20, "advance_payment": 15, "no_viewing": 15, "owner_away": 10,
    "unusual_payment": 15, "sensitive_info": 20, "off_platform": 5, "urgency": 10,
    "semantic": 8,
    "duplicate_conflict": 15, "duplicate_repost": 3,
    "contact_reported": 10, "contact_widespread": 4,
    "listing_reported": 10,
    "short_description": 5, "missing_area": 3,
}

LEVELS = [(75, "VERY_HIGH", "Very high risk"), (50, "HIGH", "High risk"),
          (25, "MODERATE", "Moderate risk"), (0, "LOW", "Low risk")]

SUMMARIES = {
    "LOW": "Few or no risk indicators were detected. Standard precautions still apply.",
    "MODERATE": "Some unusual characteristics were detected. Further verification recommended.",
    "HIGH": "High-risk indicators detected. Verify the property and owner in person before paying anything.",
    "VERY_HIGH": "Potentially risky listing: multiple strong risk indicators were detected. "
                 "Do not transfer money before an in-person viewing and document verification.",
}

TEXT_EXPLANATIONS = {
    "payment_before_viewing": "Asking for money before you have seen the property is the most common pattern "
                              "in rental scams. Legitimate landlords let you view first.",
    "advance_payment": "The listing asks for an advance or token amount. Token payments are common in Mumbai, "
                       "but only pay after a viewing and with a written receipt.",
    "no_viewing": "The listing says a physical viewing is not possible. Never rent a property you cannot visit.",
    "owner_away": "The owner claims to be abroad or unavailable - a frequent story used to avoid meeting tenants.",
    "unusual_payment": "Untraceable or indirect payment methods (gift cards, crypto, third-party accounts, keys by "
                       "courier) are hard to recover if something goes wrong.",
    "sensitive_info": "Requests for OTPs or banking credentials are never needed to rent a flat.",
    "off_platform": "Contact is restricted to messaging apps, which makes identity harder to verify.",
    "urgency": "Pressure to decide or pay quickly reduces the time you have to verify the listing.",
}

DISCLAIMER = ("RentalGuard provides an automated risk assessment based on statistical patterns. "
              "It is not proof of fraud and may produce false positives and false negatives. "
              "Always verify the property, the owner's identity and ownership documents in person.")


def risk_level(score: float) -> tuple[str, str]:
    for threshold, code, label in LEVELS:
        if score >= threshold:
            return code, label
    return "LOW", "Low risk"


class RiskEngine:
    def __init__(self, price: PriceAnalyzer | None, text: TextAnalyzer, duplicates: DuplicateDetector | None,
                 contact: ContactAnalyzer, model: Any | None = None):
        self.price = price
        self.text = text
        self.duplicates = duplicates
        self.contact = contact
        self.model = model

    # ------------------------------------------------------------------
    def components(self, listing: dict[str, Any], exclude_id: str | None = None,
                   db_counter: DbCounter | None = None) -> dict[str, dict]:
        if self.price:
            price = self.price.analyze(listing)
            zone = price.get("location", {}).get("zone") if price.get("available") else \
                self.price.resolve_location(listing.get("locality")).zone
            deposit = self.price.analyze_deposit(listing, zone)
        else:
            zone = None
            price = {"available": False, "anomaly_level": "UNKNOWN", "explanation": "Price model not loaded."}
            deposit = {"available": False, "level": "NOT_PROVIDED", "ratio": None,
                       "explanation": "Deposit statistics not loaded."}
        text = self.text.analyze(listing.get("description"))
        if self.duplicates is not None and len(self.duplicates):
            dup_in = dict(listing, _zone=zone)
            dup = self.duplicates.analyze(dup_in, exclude_id=exclude_id)
        else:
            dup = {"available": False, "max_similarity": 0.0, "matches": [], "level": "NOT_APPLICABLE",
                   "possible_duplicate": False, "conflicting_duplicate": False,
                   "explanation": "Duplicate index not loaded."}
        contact = self.contact.analyze(listing, db_counter)
        return {"price": price, "deposit": deposit, "text": text, "duplicates": dup, "contact": contact}

    @staticmethod
    def rule_contributions(parts: dict[str, dict], listing: dict[str, Any],
                           listing_reports: int = 0) -> list[dict[str, Any]]:
        price, deposit, text = parts["price"], parts["deposit"], parts["text"]
        dup, contact = parts["duplicates"], parts["contact"]
        out: list[dict[str, Any]] = []

        def add(code: str, label: str, explanation: str, evidence: list[str] | None = None,
                points: int | None = None, category: str = "general") -> None:
            out.append({"code": code, "label": label, "points": POINTS[code] if points is None else points,
                        "explanation": explanation, "evidence": evidence or [], "category": category})

        if price.get("anomaly_level") == "HIGH":
            add("price_high", "Unusually low rent", price["explanation"],
                [f"₹{price['actual_rent']:,} vs expected ≈ ₹{price['expected_rent']:,.0f}"], category="price")
        elif price.get("anomaly_level") == "MODERATE":
            add("price_moderate", "Rent below comparable listings", price["explanation"],
                [f"₹{price['actual_rent']:,} vs expected ≈ ₹{price['expected_rent']:,.0f}"], category="price")

        if deposit.get("level") == "HIGH":
            add("deposit_high", "Unusually high deposit", deposit["explanation"], category="deposit")
        elif deposit.get("level") == "ELEVATED":
            add("deposit_elevated", "Deposit above typical range", deposit["explanation"], category="deposit")

        cats = text.get("categories", {})
        phrases_by_cat: dict[str, list[str]] = {}
        for m in text.get("matches", []):
            phrases_by_cat.setdefault(m["category"], []).append(m["phrase"])
        for cat in ("payment_before_viewing", "advance_payment", "no_viewing", "owner_away",
                    "unusual_payment", "sensitive_info", "off_platform"):
            if cats.get(cat):
                add(cat, text["category_labels"][cat], TEXT_EXPLANATIONS[cat],
                    [f"“{p}”" for p in phrases_by_cat.get(cat, [])][:3], category="text")
        if cats.get("urgency"):
            pts = max(3, round(POINTS["urgency"] * text.get("urgency_score", 0)))
            add("urgency", "Urgency or pressure language", TEXT_EXPLANATIONS["urgency"],
                [f"“{p}”" for p in phrases_by_cat.get("urgency", [])][:3], points=pts, category="text")
        if text.get("semantic_match") and not any(cats.values()):
            sm = text["semantic_match"]
            add("semantic", "Wording resembles known risky messages",
                f"A sentence is {text['semantic_risk_similarity']:.0%} similar (TF-IDF) to the pattern "
                f"“{sm['closest_pattern']}”.", [f"“{sm['sentence']}”"], category="text")

        if dup.get("conflicting_duplicate"):
            add("duplicate_conflict", "Near-identical listing with different details", dup["explanation"],
                dup.get("conflicts", []), category="duplicate")
        elif dup.get("possible_duplicate"):
            add("duplicate_repost", "Possible duplicate / repost", dup["explanation"], category="duplicate")

        if contact.get("level") == "REPORTED":
            add("contact_reported", "Contact linked to reported listings", contact["explanation"], category="contact")
        elif contact.get("level") == "WIDESPREAD":
            add("contact_widespread", "Repeated contact pattern detected", contact["explanation"], category="contact")

        if listing_reports:
            add("listing_reported", "Reported by other users",
                f"This listing has been reported {listing_reports} time(s) by RentalGuard users.", category="community")

        if text.get("short_description"):
            add("short_description", "Very little information in description",
                "Listings with minimal detail are harder to verify.", category="completeness")
        if not listing.get("area_sqft"):
            add("missing_area", "Area not provided",
                "Built-up/carpet area is missing, which makes price comparison less reliable.", category="completeness")
        return out

    # ------------------------------------------------------------------
    def assess(self, listing: dict[str, Any], exclude_id: str | None = None,
               db_counter: DbCounter | None = None, listing_reports: int = 0) -> dict[str, Any]:
        parts = self.components(listing, exclude_id, db_counter)
        contributions = self.rule_contributions(parts, listing, listing_reports)
        rule_points = min(RULE_CAP, sum(c["points"] for c in contributions))

        features = risk_feature_vector(parts["price"], parts["deposit"], parts["text"], parts["duplicates"],
                                       parts["contact"], listing)
        ml = {"available": False, "risk_probability": None, "points": 0}
        if self.model is not None:
            pred = self.model.predict(features)
            if pred is not None:
                pts = round(pred["risk_probability"] * ML_MAX_POINTS)
                ml = {"available": True, "points": pts, **pred}
                if pts:
                    contributions.append({
                        "code": "ml_model", "label": "Machine-learning risk estimate", "points": pts,
                        "explanation": f"The {pred.get('model_name', 'ML')} model estimates a "
                                       f"{pred['risk_probability']:.0%} probability that this combination of "
                                       "signals matches risky patterns (trained on synthetic labels).",
                        "evidence": [], "category": "ml"})

        score = int(min(100, rule_points + ml["points"]))
        level, label = risk_level(score)
        contributions.sort(key=lambda c: -c["points"])       # rank by contribution
        capped = sum(c["points"] for c in contributions if c["code"] != "ml_model") > RULE_CAP
        return {
            "risk_score": score,
            "risk_level": level,
            "risk_label": label,
            "summary": SUMMARIES[level],
            "rule_points": rule_points,
            "rule_points_capped": capped,
            "contributions": contributions,
            "indicator_codes": sorted({c["code"] for c in contributions}),
            "ml": ml,
            "features": {k: round(v, 4) for k, v in features.items()},
            **parts,
            "disclaimer": DISCLAIMER,
        }
