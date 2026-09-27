import pytest

from app.services.contact_analyzer import ContactAnalyzer
from app.services.risk_engine import ML_MAX_POINTS, RULE_CAP, RiskEngine, risk_level
from app.services.text_analyzer import TextAnalyzer
from tests.conftest import NORMAL_LISTING, SCAM_LISTING


class StubModel:
    def __init__(self, p):
        self.p = p

    def predict(self, features):
        assert isinstance(features, dict) and "price_z" in features
        return {"risk_probability": self.p, "model_name": "stub"}


def total_points(result):
    return sum(c["points"] for c in result["contributions"])


def test_normal_listing_is_low_risk(engine):
    r = engine.assess(NORMAL_LISTING)
    assert r["risk_level"] == "LOW"
    assert r["risk_score"] < 25
    assert r["ml"]["available"] is False


def test_scam_like_listing_is_very_high(engine):
    r = engine.assess(SCAM_LISTING)
    assert r["risk_level"] == "VERY_HIGH"
    codes = set(r["indicator_codes"])
    assert {"price_high", "payment_before_viewing", "owner_away", "no_viewing"} <= codes
    # contributions are ranked (sorted) by points, highest first
    pts = [c["points"] for c in r["contributions"]]
    assert pts == sorted(pts, reverse=True)


def test_score_is_explainable_sum(engine):
    r = engine.assess(dict(NORMAL_LISTING, rent=29500))
    assert r["risk_score"] == min(RULE_CAP, total_points(r))


def test_rule_points_are_capped(engine):
    r = engine.assess(SCAM_LISTING)
    assert r["rule_points"] == RULE_CAP
    assert r["rule_points_capped"] is True
    assert 0 <= r["risk_score"] <= 100


@pytest.mark.parametrize("p", [0.0, 0.5, 1.0])
def test_ml_model_adds_at_most_20_points(engine, p):
    engine.model = StubModel(p)
    r = engine.assess(NORMAL_LISTING)
    assert r["ml"]["available"] is True
    assert r["ml"]["points"] == round(p * ML_MAX_POINTS)
    assert r["risk_score"] <= 100


def test_broken_model_degrades_to_rules(engine):
    class Broken:
        def predict(self, features):
            return None
    engine.model = Broken()
    r = engine.assess(NORMAL_LISTING)
    assert r["ml"]["available"] is False


def test_engine_without_optional_components():
    bare = RiskEngine(None, TextAnalyzer(), None, ContactAnalyzer())
    r = bare.assess(SCAM_LISTING)
    assert r["price"]["available"] is False
    assert r["duplicates"]["available"] is False
    assert r["risk_score"] >= 50   # text evidence alone still counts


def test_missing_description_and_area_are_completeness_indicators(engine):
    r = engine.assess({"locality": "Powai", "rent": 40000, "bhk": 2, "description": ""})
    codes = set(r["indicator_codes"])
    assert {"short_description", "missing_area"} <= codes
    assert r["risk_level"] in ("LOW", "MODERATE")


@pytest.mark.parametrize("score,level", [(0, "LOW"), (24, "LOW"), (25, "MODERATE"), (49, "MODERATE"),
                                         (50, "HIGH"), (74, "HIGH"), (75, "VERY_HIGH"), (100, "VERY_HIGH")])
def test_level_thresholds(score, level):
    assert risk_level(score)[0] == level


def test_wording_never_claims_fraud(engine):
    r = engine.assess(SCAM_LISTING)
    blob = (r["summary"] + " ".join(c["explanation"] for c in r["contributions"])).lower()
    assert "is a scam" not in blob and "fraudster" not in blob and "definitely" not in blob
    assert "not proof of fraud" in r["disclaimer"]


def test_contact_reports_raise_risk(engine):
    counter = lambda hashes: {h: {"listings": 3, "localities": 2, "reports": 2} for h in hashes}  # noqa: E731
    r = engine.assess(dict(NORMAL_LISTING, contact="+91 98765 43210"), db_counter=counter)
    assert r["contact"]["level"] == "REPORTED"
    assert "contact_reported" in r["indicator_codes"]


def test_repeated_contact_alone_is_not_risky(engine):
    r = engine.assess(dict(NORMAL_LISTING, contact="Agency 1"))
    assert r["contact"]["level"] == "REPEATED"
    assert "contact_widespread" not in r["indicator_codes"]
    assert "Repeated contact pattern detected" in r["contact"]["explanation"]
