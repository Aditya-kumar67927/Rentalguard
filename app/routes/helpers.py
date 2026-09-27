from __future__ import annotations

from typing import Any

from flask import current_app, jsonify, request
from werkzeug.exceptions import BadRequest

from app.models import Listing, User
from app.services.analysis_service import AnalysisService


def service() -> AnalysisService:
    return current_app.extensions["analysis_service"]


class MalformedJSON(BadRequest):
    description = "Request body is not valid JSON."


def json_body() -> Any:
    """Parse the JSON body; malformed JSON raises MalformedJSON (400), handled centrally."""
    data = request.get_json(silent=True)
    if data is None:
        raise MalformedJSON()
    return data


def validation_error(errors: dict[str, str]):
    return jsonify(error="validation_error", message="Some fields are invalid.", fields=errors), 400


def not_found(what: str = "Resource"):
    return jsonify(error="not_found", message=f"{what} not found."), 404


def can_view_listing(listing: Listing, user: User | None) -> bool:
    """Dataset/demo listings are public; user listings are visible to their owner only."""
    if listing.source in ("dataset", "demo"):
        return True
    return user is not None and listing.user_id == user.id


def int_arg(name: str, default: int | None = None, lo: int | None = None, hi: int | None = None) -> int | None:
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    try:
        val = int(float(raw))
    except ValueError:
        return default
    if lo is not None:
        val = max(lo, val)
    if hi is not None:
        val = min(hi, val)
    return val
