"""RentalGuard application factory."""
from __future__ import annotations

import logging
import os

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from app.config import CONFIGS
from app.extensions import db

__version__ = "1.0.0"


def create_app(config_name: str | None = None, **overrides) -> Flask:
    config_name = config_name or os.environ.get("FLASK_ENV_NAME") or os.environ.get("APP_ENV", "development")
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(CONFIGS[config_name])
    app.config.update(overrides)
    app.json.sort_keys = False   # keep meaningful key order (e.g. LOW -> VERY_HIGH) in API responses
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be set (see .env.example)")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db.init_app(app)

    from app import models  # noqa: F401  (register tables)
    from app.routes import register_blueprints
    from app.security import SlidingWindowLimiter, register_security
    from app.services.analysis_service import AnalysisService
    from app.services.registry import build_engine
    from app.utils.search import LocalityIndex

    engine, status = build_engine(app.config["MODEL_DIR"], load_ml=app.config["LOAD_ML"])
    app.extensions["analysis_service"] = AnalysisService(engine, status)
    app.extensions["locality_index"] = LocalityIndex.from_price_analyzer(engine.price)
    app.extensions["login_limiter"] = SlidingWindowLimiter(app.config["LOGIN_MAX_ATTEMPTS"],
                                                           app.config["LOGIN_WINDOW_SECONDS"])
    app.logger.info("artifacts loaded: %s", status)

    register_security(app)
    register_blueprints(app)
    register_error_handlers(app)
    register_cli(app)

    with app.app_context():
        db.create_all()
    return app


def register_error_handlers(app: Flask) -> None:
    def wants_json() -> bool:
        return request.path.startswith("/api/")

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        if wants_json():
            code = exc.name.lower().replace(" ", "_")
            message = "Request body too large." if exc.code == 413 else exc.description
            from app.routes.helpers import MalformedJSON
            if isinstance(exc, MalformedJSON):
                code = "malformed_json"
            return jsonify(error=code, message=message), exc.code
        return render_template("error.html", code=exc.code, title=exc.name,
                               message=exc.description), exc.code

    @app.errorhandler(Exception)
    def unhandled(exc: Exception):
        # Never leak stack traces to clients; log them server-side instead.
        app.logger.exception("unhandled error on %s %s", request.method, request.path)
        db.session.rollback()
        if wants_json():
            return jsonify(error="internal_error", message="An unexpected error occurred."), 500
        return render_template("error.html", code=500, title="Something went wrong",
                               message="An unexpected error occurred. Please try again."), 500


def register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db():
        """Create all database tables."""
        db.create_all()
        print("database initialised")
