"""Load persisted artifacts from ml_models/ with graceful degradation.

Every loader returns ``None`` (and logs a warning) instead of raising when an
artifact is missing or incompatible, so the web app keeps working in a
reduced, rule-only mode.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import joblib

log = logging.getLogger(__name__)

PRICE_BASELINES = "price_baselines.json"
CONTACT_STATS = "contact_stats.json"
DUPLICATE_INDEX = "duplicate_index.joblib"
PRICE_MODEL = "price_model.joblib"
RISK_MODEL = "risk_model.joblib"
METRICS = "metrics.json"


def load_json(directory: Path, name: str) -> Any | None:
    path = Path(directory) / name
    if not path.exists():
        log.warning("artifact missing: %s", path)
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error("could not read %s: %s", path, exc)
        return None


def load_joblib(directory: Path, name: str) -> Any | None:
    path = Path(directory) / name
    if not path.exists():
        log.warning("artifact missing: %s", path)
        return None
    try:
        return joblib.load(path)
    except Exception as exc:  # corrupted file / incompatible sklearn version
        log.error("could not load %s: %s", path, exc)
        return None
