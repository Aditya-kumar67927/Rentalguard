from __future__ import annotations

from flask import Blueprint, jsonify
from sqlalchemy import select

from app.extensions import db
from app.models import Analysis, Listing
from app.routes.helpers import can_view_listing, int_arg, json_body, not_found, service, validation_error
from app.security import api_login_required, current_user
from app.validation import ValidationError, validate_listing

bp = Blueprint("analysis", __name__, url_prefix="/api")


@bp.post("/analyze")
@api_login_required
def analyze():
    """Analyse an existing listing ({"listing_id": 5}) or a new one (listing fields).

    New listings are stored in the user's history together with the analysis.
    """
    body = json_body()
    user = current_user()
    if isinstance(body, dict) and "listing_id" in body:
        try:
            listing = db.session.get(Listing, int(body["listing_id"]))
        except (TypeError, ValueError):
            return validation_error({"listing_id": "Must be an integer."})
        if listing is None or not can_view_listing(listing, user):
            return not_found("Listing")
    else:
        try:
            data = validate_listing(body)
        except ValidationError as exc:
            return validation_error(exc.errors)
        listing = service().create_listing(data, user)
    analysis = service().analyze(listing, user)
    return jsonify(analysis=analysis.to_dict()), 201


@bp.get("/analysis/<int:analysis_id>")
def get_analysis(analysis_id: int):
    analysis = db.session.get(Analysis, analysis_id)
    user = current_user()
    if analysis is None:
        return not_found("Analysis")
    owned = user is not None and analysis.user_id == user.id
    public = analysis.user_id is None and analysis.listing.source in ("dataset", "demo")
    if not (owned or public):
        return not_found("Analysis")
    return jsonify(analysis=analysis.to_dict())


@bp.get("/analyses")
@api_login_required
def history():
    user = current_user()
    limit = int_arg("limit", 50, lo=1, hi=200)
    rows = db.session.scalars(select(Analysis).where(Analysis.user_id == user.id)
                              .order_by(Analysis.created_at.desc(), Analysis.id.desc()).limit(limit)).all()
    return jsonify(items=[{**a.to_dict(full=False), "listing": a.listing.to_dict(include_description=False)}
                          for a in rows])
