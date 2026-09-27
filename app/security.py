"""Authentication helpers, login rate limiting, CSRF mitigation and security headers."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from functools import wraps
from urllib.parse import urlparse

from flask import Flask, abort, g, jsonify, redirect, request, session, url_for

from app.extensions import db
from app.models import User


# ---------------------------------------------------------------------------
# Session-based authentication
# ---------------------------------------------------------------------------
def login_user(user: User) -> None:
    session.clear()                 # prevent session fixation
    session["user_id"] = user.id
    session.permanent = True


def logout_user() -> None:
    session.clear()


def current_user() -> User | None:
    # g lives as long as the *app* context, which can outlive a request, so the
    # cache is keyed by the session's user id to never serve a stale user.
    uid = session.get("user_id")
    cached = g.get("_rg_user")
    if cached is None or cached[0] != uid:
        cached = (uid, db.session.get(User, uid) if uid else None)
        g._rg_user = cached
    return cached[1]


def api_login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            return jsonify(error="authentication_required", message="Please log in."), 401
        return view(*args, **kwargs)
    return wrapper


def page_login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("pages.login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def safe_next(target: str | None) -> str:
    """Only allow relative redirects (open-redirect protection)."""
    if target and target.startswith("/") and not target.startswith("//") and not urlparse(target).netloc:
        return target
    return url_for("pages.analyze")


# ---------------------------------------------------------------------------
# Sliding-window rate limiter (deque per key: O(1) amortised per request)
# ---------------------------------------------------------------------------
class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, q: deque[float], now: float) -> None:
        while q and now - q[0] > self.window:
            q.popleft()

    def blocked(self, key: str) -> bool:
        with self._lock:
            q = self._events[key]
            self._prune(q, time.monotonic())
            return len(q) >= self.max_events

    def hit(self, key: str) -> None:
        with self._lock:
            q = self._events[key]
            now = time.monotonic()
            self._prune(q, now)
            q.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)


# ---------------------------------------------------------------------------
# Request hooks
# ---------------------------------------------------------------------------
CSP = ("default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
       "style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
       "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


def register_security(app: Flask) -> None:
    @app.before_request
    def _csrf_guard():
        """State-changing API calls must be JSON and same-origin.

        Browsers cannot send ``application/json`` cross-site without a CORS
        preflight (which this app never approves), and SameSite=Lax cookies
        are not attached to cross-site POSTs; the Origin check is defence in depth.
        """
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.path.startswith("/api/"):
            if not request.is_json:
                return jsonify(error="unsupported_media_type",
                               message="Content-Type must be application/json."), 415
            origin = request.headers.get("Origin")
            if origin and urlparse(origin).netloc != request.host:
                abort(403)

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Content-Security-Policy", CSP)
        if request.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp
