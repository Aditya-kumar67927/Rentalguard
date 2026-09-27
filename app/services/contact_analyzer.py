"""Contact-pattern analysis on pseudonymised (hashed) contact identifiers.

Repeated contacts are *normal* for brokers (in the dataset the top 10% of
contacts post ~45% of listings), so repetition alone is reported as an
informational pattern. It contributes to risk only when the same contact
appears across many unrelated localities, or when other users have reported
listings carrying that contact.
"""
from __future__ import annotations

from typing import Any, Callable

from app.utils.privacy import hash_contact
from app.utils.text import extract_contacts

WIDESPREAD_LISTINGS = 20
WIDESPREAD_LOCALITIES = 8

DbCounter = Callable[[list[str]], dict[str, dict[str, int]]]


class ContactAnalyzer:
    def __init__(self, dataset_stats: dict[str, dict[str, int]] | None = None):
        # hash map: contact hash -> {"listings": n, "localities": m}
        self.stats = dataset_stats or {}

    @staticmethod
    def contact_hashes(listing: dict[str, Any]) -> list[str]:
        raw = []
        if listing.get("contact"):
            raw.append(listing["contact"])
        raw.extend(extract_contacts(listing.get("description")))
        # set -> each identifier counted once even if repeated in the text
        hashes = {h for h in (hash_contact(r) for r in raw) if h}
        if listing.get("contact_hash"):          # already pseudonymised (dataset rows)
            hashes.add(str(listing["contact_hash"]))
        return sorted(hashes)

    def analyze(self, listing: dict[str, Any], db_counter: DbCounter | None = None) -> dict[str, Any]:
        hashes = self.contact_hashes(listing)
        if not hashes:
            return {"available": False, "level": "NOT_PROVIDED", "listings_per_contact": 0,
                    "localities": 0, "reported_count": 0,
                    "explanation": "No contact identifier provided, so contact patterns were not checked."}
        db = db_counter(hashes) if db_counter else {}
        best = {"listings": 0, "localities": 0, "reports": 0}
        for h in hashes:
            ds = self.stats.get(h, {})
            dbs = db.get(h, {})
            listings = ds.get("listings", 0) + dbs.get("listings", 0)
            localities = ds.get("localities", 0) + dbs.get("localities", 0)
            reports = dbs.get("reports", 0)
            if (listings, reports) > (best["listings"], best["reports"]):
                best = {"listings": listings, "localities": localities, "reports": reports}

        if best["reports"]:
            level = "REPORTED"
            msg = (f"Listings with this contact have been reported {best['reports']} time(s) by other users. "
                   "Further verification recommended.")
        elif best["listings"] >= WIDESPREAD_LISTINGS and best["localities"] >= WIDESPREAD_LOCALITIES:
            level = "WIDESPREAD"
            msg = (f"Repeated contact pattern detected: this contact appears on {best['listings']} listings across "
                   f"{best['localities']} localities. This is common for brokers but worth verifying.")
        elif best["listings"] >= 2:
            level = "REPEATED"
            msg = (f"Repeated contact pattern detected: this contact appears on {best['listings']} listings. "
                   "Repeated contacts are common for brokers and are not a risk signal on their own.")
        else:
            level = "UNIQUE"
            msg = "This contact does not appear on other known listings."
        return {"available": True, "level": level, "listings_per_contact": best["listings"],
                "localities": best["localities"], "reported_count": best["reports"],
                "hashed_ids": [h[:8] for h in hashes], "explanation": msg}
