from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.user import utcnow

REPORT_REASONS = ("asked_payment_before_viewing", "fake_or_unavailable_property", "owner_unreachable",
                  "price_too_good", "duplicate_listing", "identity_mismatch", "other")


class Report(db.Model):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(String(40))
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    # one report per user per listing -> no report spamming
    __table_args__ = (UniqueConstraint("listing_id", "user_id", name="uq_report_listing_user"),)

    def to_dict(self) -> dict:
        return {"id": self.id, "listing_id": self.listing_id, "reason": self.reason, "details": self.details,
                "created_at": self.created_at.isoformat() + "Z"}
