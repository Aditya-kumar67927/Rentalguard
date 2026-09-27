"""Clean the raw 99acres Mumbai rental dataset.

Input : data/raw/mumbai_99acres_rent_2018.csv   (never modified)
Output: data/processed/listings_clean.csv
        data/processed/cleaning_report.json

Every rule applied here is documented in docs/dataset.md ("Cleaning rules").
Legitimate but extreme listings are *flagged* (price_outlier) rather than
deleted, so downstream robust statistics can decide how to treat them.

Usage: python scripts/clean_data.py
"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.utils.locality import display_name, locality_key, resolve_group  # noqa: E402
from app.utils.money import extract_bathrooms, extract_deposit  # noqa: E402
from app.utils.privacy import hash_contact  # noqa: E402
from app.utils.text import clean_scraped_description, extract_contacts, redact_contacts  # noqa: E402

RAW_FILE = ROOT / "data" / "raw" / "mumbai_99acres_rent_2018.csv"
OUT_DIR = ROOT / "data" / "processed"
OUT_FILE = OUT_DIR / "listings_clean.csv"
REPORT_FILE = OUT_DIR / "cleaning_report.json"

MIN_GROUP_SIZE = 15          # a locality needs >= this many listings to become a "group"
MUMBAI_BBOX = (18.80, 19.60, 72.70, 73.40)  # lat_min, lat_max, lon_min, lon_max

ZONE_PATTERNS = [
    ("mumbai andheri-dahisar", "Andheri-Dahisar"),
    ("mumbai beyond thane", "Beyond Thane"),
    ("mumbai south west", "South West Mumbai"),
    ("mumbai south", "South Mumbai"),
    ("mumbai navi", "Navi Mumbai"),
    ("mumbai harbour", "Harbour"),
    ("mumbai thane", "Thane"),
    ("central mumbai suburbs", "Central Suburbs"),
]

PROPERTY_TYPE_MAP = {
    "Residential Apartment": "apartment",
    "Studio Apartment": "studio",
    "Independent House/Villa": "independent_house",
}
FURNISHING_MAP = {
    "furnished": "furnished",
    "semifurnished": "semi-furnished",
    "semi-furnished": "semi-furnished",
    "unfurnished": "unfurnished",
}


def read_mixed_encoding(path: Path) -> pd.DataFrame:
    """The raw file is mostly UTF-8 with some cp1252 lines; decode line by line."""
    lines = []
    for raw_line in path.read_bytes().splitlines(keepends=True):
        try:
            lines.append(raw_line.decode("utf-8"))
        except UnicodeDecodeError:
            lines.append(raw_line.decode("cp1252", errors="replace"))
    return pd.read_csv(io.StringIO("".join(lines)))


def parse_bhk(value: str) -> tuple[float | None, bool]:
    s = str(value).strip().upper()
    if s.endswith("RK"):
        return 1.0, True
    m = re.match(r"(\d+)\s*(BHK|BEDROOM)", s)
    if not m:
        return None, False
    n = int(m.group(1))
    return (float(n), False) if 1 <= n <= 10 else (None, False)


def parse_floor(value: str) -> float | None:
    s = str(value).strip().lower()
    if s.startswith(("ground", "g")):
        return 0.0
    if s.startswith(("lower basement", "upper basement", "basement")):
        return -1.0
    m = re.match(r"(\d+)", s)
    return float(m.group(1)) if m else None


def extract_zone(desc: str) -> str | None:
    low = desc.lower()
    for pat, zone in ZONE_PATTERNS:
        if pat in low:
            return zone
    return None


def robust_z(x: pd.Series) -> pd.Series:
    """Median/MAD z-score (0.6745 scales MAD to sigma for normal data)."""
    med = x.median()
    mad = (x - med).abs().median()
    if not mad or np.isnan(mad):
        return pd.Series(0.0, index=x.index)
    return 0.6745 * (x - med) / mad


def main() -> None:
    if not RAW_FILE.exists():
        sys.exit(f"Raw file missing: {RAW_FILE}\nRun: python scripts/download_data.py")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {}

    raw = read_mixed_encoding(RAW_FILE)
    report["rows_raw"] = len(raw)
    df = pd.DataFrame({
        "source_row": raw["sl no."],
        "society": raw["society"].astype(str).str.strip(),
        "property_type": raw["type"].map(PROPERTY_TYPE_MAP).fillna("other"),
        "location_raw": raw["location"].astype(str).str.strip(),
        "latitude": pd.to_numeric(raw["lattitude"], errors="coerce"),
        "longitude": pd.to_numeric(raw["longitude"], errors="coerce"),
        "area_sqft": pd.to_numeric(raw["built-up area"], errors="coerce"),
        "furnishing": raw["furnishing"].astype(str).str.strip().str.lower().map(FURNISHING_MAP).fillna("unknown"),
        "age_band": raw["age"].astype(str).str.strip().replace({"Not Mentioned": "unknown"}),
        "floor": raw["floor"].map(parse_floor),
        "total_floors": pd.to_numeric(raw["total floors"], errors="coerce"),
        "contact_hash": raw["dealer"].map(hash_contact),
        "posted_date": pd.to_datetime(raw["posted"], format="%b-%d-%Y", errors="coerce"),
        "rent": pd.to_numeric(raw["monthly rent"].astype(str).str.replace(r"[^\d.]", "", regex=True),
                              errors="coerce"),
        "n_photos": raw[["property photo", "society photo", "locality photo"]].sum(axis=1),
    })

    # ---- BHK --------------------------------------------------------------
    parsed = raw["bedrooms"].map(parse_bhk)
    df["bhk"] = parsed.map(lambda t: t[0])
    df["is_rk"] = parsed.map(lambda t: t[1])
    df.loc[df["is_rk"], "property_type"] = "studio"
    invalid_bhk = df["bhk"].isna()
    report["dropped_invalid_bhk"] = int(invalid_bhk.sum())
    df = df[~invalid_bhk]

    # ---- Rent -------------------------------------------------------------
    invalid_rent = df["rent"].isna() | (df["rent"] < 1000) | (df["rent"] > 2_000_000)
    report["dropped_invalid_rent"] = int(invalid_rent.sum())
    df = df[~invalid_rent].copy()

    # ---- Area: implausible values become NaN (row kept) -----------------
    per_room = df["area_sqft"] / df["bhk"]
    bad_area = (df["area_sqft"] < 120) | (df["area_sqft"] > 15000) | (per_room < 100)
    report["area_set_missing"] = int(bad_area.sum())
    df.loc[bad_area, "area_sqft"] = np.nan

    # ---- Coordinates outside Mumbai metropolitan bbox -> NaN ------------
    lat_min, lat_max, lon_min, lon_max = MUMBAI_BBOX
    bad_geo = df["latitude"].notna() & ~(df["latitude"].between(lat_min, lat_max)
                                         & df["longitude"].between(lon_min, lon_max))
    report["coordinates_set_missing"] = int(bad_geo.sum())
    df.loc[bad_geo, ["latitude", "longitude"]] = np.nan

    # ---- Description: artefacts, contacts (hashed, then redacted) -------
    desc = raw.loc[df.index, "description"].map(clean_scraped_description)
    df["desc_contact_hashes"] = desc.map(lambda t: ";".join(sorted({hash_contact(c) for c in extract_contacts(t)})))
    report["descriptions_with_contacts_redacted"] = int((df["desc_contact_hashes"] != "").sum())
    df["description"] = desc.map(redact_contacts)
    df["zone"] = df["description"].map(extract_zone)

    # ---- Deposit & bathrooms from description ---------------------------
    df["deposit"] = [extract_deposit(t, r) for t, r in zip(df["description"], df["rent"])]
    df["deposit_ratio"] = df["deposit"] / df["rent"]
    df["bathrooms"] = df["description"].map(extract_bathrooms)
    report["deposit_extracted"] = int(df["deposit"].notna().sum())
    report["bathrooms_extracted"] = int(df["bathrooms"].notna().sum())

    # ---- Locality normalisation ----------------------------------------
    df["locality_key"] = df["location_raw"].map(locality_key)
    counts = df["locality_key"].value_counts()
    known_groups = set(counts[counts >= MIN_GROUP_SIZE].index)
    df["locality_group"] = df["locality_key"].map(lambda k: resolve_group(k, known_groups))
    df["locality"] = df["locality_key"].map(display_name)
    report["unique_location_raw"] = int(df["location_raw"].nunique())
    report["unique_locality_key"] = int(df["locality_key"].nunique())
    report["unique_locality_group"] = int(df["locality_group"].nunique())

    # Fill zone from the majority zone of the locality group (hash-map lookup)
    zone_by_group = (df.dropna(subset=["zone"]).groupby("locality_group")["zone"]
                     .agg(lambda s: s.value_counts().index[0]).to_dict())
    missing_zone = df["zone"].isna()
    df.loc[missing_zone, "zone"] = df.loc[missing_zone, "locality_group"].map(zone_by_group)
    df["zone"] = df["zone"].fillna("Unknown")

    # ---- Repost de-duplication -----------------------------------------
    dup_key = ["locality_key", "bhk", "area_sqft", "rent", "contact_hash", "society"]
    df["n_reposts"] = df.groupby(dup_key, dropna=False)["source_row"].transform("size")
    before = len(df)
    df = df.drop_duplicates(subset=dup_key, keep="first").copy()
    report["dropped_reposts"] = before - len(df)

    # ---- Outlier *flag* (not deletion) ----------------------------------
    df["rent_per_sqft"] = df["rent"] / df["area_sqft"]
    log_ppsf = np.log(df["rent_per_sqft"])
    z = log_ppsf.groupby(df["zone"]).transform(robust_z)
    df["price_outlier"] = z.abs() > 3.5
    report["flagged_price_outliers"] = int(df["price_outlier"].sum())

    df = df.reset_index(drop=True)
    df.insert(0, "listing_id", [f"MUM99-{r:05d}" for r in df["source_row"]])
    df["posted_date"] = df["posted_date"].dt.date.astype("string")
    cols = ["listing_id", "source_row", "society", "property_type", "location_raw", "locality",
            "locality_key", "locality_group", "zone", "latitude", "longitude", "bhk", "is_rk",
            "area_sqft", "bathrooms", "furnishing", "age_band", "floor", "total_floors", "rent",
            "deposit", "deposit_ratio", "rent_per_sqft", "price_outlier", "contact_hash",
            "desc_contact_hashes", "n_photos", "n_reposts", "posted_date", "description"]
    df[cols].to_csv(OUT_FILE, index=False, encoding="utf-8")

    report["rows_clean"] = len(df)
    report["missing_after_cleaning"] = {c: int(df[c].isna().sum()) for c in cols if df[c].isna().any()}
    REPORT_FILE.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print(f"\nSaved {len(df):,} rows -> {OUT_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
