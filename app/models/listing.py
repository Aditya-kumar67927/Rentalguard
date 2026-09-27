from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.user import utcnow

SOURCES = ("user", "dataset", "demo")


class Listing(db.Model):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(10), default="user", index=True)
    external_id: Mapped[str | None] = mapped_column(String(32), unique=True)

    locality: Mapped[str] = mapped_column(String(120))
    locality_key: Mapped[str] = mapped_column(String(120), index=True)
    locality_group: Mapped[str | None] = mapped_column(String(120), index=True)
    zone: Mapped[str | None] = mapped_column(String(40))
    rent: Mapped[int] = mapped_column(index=True)
    deposit: Mapped[int | None]
    bhk: Mapped[float]
    area_sqft: Mapped[float | None]
    bathrooms: Mapped[int | None]
    furnishing: Mapped[str] = mapped_column(String(20), default="unknown")
    property_type: Mapped[str] = mapped_column(String(20), default="apartment")
    description: Mapped[str] = mapped_column(Text, default="")
    contact_hash: Mapped[str | None] = mapped_column(String(16), index=True)

    # Denormalised latest assessment -> filter/sort without joins, served by indexes
    latest_analysis_id: Mapped[int | None]
    latest_risk_score: Mapped[int | None] = mapped_column(index=True)
    latest_risk_level: Mapped[str | None] = mapped_column(String(10), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    __table_args__ = (
        Index("ix_listings_locality_bhk", "locality_key", "bhk"),
        Index("ix_listings_source_score", "source", "latest_risk_score"),
    )

    def to_input(self) -> dict:
        """Dictionary consumed by the risk engine."""
        return {"locality": self.locality, "rent": self.rent, "deposit": self.deposit, "bhk": self.bhk,
                "area_sqft": self.area_sqft, "bathrooms": self.bathrooms, "furnishing": self.furnishing,
                "property_type": self.property_type, "description": self.description,
                "contact_hash": self.contact_hash}

    @property
    def index_id(self) -> str:
        """Identifier used in the duplicate index."""
        return self.external_id or f"L{self.id}"

    def to_dict(self, include_description: bool = True) -> dict:
        d = {"id": self.id, "source": self.source, "external_id": self.external_id,
             "locality": self.locality, "locality_group": self.locality_group, "zone": self.zone,
             "rent": self.rent, "deposit": self.deposit, "bhk": self.bhk, "area_sqft": self.area_sqft,
             "bathrooms": self.bathrooms, "furnishing": self.furnishing, "property_type": self.property_type,
             "has_contact": self.contact_hash is not None,
             "latest_analysis_id": self.latest_analysis_id, "latest_risk_score": self.latest_risk_score,
             "latest_risk_level": self.latest_risk_level, "created_at": self.created_at.isoformat() + "Z"}
        if include_description:
            d["description"] = self.description
        return d
