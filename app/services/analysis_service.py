"""Glue between the database and the (pure, stateless) risk engine."""
from __future__ import annotations

import json
import logging
import threading
from typing import Any

from sqlalchemy import func, select

from app.extensions import db
from app.models import Analysis, AnalysisIndicator, Listing, Report, User
from app.services.risk_engine import RiskEngine
from app.utils.locality import display_name, locality_key
from app.utils.privacy import hash_contact

log = logging.getLogger(__name__)


class AnalysisService:
    def __init__(self, engine: RiskEngine, status: dict[str, bool]):
        self.engine = engine
        self.status = status
        self._lock = threading.Lock()
        self._db_indexed = False

    # ------------------------------------------------------------------
    # Duplicate index: dataset rows are pre-indexed offline; user/demo listings
    # stored in the database are added lazily (once per process).
    # ------------------------------------------------------------------
    def _dup_meta(self, listing: Listing) -> dict[str, Any]:
        return {"id": listing.index_id, "rent": float(listing.rent), "bhk": listing.bhk,
                "locality": listing.locality, "locality_group": listing.locality_group,
                "zone": listing.zone, "source": listing.source}

    def ensure_db_indexed(self) -> None:
        dup = self.engine.duplicates
        if dup is None or self._db_indexed:
            return
        with self._lock:
            if self._db_indexed:
                return
            rows = db.session.scalars(select(Listing).where(Listing.source != "dataset")).all()
            for listing in rows:
                if listing.description:
                    dup.add(listing.description, self._dup_meta(listing))
            self._db_indexed = True
            log.info("indexed %d database listings for duplicate detection", len(rows))

    def _index_listing(self, listing: Listing) -> None:
        dup = self.engine.duplicates
        if dup is not None and listing.description and listing.source != "dataset":
            with self._lock:
                dup.add(listing.description, self._dup_meta(listing))

    # ------------------------------------------------------------------
    def create_listing(self, data: dict[str, Any], user: User | None, source: str = "user") -> Listing:
        if self.engine.price:
            loc = self.engine.price.resolve_location(data["locality"])
            key, group, zone, display = loc.key, loc.group, loc.zone, loc.display
        else:
            key = locality_key(data["locality"])
            group, zone, display = key, None, display_name(key)
        listing = Listing(
            user_id=user.id if user else None, source=source, locality=display or data["locality"],
            locality_key=key, locality_group=group, zone=zone, rent=data["rent"], deposit=data.get("deposit"),
            bhk=data["bhk"], area_sqft=data.get("area_sqft"), bathrooms=data.get("bathrooms"),
            furnishing=data.get("furnishing", "unknown"), property_type=data.get("property_type", "apartment"),
            description=data.get("description") or "",
            contact_hash=hash_contact(data["contact"]) if data.get("contact") else None,
        )
        db.session.add(listing)
        db.session.flush()   # assign id
        return listing

    def _db_counter(self, hashes: list[str]) -> dict[str, dict[str, int]]:
        if not hashes:
            return {}
        rows = db.session.execute(
            select(Listing.contact_hash, func.count(Listing.id), func.count(func.distinct(Listing.locality_group)))
            .where(Listing.contact_hash.in_(hashes), Listing.source != "dataset")
            .group_by(Listing.contact_hash)).all()
        out = {h: {"listings": n, "localities": m, "reports": 0} for h, n, m in rows}
        reports = db.session.execute(
            select(Listing.contact_hash, func.count(Report.id)).join(Report, Report.listing_id == Listing.id)
            .where(Listing.contact_hash.in_(hashes)).group_by(Listing.contact_hash)).all()
        for h, n in reports:
            out.setdefault(h, {"listings": 0, "localities": 0, "reports": 0})["reports"] = n
        return out

    def _link_matches(self, result: dict[str, Any], viewer_id: int | None) -> None:
        """Attach database ids to duplicate matches so the UI can link to them.

        Matches that are another user's private listing are redacted to just
        the similarity score - users never see each other's listings.
        """
        matches = result.get("duplicates", {}).get("matches", [])
        if not matches:
            return
        ext = [m["id"] for m in matches if not str(m["id"]).startswith("L")]
        mapping = dict(db.session.execute(select(Listing.external_id, Listing.id)
                                          .where(Listing.external_id.in_(ext))).all()) if ext else {}
        internal = [int(str(m["id"])[1:]) for m in matches
                    if str(m["id"]).startswith("L") and str(m["id"])[1:].isdigit()]
        owners = dict(db.session.execute(select(Listing.id, Listing.user_id)
                                         .where(Listing.id.in_(internal))).all()) if internal else {}
        for m in matches:
            mid = str(m["id"])
            if mid.startswith("L") and mid[1:].isdigit():
                lid = int(mid[1:])
                if m.get("source") == "user" and owners.get(lid) != viewer_id:
                    m.update({"listing_id": None, "locality": None, "zone": None, "rent": None, "bhk": None,
                              "id": "private", "private": True})
                    continue
                m["listing_id"] = lid
            else:
                m["listing_id"] = mapping.get(mid)

    def analyze(self, listing: Listing, user: User | None, commit: bool = True) -> Analysis:
        self.ensure_db_indexed()
        reports = db.session.scalar(select(func.count(Report.id)).where(Report.listing_id == listing.id)) or 0
        result = self.engine.assess(listing.to_input(), exclude_id=listing.index_id,
                                    db_counter=self._db_counter, listing_reports=reports)
        self._link_matches(result, user.id if user else None)
        analysis = Analysis(listing_id=listing.id, user_id=user.id if user else None,
                            risk_score=result["risk_score"], risk_level=result["risk_level"],
                            ml_probability=result["ml"].get("risk_probability"),
                            result_json=json.dumps(result, default=float))
        analysis.indicators = [AnalysisIndicator(code=c["code"], points=c["points"])
                               for c in result["contributions"]]
        db.session.add(analysis)
        db.session.flush()
        listing.latest_analysis_id = analysis.id
        listing.latest_risk_score = analysis.risk_score
        listing.latest_risk_level = analysis.risk_level
        if commit:
            db.session.commit()
        self._index_listing(listing)
        return analysis

    def similar(self, listing: Listing, viewer: User | None, top_k: int = 5) -> list[dict[str, Any]]:
        self.ensure_db_indexed()
        dup = self.engine.duplicates
        if dup is None or not listing.description:
            return []
        matches = dup.similar(listing.description, top_k=top_k, exclude_id=listing.index_id)
        result = {"duplicates": {"matches": [dict(m) for m in matches]}}
        self._link_matches(result, viewer.id if viewer else None)
        return [{k: m.get(k) for k in ("listing_id", "similarity", "locality", "zone", "bhk", "rent", "source",
                                       "private")}
                for m in result["duplicates"]["matches"]]
