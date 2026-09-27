"""Download the raw Mumbai rental dataset into data/raw/.

Source: public GitHub repository ``baldsatan/mumbai-rental-data-analysis``
(99acres.com Mumbai rental listings collected on 2018-07-16 by the repo author).
The URL is pinned to a commit SHA so the download is reproducible.

The raw file is never modified after download. See docs/dataset.md for
provenance, licensing notes and limitations.

Usage:
    python scripts/download_data.py            # download if missing, then profile
    python scripts/download_data.py --force    # re-download
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
RAW_FILE = RAW_DIR / "mumbai_99acres_rent_2018.csv"

COMMIT = "40caf19f49a3f8b01b9783b979273eb29f982b9e"
URL = (
    "https://raw.githubusercontent.com/baldsatan/mumbai-rental-data-analysis/"
    f"{COMMIT}/16-Jul-99acres-mumbai-rental-data.csv"
)

MANUAL_INSTRUCTIONS = f"""
Automatic download failed. Manual procedure:
  1. Open https://github.com/baldsatan/mumbai-rental-data-analysis
  2. Download '16-Jul-99acres-mumbai-rental-data.csv'
  3. Save it as: {RAW_FILE}
  4. Re-run: python scripts/download_data.py
"""


def download(force: bool = False) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if RAW_FILE.exists() and not force:
        print(f"[download] raw file already present: {RAW_FILE}")
        return RAW_FILE
    print(f"[download] fetching {URL}")
    try:
        resp = requests.get(URL, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[download] ERROR: {exc}")
        print(MANUAL_INSTRUCTIONS)
        sys.exit(1)
    tmp = RAW_FILE.with_suffix(".part")
    tmp.write_bytes(resp.content)
    tmp.replace(RAW_FILE)
    return RAW_FILE


def profile(path: Path) -> None:
    size_mb = path.stat().st_size / 1_048_576
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    df = pd.read_csv(path, encoding="utf-8", encoding_errors="replace")
    print(f"\nFile      : {path.relative_to(ROOT)}")
    print(f"Size      : {size_mb:.2f} MB")
    print(f"SHA-256   : {sha256}")
    print(f"Rows      : {len(df):,}")
    print(f"Columns   : {len(df.columns)}")
    print(f"Duplicate rows (exact): {int(df.duplicated().sum()):,}")
    print("\nColumn                 dtype      missing")
    for col in df.columns:
        print(f"  {col:<22} {str(df[col].dtype):<10} {int(df[col].isna().sum()):>6}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    args = parser.parse_args()
    profile(download(force=args.force))


if __name__ == "__main__":
    main()
