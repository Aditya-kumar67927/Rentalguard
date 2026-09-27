"""Risk-model inference wrapper.

    >>> model = RiskModel.load(Path("ml_models"))
    >>> model.predict(feature_dict)
    {'risk_probability': 0.82, 'model_name': 'gradient_boosting'}
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.ml.features import RISK_FEATURES
from app.ml.model_loader import RISK_MODEL, load_joblib


class RiskModel:
    def __init__(self, bundle: dict[str, Any]):
        self.pipeline = bundle["pipeline"]
        self.features: list[str] = bundle["features"]
        self.name: str = bundle.get("model_name", "model")
        self.version: str = bundle.get("version", "unknown")

    @classmethod
    def load(cls, directory: Path) -> "RiskModel | None":
        bundle = load_joblib(directory, RISK_MODEL)
        if not bundle or bundle.get("features") != RISK_FEATURES:
            return None  # missing, or trained with a different feature schema
        return cls(bundle)

    def predict(self, features: dict[str, float]) -> dict[str, Any] | None:
        try:
            row = pd.DataFrame([[features.get(f, 0.0) for f in self.features]], columns=self.features)
            p = float(self.pipeline.predict_proba(row)[0, 1])
        except Exception:
            return None
        if not np.isfinite(p):
            return None
        return {"risk_probability": round(p, 4), "model_name": self.name, "model_version": self.version}
