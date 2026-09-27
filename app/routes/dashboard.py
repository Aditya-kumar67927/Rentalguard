from __future__ import annotations

import statistics

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func, select

from app import __version__
from app.extensions import db
from app.ml.model_loader import METRICS, load_json
from app.models import AnalysisIndicator, Listing, Report
from app.routes.helpers import service, validation_error
from app.security import current_user
from app.utils.search import top_k

bp = Blueprint("dashboard", __name__, url_prefix="/api")

INDICATOR_LABELS = {
    "price_high": "Unusually low rent", "price_moderate": "Rent below comparables",
    "deposit_high": "Unusually high deposit", "deposit_elevated": "Deposit above typical",
    "payment_before_viewing": "Payment before viewing", "advance_payment": "Advance payment request",
    "no_viewing": "No physical viewing", "owner_away": "Owner abroad / unavailable",
    "unusual_payment": "Unusual payment method", "sensitive_info": "Sensitive info request",
    "off_platform": "Restricted contact channel", "urgency": "Urgency language",
    "semantic": "Resembles risky wording", "duplicate_conflict": "Duplicate with different details",
    "duplicate_repost": "Possible duplicate / repost", "contact_reported": "Contact linked to reports",
    "contact_widespread": "Widespread contact pattern", "listing_reported": "Reported by users",
    "short_description": "Very short description", "missing_area": "Area not provided",
    "ml_model": "ML risk estimate",
}


@bp.get("/health")
def health():
    try:
        db.session.execute(select(1))
        db_ok = True
    except Exception:
        db_ok = False
    status = service().status
    return jsonify(status="ok" if db_ok else "degraded", database=db_ok, artifacts=status,
                   version=__version__), (200 if db_ok else 503)


@bp.get("/dashboard/stats")
def stats():
    user = current_user()
    scope = request.args.get("scope", "mine" if user else "market")
    if scope == "mine":
        if user is None:
            return jsonify(error="authentication_required", message="Please log in."), 401
        where = [Listing.user_id == user.id]
    elif scope == "market":
        where = [Listing.source.in_(("dataset", "demo"))]
    else:
        return validation_error({"scope": "Must be 'mine' or 'market'."})

    analyzed = [*where, Listing.latest_risk_level.is_not(None)]
    total = db.session.scalar(select(func.count(Listing.id)).where(*where)) or 0
    n_analyzed = db.session.scalar(select(func.count(Listing.id)).where(*analyzed)) or 0
    rents = db.session.scalars(select(Listing.rent).where(*where)).all()
    avg_score = db.session.scalar(select(func.avg(Listing.latest_risk_score)).where(*analyzed))

    risk = dict(db.session.execute(select(Listing.latest_risk_level, func.count(Listing.id))
                                   .where(*analyzed).group_by(Listing.latest_risk_level)).all())
    bhk_rows = db.session.execute(select(Listing.bhk, func.count(Listing.id)).where(*where)
                                  .group_by(Listing.bhk)).all()
    bhk: dict[str, int] = {}
    for b, n in bhk_rows:        # hash map aggregation, 5+ BHK folded together
        label = "5+ BHK" if b >= 5 else f"{int(b)} BHK"
        bhk[label] = bhk.get(label, 0) + n
    bhk = dict(sorted(bhk.items()))

    loc_rows = db.session.execute(
        select(Listing.locality_group, func.count(Listing.id), func.avg(Listing.rent))
        .where(*where).group_by(Listing.locality_group)
        .order_by(func.count(Listing.id).desc()).limit(10)).all()
    by_locality = [{"locality": (g or "unknown").title(), "count": n, "avg_rent": round(float(a or 0))}
                   for g, n, a in loc_rows]

    ind_rows = db.session.execute(
        select(AnalysisIndicator.code, func.count(AnalysisIndicator.id))
        .join(Listing, Listing.latest_analysis_id == AnalysisIndicator.analysis_id)
        .where(*where, AnalysisIndicator.code != "ml_model")   # the ML estimate is not an indicator
        .group_by(AnalysisIndicator.code)
        .order_by(func.count(AnalysisIndicator.id).desc()).limit(10)).all()
    indicators = [{"code": c, "label": INDICATOR_LABELS.get(c, c), "count": n} for c, n in ind_rows]

    # Verification priority queue: risk score + 10 points per user report.
    report_counts = dict(db.session.execute(
        select(Report.listing_id, func.count(Report.id)).join(Listing, Listing.id == Report.listing_id)
        .where(*where).group_by(Report.listing_id)).all())
    candidates = db.session.execute(
        select(Listing.id, Listing.locality, Listing.bhk, Listing.rent, Listing.latest_risk_score,
               Listing.latest_risk_level, Listing.latest_analysis_id, Listing.source)
        .where(*analyzed, Listing.latest_risk_score >= 25)).all()
    top = top_k(candidates, 8, key=lambda r: r.latest_risk_score + 10 * report_counts.get(r.id, 0))
    top_items = [{"id": r.id, "locality": r.locality, "bhk": r.bhk, "rent": r.rent,
                  "risk_score": r.latest_risk_score, "risk_level": r.latest_risk_level,
                  "analysis_id": r.latest_analysis_id, "reports": report_counts.get(r.id, 0),
                  "source": r.source} for r in top]

    return jsonify(
        scope=scope, total_listings=total, listings_analyzed=n_analyzed,
        average_rent=round(statistics.fmean(rents)) if rents else None,
        median_rent=round(statistics.median(rents)) if rents else None,
        average_risk_score=round(float(avg_score), 1) if avg_score is not None else None,
        risk_distribution={lvl: risk.get(lvl, 0) for lvl in ("LOW", "MODERATE", "HIGH", "VERY_HIGH")},
        bhk_distribution=bhk, rent_by_locality=by_locality, top_indicators=indicators,
        highest_risk=top_items)


@bp.get("/model/info")
def model_info():
    metrics = load_json(current_app.config["MODEL_DIR"], METRICS) or {}
    pm, rm = metrics.get("price_model", {}), metrics.get("risk_model", {})

    def pick(section: dict) -> dict:
        sel = section.get("selected")
        return {"selected": sel, "test": section.get("models", {}).get(sel, {}).get("test"),
                "rows": section.get("rows"), "criterion": section.get("selection_criterion"),
                "importance": dict(list(section.get("permutation_importance", {}).items())[:8])}

    return jsonify(artifacts=service().status, generated_at=metrics.get("generated_at"),
                   price_model=pick(pm) if pm else None,
                   price_baseline=pm.get("models", {}).get("peer_median_baseline", {}).get("test") if pm else None,
                   risk_model=pick(rm) if rm else None,
                   risk_rule_baseline=rm.get("models", {}).get("rule_score_baseline", {}).get("test") if rm else None,
                   label_source=rm.get("label_source"))
