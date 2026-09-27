from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.user import utcnow


class Analysis(db.Model):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    risk_score: Mapped[int] = mapped_column(index=True)
    risk_level: Mapped[str] = mapped_column(String(10), index=True)
    ml_probability: Mapped[float | None]
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    listing = relationship("Listing", lazy="joined")
    indicators = relationship("AnalysisIndicator", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (Index("ix_analyses_user_created", "user_id", "created_at"),)

    @property
    def result(self) -> dict:
        return json.loads(self.result_json)

    def to_dict(self, full: bool = True) -> dict:
        d = {"id": self.id, "listing_id": self.listing_id, "risk_score": self.risk_score,
             "risk_level": self.risk_level, "ml_probability": self.ml_probability,
             "created_at": self.created_at.isoformat() + "Z",
             "indicators": [i.code for i in self.indicators]}
        if full:
            d["result"] = self.result
            d["listing"] = self.listing.to_dict() if self.listing else None
        return d


class AnalysisIndicator(db.Model):
    """One row per triggered indicator -> 'top indicators' is a simple GROUP BY."""
    __tablename__ = "analysis_indicators"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(40), index=True)
    points: Mapped[int]
