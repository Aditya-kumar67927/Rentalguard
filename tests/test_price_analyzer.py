import pytest

from app.services.price_analyzer import PriceAnalyzer
from app.utils.locality import locality_key
from app.utils.money import extract_deposit, parse_amount


def listing(**kw):
    base = {"locality": "Andheri West", "rent": 44000, "bhk": 2, "area_sqft": 800}
    base.update(kw)
    return base


def test_normal_rent_is_normal(price_analyzer):
    r = price_analyzer.analyze(listing())
    assert r["available"] is True
    assert r["anomaly_level"] == "NORMAL"
    lo, hi = r["expected_range"]
    assert lo < r["expected_rent"] < hi
    assert r["peer_group"]["level"] == "locality"


def test_very_low_rent_is_high_anomaly(price_analyzer):
    r = price_analyzer.analyze(listing(rent=9000))
    assert r["anomaly_level"] == "HIGH"
    assert r["deviation_percent"] > 60
    assert r["z_score"] < -2.5
    assert "below" in r["explanation"]


def test_moderately_low_rent(price_analyzer):
    r = price_analyzer.analyze(listing(rent=29500))   # ~0.67x expected
    assert r["anomaly_level"] == "MODERATE"


def test_above_market_is_informational(price_analyzer):
    r = price_analyzer.analyze(listing(rent=200000))
    assert r["anomaly_level"] == "ABOVE_MARKET"


@pytest.mark.parametrize("rent", [None, 0, -5000])
def test_missing_zero_or_negative_rent_is_unavailable(price_analyzer, rent):
    r = price_analyzer.analyze(listing(rent=rent))
    assert r["available"] is False
    assert r["anomaly_level"] == "UNKNOWN"


def test_missing_bhk_is_unavailable(price_analyzer):
    assert price_analyzer.analyze(listing(bhk=None))["available"] is False


def test_unknown_locality_falls_back_to_city(price_analyzer):
    r = price_analyzer.analyze(listing(locality="Some Unknown Place"))
    assert r["available"] is True
    assert r["peer_group"]["level"] == "city"


def test_without_area_uses_median_rent(price_analyzer):
    r = price_analyzer.analyze(listing(area_sqft=None))
    assert "median rent" in r["method"] and "per sq.ft" not in r["method"]


@pytest.mark.parametrize("raw", ["Andheri West", "andheri-west", "ANDHERI (W)", "Andheri W", "  andheri   west "])
def test_locality_variants_normalise_to_same_key(raw, price_analyzer):
    assert locality_key(raw) == "andheri west"
    assert price_analyzer.analyze(listing(locality=raw))["peer_group"]["level"] == "locality"


def test_empty_baselines_do_not_crash():
    r = PriceAnalyzer({}).analyze(listing())
    assert r["available"] is False


# ---- deposit ------------------------------------------------------------------
def test_deposit_normal(price_analyzer):
    r = price_analyzer.analyze_deposit(listing(deposit=44000 * 4), "Andheri-Dahisar")
    assert r["level"] == "NORMAL"
    assert r["ratio"] == pytest.approx(4.0)


def test_deposit_unusually_high(price_analyzer):
    r = price_analyzer.analyze_deposit(listing(deposit=44000 * 15), "Andheri-Dahisar")
    assert r["level"] == "HIGH"
    assert "unusually high" in r["explanation"]
    assert "fraud" not in r["explanation"].lower()


def test_deposit_missing(price_analyzer):
    assert price_analyzer.analyze_deposit(listing(deposit=None))["level"] == "NOT_PROVIDED"


# ---- money parsing ------------------------------------------------------------------
@pytest.mark.parametrize("text,unit,expected", [("7, 00,000", None, 700000), ("1.5", "lakh", 150000),
                                                 ("35", "k", 35000), ("₹35,000", None, 35000), ("", None, None)])
def test_parse_amount(text, unit, expected):
    assert parse_amount(text, unit) == expected


@pytest.mark.parametrize("text,rent,expected", [
    ("Tenant needs to make a security deposit of rs. 500000.", 85000, 500000),
    ("security deposit of 6 months rent.", 28000, 168000),
    ("Asking for 35k rental and 1 lakh deposit", 35000, 100000),
    ("deposit of rs. 5 only", 30000, None),          # implausible -> rejected
    ("no deposit information here", 30000, None),
])
def test_extract_deposit(text, rent, expected):
    assert extract_deposit(text, rent) == expected


class RecordingModel:
    """Stub regressor: records the frame it was given and predicts log(40000)."""
    def __init__(self):
        self.frames = []

    def predict(self, frame):
        import numpy as np
        self.frames.append(frame)
        return np.array([np.log(40000.0)])


def test_model_gets_imputed_area_when_missing(artifact_dir):
    model = RecordingModel()
    analyzer = PriceAnalyzer.from_file(artifact_dir / "price_baselines.json", model)
    r = analyzer.analyze(listing(area_sqft=None))
    assert r["model_estimate"] == 40000
    assert model.frames[0]["log_area"].notna().all()     # never NaN (unreliable branch)
    assert 0 < r["peer_weight"] < 1                      # peer + model blend


def test_broken_model_is_ignored(artifact_dir):
    class Broken:
        def predict(self, frame):
            raise ValueError("boom")
    r = PriceAnalyzer.from_file(artifact_dir / "price_baselines.json", Broken()).analyze(listing())
    assert r["available"] is True and r["model_estimate"] is None
