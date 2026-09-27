from sqlalchemy import select

from app.extensions import db
from app.models import User
from app.security import safe_next
from tests.conftest import register


def test_register_logs_in_and_hashes_password(client, app):
    resp = register(client)
    assert resp.status_code == 201
    assert resp.get_json()["user"]["email"] == "user@example.com"
    user = db.session.scalar(select(User))
    assert user.password_hash != "password123"
    assert "password123" not in user.password_hash
    assert user.check_password("password123")
    assert client.get("/api/auth/me").get_json()["user"]["id"] == user.id


def test_register_normalises_email_and_rejects_duplicates(client):
    assert register(client, email="Person@Example.com").status_code == 201
    resp = register(client, email="person@example.com")
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "email_taken"


def test_register_validation(client):
    resp = client.post("/api/auth/register", json={"name": "", "email": "not-an-email", "password": "short"})
    assert resp.status_code == 400
    fields = resp.get_json()["fields"]
    assert {"name", "email", "password"} <= set(fields)
    resp = client.post("/api/auth/register", json={"name": "A", "email": "a@b.co", "password": "onlyletters"})
    assert "password" in resp.get_json()["fields"]


def test_login_logout_flow(client):
    register(client)
    client.post("/api/auth/logout", json={})
    assert client.get("/api/auth/me").get_json()["user"] is None
    bad = client.post("/api/auth/login", json={"email": "user@example.com", "password": "wrong-pass1"})
    assert bad.status_code == 401
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-pass1"})
    assert unknown.get_json()["message"] == bad.get_json()["message"]   # no account enumeration
    ok = client.post("/api/auth/login", json={"email": "USER@example.com", "password": "password123"})
    assert ok.status_code == 200
    assert client.get("/api/auth/me").get_json()["user"]["email"] == "user@example.com"


def test_login_rate_limited(client, app):
    register(client)
    client.post("/api/auth/logout", json={})
    for _ in range(app.config["LOGIN_MAX_ATTEMPTS"]):
        client.post("/api/auth/login", json={"email": "user@example.com", "password": "bad-password1"})
    resp = client.post("/api/auth/login", json={"email": "user@example.com", "password": "password123"})
    assert resp.status_code == 429


def test_protected_pages_redirect_to_login(client):
    resp = client.get("/history")
    assert resp.status_code == 302
    assert "/login?next=/history" in resp.headers["Location"]
    assert client.get("/api/analyses").status_code == 401


def test_session_cookie_flags(client):
    resp = register(client)
    cookie = resp.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_open_redirect_protection(app):
    with app.test_request_context():
        assert safe_next("/history") == "/history"
        assert safe_next("https://evil.example/") == "/analyze"
        assert safe_next("//evil.example/") == "/analyze"
        assert safe_next(None) == "/analyze"


def test_state_changing_api_requires_json(client):
    resp = client.post("/api/auth/login", data={"email": "a", "password": "b"})
    assert resp.status_code == 415


def test_cross_origin_post_rejected(client):
    resp = client.post("/api/auth/logout", json={}, headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
