"""Shared fixtures.

Tests never depend on the downloaded dataset: a small synthetic reference
frame is generated here and turned into the same artifacts the real pipeline
produces (price baselines, contact stats, duplicate index).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.extensions import db as _db  # noqa: E402
from app.ml.features import build_contact_stats, build_price_baselines  # noqa: E402
from app.services.contact_analyzer import ContactAnalyzer  # noqa: E402
from app.services.duplicate_detector import DuplicateDetector  # noqa: E402
from app.services.price_analyzer import PriceAnalyzer  # noqa: E402
from app.services.risk_engine import RiskEngine  # noqa: E402
from app.services.text_analyzer import TextAnalyzer  # noqa: E402
from app.utils.privacy import hash_contact  # noqa: E402

# (locality, zone, median rent per sq.ft)
LOCALITIES = [("Andheri West", "Andheri-Dahisar", 55.0), ("Powai", "Central Suburbs", 50.0),
              ("Kharghar", "Navi Mumbai", 20.0)]
AREA_BY_BHK = {1: 550, 2: 800, 3: 1200}

FEATURES = ["modular kitchen", "covered parking", "gym", "swimming pool", "garden view", "lift",
            "24x7 security", "power backup", "near station", "club house", "sea view", "balcony"]


def make_reference_frame(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    i = 0
    for loc, zone, ppsf in LOCALITIES:
        for bhk, area0 in AREA_BY_BHK.items():
            for _ in range(20):
                area = float(round(area0 * rng.uniform(0.85, 1.15)))
                rent = float(round(ppsf * area * np.exp(rng.normal(0, 0.1)), -2))
                feats = ", ".join(rng.choice(FEATURES, 4, replace=False))
                rows.append({
                    "listing_id": f"T-{i:04d}", "locality": loc, "locality_key": loc.lower(),
                    "locality_group": loc.lower(), "zone": zone, "bhk": float(bhk), "rent": rent,
                    "area_sqft": area, "rent_per_sqft": rent / area, "price_outlier": False,
                    "deposit": rent * 4, "deposit_ratio": float(rng.uniform(3, 6)),
                    "contact_hash": hash_contact(f"agency {i % 7}"),
                    "description": f"{bhk} bhk flat for rent in {loc.lower()} with {feats}. "
                                   f"Listing number {i} with area {int(area)} sq ft on floor {i % 20}.",
                })
                i += 1
    return pd.DataFrame(rows)


@pytest.fixture(scope="session")
def reference_frame() -> pd.DataFrame:
    return make_reference_frame()


@pytest.fixture(scope="session")
def artifact_dir(tmp_path_factory, reference_frame) -> Path:
    d = tmp_path_factory.mktemp("artifacts")
    df = reference_frame
    (d / "price_baselines.json").write_text(json.dumps(build_price_baselines(df)))
    (d / "contact_stats.json").write_text(json.dumps(build_contact_stats(df)))
    meta = [{"id": r.listing_id, "rent": r.rent, "bhk": r.bhk, "locality": r.locality,
             "locality_group": r.locality_group, "zone": r.zone, "source": "dataset"} for r in df.itertuples()]
    joblib.dump(DuplicateDetector().fit(df.description.tolist(), meta), d / "duplicate_index.joblib")
    return d


@pytest.fixture(scope="session")
def price_analyzer(artifact_dir) -> PriceAnalyzer:
    return PriceAnalyzer.from_file(artifact_dir / "price_baselines.json")


@pytest.fixture(scope="session")
def text_analyzer() -> TextAnalyzer:
    return TextAnalyzer()


@pytest.fixture()
def duplicate_detector(artifact_dir) -> DuplicateDetector:
    return joblib.load(artifact_dir / "duplicate_index.joblib")   # fresh copy per test (add() mutates)


@pytest.fixture()
def engine(price_analyzer, text_analyzer, duplicate_detector, artifact_dir) -> RiskEngine:
    stats = json.loads((artifact_dir / "contact_stats.json").read_text())
    return RiskEngine(price_analyzer, text_analyzer, duplicate_detector, ContactAnalyzer(stats))


@pytest.fixture()
def app(artifact_dir):
    app = create_app("testing", MODEL_DIR=artifact_dir, LOAD_ML=False)
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def register(client, email="user@example.com", password="password123", name="Test User"):
    return client.post("/api/auth/register", json={"name": name, "email": email, "password": password})


@pytest.fixture()
def auth_client(client):
    resp = register(client)
    assert resp.status_code == 201
    return client


NORMAL_LISTING = {
    "locality": "Andheri West", "rent": 44000, "deposit": 180000, "bhk": 2, "area_sqft": 800,
    "furnishing": "semi-furnished", "property_type": "apartment",
    "description": "2 bhk flat for rent in andheri west with lift, gym and covered parking. "
                   "Family preferred. Call to schedule a visit.",
}
SCAM_LISTING = {
    "locality": "Andheri West", "rent": 9000, "bhk": 2, "area_sqft": 800,
    "description": "I am currently in Dubai so no physical viewing is possible. Send token amount before "
                   "viewing and I will courier the keys. Pay immediately or it will be given to someone else.",
}
