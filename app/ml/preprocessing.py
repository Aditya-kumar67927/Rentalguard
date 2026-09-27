"""Feature preparation shared by price-model training and runtime prediction."""
from __future__ import annotations

import numpy as np
import pandas as pd

PRICE_CATEGORICAL = ["locality_group", "zone", "furnishing", "property_type"]
PRICE_NUMERIC = ["bhk", "log_area", "bathrooms"]
PRICE_FEATURES = PRICE_CATEGORICAL + PRICE_NUMERIC

FURNISHING_VALUES = {"furnished", "semi-furnished", "unfurnished", "unknown"}
PROPERTY_TYPES = {"apartment", "studio", "independent_house", "other"}


def normalize_furnishing(value: str | None) -> str:
    if not value:
        return "unknown"
    v = str(value).strip().lower().replace("_", "-").replace(" ", "-")
    if v in ("semifurnished", "semi"):
        v = "semi-furnished"
    return v if v in FURNISHING_VALUES else "unknown"


def normalize_property_type(value: str | None) -> str:
    if not value:
        return "apartment"
    v = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {"flat": "apartment", "residential_apartment": "apartment", "1rk": "studio",
               "rk": "studio", "house": "independent_house", "villa": "independent_house",
               "independent_house/villa": "independent_house", "bungalow": "independent_house"}
    v = aliases.get(v, v)
    return v if v in PROPERTY_TYPES else "other"


def price_feature_frame(records: list[dict] | pd.DataFrame, known_groups: set[str] | None = None) -> pd.DataFrame:
    """Build the model input frame.

    Expects keys: locality_group, zone, furnishing, property_type, bhk, area_sqft, bathrooms.
    Unknown locality groups are mapped to "other" so the one-hot encoder never
    sees an unseen category it cannot explain.
    """
    df = pd.DataFrame(records).copy()
    for col in ("bathrooms", "area_sqft"):
        if col not in df:
            df[col] = np.nan
    out = pd.DataFrame(index=df.index)
    groups = df["locality_group"].fillna("other").astype(str)
    if known_groups is not None:
        groups = groups.where(groups.isin(known_groups), "other")
    out["locality_group"] = groups
    out["zone"] = df["zone"].fillna("Unknown").astype(str)
    out["furnishing"] = df["furnishing"].map(normalize_furnishing)
    out["property_type"] = df["property_type"].map(normalize_property_type)
    out["bhk"] = pd.to_numeric(df["bhk"], errors="coerce").clip(1, 6)
    area = pd.to_numeric(df["area_sqft"], errors="coerce")
    out["log_area"] = np.log(area.where(area > 0))
    out["bathrooms"] = pd.to_numeric(df["bathrooms"], errors="coerce")
    return out[PRICE_FEATURES]
