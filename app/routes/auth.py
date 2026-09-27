from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import User
from app.routes.helpers import json_body, validation_error
from app.security import current_user, login_user, logout_user
from app.validation import ValidationError, validate_registration

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/register")
def register():
    try:
        data = validate_registration(json_body())
    except ValidationError as exc:
        return validation_error(exc.errors)
    if db.session.scalar(select(User.id).where(User.email == data["email"])):
        return jsonify(error="email_taken", message="An account with this e-mail already exists."), 409
    user = User(email=data["email"], name=data["name"])
    user.set_password(data["password"])
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:   # concurrent registration with the same e-mail
        db.session.rollback()
        return jsonify(error="email_taken", message="An account with this e-mail already exists."), 409
    login_user(user)
    return jsonify(user=user.to_dict()), 201


@bp.post("/login")
def login():
    body = json_body()
    if not isinstance(body, dict):
        return validation_error({"_body": "Expected a JSON object."})
    email = str(body.get("email") or "").strip().lower()
    password = body.get("password")
    if not email or not isinstance(password, str) or not password:
        return validation_error({"email": "E-mail and password are required."})

    limiter = current_app.extensions["login_limiter"]
    key = f"{request.remote_addr}|{email}"
    if limiter.blocked(key):
        return jsonify(error="too_many_attempts",
                       message="Too many failed login attempts. Please try again later."), 429

    user = db.session.scalar(select(User).where(User.email == email))
    if user is None or not user.check_password(password):
        limiter.hit(key)
        # Same message for unknown e-mail and wrong password (no account enumeration)
        return jsonify(error="invalid_credentials", message="Incorrect e-mail or password."), 401
    limiter.reset(key)
    login_user(user)
    return jsonify(user=user.to_dict())


@bp.post("/logout")
def logout():
    logout_user()
    return jsonify(ok=True)


@bp.get("/me")
def me():
    user = current_user()
    return jsonify(user=user.to_dict() if user else None)
