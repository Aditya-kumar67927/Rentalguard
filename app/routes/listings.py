from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import REPORT_REASONS, Listing, Report
from app.routes.helpers import can_view_listing, int_arg, json_body, not_found, service, validation_error
from app.security import api_login_required, current_user
from app.utils.locality import locality_key
from app.validation import ValidationError, validate_listing

bp = Blueprint("listings", __name__, url_prefix="/api")

RISK_LEVELS = ("LOW", "MODERATE", "HIGH", "VERY_HIGH")
SORTS = {
    "risk_desc": (Listing.latest_risk_score.desc().nulls_last(), Listing.id.desc()),
    "risk_asc": (Listing.latest_risk_score.asc().nulls_last(), Listing.id.asc()),
    "rent_desc": (Listing.rent.desc(), Listing.id.desc()),
    "rent_asc": (Listing.rent.asc(), Listing.id.asc()),
    "newest": (Listing.created_at.desc(), Listing.id.desc()),
}


@bp.post("/listings")
@api_login_required
def create_listing():
    try:
        data = validate_listing(json_body())
    except ValidationError as exc:
        return validation_error(exc.errors)
    listing = service().create_listing(data, current_user())
    db.session.commit()
    return jsonify(listing=listing.to_dict()), 201


@bp.get("/listings")
def search_listings():
    """Search / filter / sort. scope=mine (own listings, login required) or market (dataset + demo)."""
    user = current_user()
    scope = request.args.get("scope", "mine" if user else "market")
    stmt = select(Listing)
    if scope == "mine":
        if user is None:
            return jsonify(error="authentication_required", message="Please log in."), 401
        stmt = stmt.where(Listing.user_id == user.id)
    elif scope == "market":
        stmt = stmt.where(Listing.source.in_(("dataset", "demo")))
    else:
        return validation_error({"scope": "Must be 'mine' or 'market'."})

    q = (request.args.get("q") or "").strip()[:80]
    if q:
        key = locality_key(q)
        # Prefix match on the indexed normalised key; ORM parameters prevent SQL injection
        stmt = stmt.where(or_(Listing.locality_key.startswith(key, autoescape=True),
                              Listing.locality_group.startswith(key, autoescape=True)))
    bhk = int_arg("bhk", lo=1, hi=10)
    if bhk:
        stmt = stmt.where(Listing.bhk >= 5) if bhk >= 5 else stmt.where(Listing.bhk == bhk)
    min_rent, max_rent = int_arg("min_rent", lo=0), int_arg("max_rent", lo=0)
    if min_rent:
        stmt = stmt.where(Listing.rent >= min_rent)
    if max_rent:
        stmt = stmt.where(Listing.rent <= max_rent)
    level = (request.args.get("risk_level") or "").upper()
    if level:
        if level not in RISK_LEVELS:
            return validation_error({"risk_level": f"Must be one of {', '.join(RISK_LEVELS)}."})
        stmt = stmt.where(Listing.latest_risk_level == level)

    sort = request.args.get("sort", "newest" if scope == "mine" else "risk_desc")
    if sort not in SORTS:
        return validation_error({"sort": f"Must be one of {', '.join(SORTS)}."})
    per_page = int_arg("per_page", 20, lo=1, hi=100)
    page = int_arg("page", 1, lo=1, hi=10_000)
    total = db.session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.session.scalars(stmt.order_by(*SORTS[sort]).limit(per_page).offset((page - 1) * per_page)).all()
    return jsonify(items=[r.to_dict(include_description=False) for r in rows], total=total, page=page,
                   per_page=per_page, pages=max(1, -(-total // per_page)), sort=sort, scope=scope)


@bp.get("/listings/<int:listing_id>")
def get_listing(listing_id: int):
    listing = db.session.get(Listing, listing_id)
    if listing is None or not can_view_listing(listing, current_user()):
        return not_found("Listing")
    reports = db.session.scalar(select(func.count(Report.id)).where(Report.listing_id == listing.id))
    return jsonify(listing=listing.to_dict(), reports=reports)


@bp.get("/listings/<int:listing_id>/similar")
def similar_listings(listing_id: int):
    listing = db.session.get(Listing, listing_id)
    user = current_user()
    if listing is None or not can_view_listing(listing, user):
        return not_found("Listing")
    k = int_arg("k", 5, lo=1, hi=20)
    return jsonify(listing_id=listing.id, similar=service().similar(listing, user, top_k=k))


@bp.get("/localities")
def localities():
    q = (request.args.get("q") or "")[:60]
    limit = int_arg("limit", 8, lo=1, hi=20)
    return jsonify(items=current_app.extensions["locality_index"].prefix(q, limit))


@bp.post("/reports")
@api_login_required
def create_report():
    body = json_body()
    if not isinstance(body, dict):
        return validation_error({"_body": "Expected a JSON object."})
    errors = {}
    try:
        listing_id = int(body.get("listing_id"))
    except (TypeError, ValueError):
        listing_id = None
        errors["listing_id"] = "A valid listing id is required."
    reason = body.get("reason")
    if reason not in REPORT_REASONS:
        errors["reason"] = f"Must be one of: {', '.join(REPORT_REASONS)}."
    details = body.get("details") or ""
    if not isinstance(details, str) or len(details) > 1000:
        errors["details"] = "Must be text of at most 1,000 characters."
    if errors:
        return validation_error(errors)
    user = current_user()
    listing = db.session.get(Listing, listing_id)
    if listing is None or not can_view_listing(listing, user):
        return not_found("Listing")
    report = Report(listing_id=listing.id, user_id=user.id, reason=reason, details=details.strip())
    db.session.add(report)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(error="already_reported", message="You have already reported this listing."), 409
    return jsonify(report=report.to_dict()), 201
