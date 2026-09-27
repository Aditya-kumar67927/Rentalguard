"""Configuration classes. Everything secret or environment-specific comes from
environment variables (see .env.example); nothing sensitive is hard-coded."""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        (ROOT / "instance").mkdir(exist_ok=True)
        return "sqlite:///" + (ROOT / "instance" / "rentalguard.db").as_posix()
    # Heroku-style URLs use the deprecated "postgres://" scheme
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    MODEL_DIR = Path(os.environ.get("MODEL_DIR", ROOT / "ml_models"))
    LOAD_ML = _bool("LOAD_ML", True)

    MAX_CONTENT_LENGTH = 64 * 1024            # request size limit (bytes)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    LOGIN_MAX_ATTEMPTS = 10                    # failed logins per sliding window
    LOGIN_WINDOW_SECONDS = 15 * 60


class DevelopmentConfig(Config):
    DEBUG = True
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-insecure-key-change-me"


class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    LOAD_ML = False
    LOGIN_MAX_ATTEMPTS = 5


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", True)


CONFIGS = {"development": DevelopmentConfig, "testing": TestingConfig, "production": ProductionConfig}
