"""Server-rendered page shells. Data is loaded client-side via the JSON API."""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, request

from app.models import REPORT_REASONS
from app.security import current_user, page_login_required, safe_next

bp = Blueprint("pages", __name__)


@bp.app_context_processor
def inject_user():
    return {"current_user": current_user()}


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/login")
def login():
    if current_user():
        return redirect(safe_next(request.args.get("next")))
    return render_template("login.html", next=safe_next(request.args.get("next")))


@bp.get("/register")
def register():
    if current_user():
        return redirect(safe_next(None))
    return render_template("register.html", next=safe_next(request.args.get("next")))


@bp.get("/analyze")
@page_login_required
def analyze():
    return render_template("analyze.html")


@bp.get("/results/<int:analysis_id>")
def result(analysis_id: int):
    return render_template("result.html", analysis_id=analysis_id, report_reasons=REPORT_REASONS)


@bp.get("/history")
@page_login_required
def history():
    return render_template("history.html")


@bp.get("/market")
def market():
    return render_template("market.html")


@bp.get("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@bp.get("/methodology")
def methodology():
    return render_template("methodology.html")
