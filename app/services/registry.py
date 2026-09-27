"""Build a fully wired RiskEngine from the artifacts directory.

Missing artifacts degrade gracefully: the corresponding analyzer is disabled
and the result says so, instead of the app failing to start.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.ml.model_loader import (CONTACT_STATS, DUPLICATE_INDEX, PRICE_BASELINES, PRICE_MODEL,
                                 load_joblib, load_json)
from app.ml.predict import RiskModel
from app.services.contact_analyzer import ContactAnalyzer
from app.services.duplicate_detector import DuplicateDetector
from app.services.price_analyzer import PriceAnalyzer
from app.services.risk_engine import RiskEngine
from app.services.text_analyzer import TextAnalyzer

log = logging.getLogger(__name__)


def build_engine(model_dir: Path, load_ml: bool = True) -> tuple[RiskEngine, dict[str, bool]]:
    model_dir = Path(model_dir)
    baselines = load_json(model_dir, PRICE_BASELINES)
    price_bundle = load_joblib(model_dir, PRICE_MODEL) if load_ml else None
    price_model = price_bundle.get("pipeline") if isinstance(price_bundle, dict) else None
    price = PriceAnalyzer(baselines, price_model) if baselines else None

    dup = load_joblib(model_dir, DUPLICATE_INDEX)
    if dup is not None and not isinstance(dup, DuplicateDetector):
        log.error("duplicate index has unexpected type %s", type(dup))
        dup = None

    contact = ContactAnalyzer(load_json(model_dir, CONTACT_STATS) or {})
    risk_model = RiskModel.load(model_dir) if load_ml else None
    status = {"price_baselines": price is not None, "price_model": price_model is not None,
              "duplicate_index": dup is not None, "contact_stats": bool(contact.stats),
              "risk_model": risk_model is not None}
    return RiskEngine(price, TextAnalyzer(), dup, contact, risk_model), status
