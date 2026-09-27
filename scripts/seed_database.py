"""Create tables and load reference + demo listings, each scored by the risk engine.

    python scripts/seed_database.py                 # dataset + demo, analyzed
    python scripts/seed_database.py --limit 500     # quicker: only the first 500 dataset rows
    python scripts/seed_database.py --demo-only     # only the synthetic demo listings
    python scripts/seed_database.py --reset         # drop all tables first (destroys user data!)

Idempotent: listings whose external_id already exists are skipped.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from sqlalchemy import select  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Listing  # noqa: E402

DATA = ROOT / "data" / "processed" / "listings_clean.csv"
DEMO = ROOT / "data" / "demo" / "demo_listings.json"
BATCH = 250


def _none(v):
    return None if pd.isna(v) else v


def seed_dataset(service, limit: int | None, analyze: bool) -> int:
    if not DATA.exists():
        print("[seed] processed dataset missing - run scripts/clean_data.py first; skipping")
        return 0
    df = pd.read_csv(DATA)
    if limit:
        df = df.head(limit)
    existing = set(db.session.scalars(select(Listing.external_id).where(Listing.source == "dataset")))
    todo = df[~df.listing_id.isin(existing)]
    print(f"[seed] dataset: {len(existing)} already present, inserting {len(todo)}")
    t0 = time.time()
    for i, r in enumerate(todo.itertuples(), 1):
        listing = Listing(
            source="dataset", external_id=r.listing_id, locality=r.locality, locality_key=r.locality_key,
            locality_group=r.locality_group, zone=r.zone, rent=int(r.rent), deposit=_none(r.deposit) and int(r.deposit),
            bhk=float(r.bhk), area_sqft=_none(r.area_sqft), bathrooms=_none(r.bathrooms) and int(r.bathrooms),
            furnishing=r.furnishing, property_type=r.property_type,
            description=r.description if isinstance(r.description, str) else "",
            contact_hash=_none(r.contact_hash))
        db.session.add(listing)
        db.session.flush()
        if analyze:
            service.analyze(listing, None, commit=False)
        if i % BATCH == 0:
            db.session.commit()
            rate = i / (time.time() - t0)
            print(f"  {i}/{len(todo)} ({rate:.0f}/s, ~{(len(todo) - i) / rate:.0f}s left)")
    db.session.commit()
    return len(todo)


def seed_demo(service, analyze: bool) -> int:
    payload = json.loads(DEMO.read_text(encoding="utf-8"))
    n = 0
    for item in payload["listings"]:
        ext = f"DEMO-{item['key']}"
        if db.session.scalar(select(Listing.id).where(Listing.external_id == ext)):
            continue
        data = {k: item.get(k) for k in ("locality", "rent", "deposit", "bhk", "area_sqft", "bathrooms",
                                         "furnishing", "property_type", "description")}
        listing = service.create_listing(data, None, source="demo")
        listing.external_id = ext
        db.session.flush()
        if analyze:
            service.analyze(listing, None, commit=False)
        n += 1
    db.session.commit()
    print(f"[seed] demo: inserted {n} synthetic demo listings")
    return n


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=int(os.environ.get("SEED_LIMIT", "0")) or None)
    parser.add_argument("--demo-only", action="store_true")
    parser.add_argument("--no-analyze", action="store_true")
    parser.add_argument("--reset", action="store_true", help="drop and recreate all tables")
    args = parser.parse_args()

    app = create_app(os.environ.get("APP_ENV", "development"))
    with app.app_context():
        if args.reset:
            db.drop_all()
        db.create_all()
        service = app.extensions["analysis_service"]
        print(f"[seed] database: {db.engine.url.render_as_string(hide_password=True)}")
        print(f"[seed] artifacts: {service.status}")
        # Demo listings first so the dataset analysis can already see them as duplicates.
        seed_demo(service, not args.no_analyze)
        if not args.demo_only:
            seed_dataset(service, args.limit, not args.no_analyze)
        total = db.session.scalar(select(db.func.count(Listing.id)))
        print(f"[seed] done - {total} listings in database")


if __name__ == "__main__":
    main()
