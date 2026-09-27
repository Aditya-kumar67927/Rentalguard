from app import create_app
from app.extensions import db
from tests.conftest import NORMAL_LISTING, SCAM_LISTING, register

DUP_TEXT = ("Sea facing fully furnished 2 BHK apartment on a high floor with a large balcony, Italian marble "
            "flooring, modular kitchen with chimney and hob, two air conditioners and a covered car park.")


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["artifacts"]["price_baselines"] is True


def test_analyze_requires_login(client):
    assert client.post("/api/analyze", json=NORMAL_LISTING).status_code == 401


def test_analyze_new_listing(auth_client):
    resp = auth_client.post("/api/analyze", json=SCAM_LISTING)
    assert resp.status_code == 201
    a = resp.get_json()["analysis"]
    r = a["result"]
    assert a["risk_level"] == "VERY_HIGH"
    assert 0 <= a["risk_score"] <= 100
    for section in ("price", "deposit", "text", "duplicates", "contact", "ml", "contributions"):
        assert section in r
    assert r["price"]["anomaly_level"] == "HIGH"
    assert r["text"]["advance_payment_detected"] is True
    assert a["listing"]["description"] == SCAM_LISTING["description"]


def test_analyze_existing_listing_and_history(auth_client):
    lid = auth_client.post("/api/listings", json=NORMAL_LISTING).get_json()["listing"]["id"]
    a1 = auth_client.post("/api/analyze", json={"listing_id": lid}).get_json()["analysis"]
    a2 = auth_client.post("/api/analyze", json={"listing_id": lid}).get_json()["analysis"]
    assert a1["listing_id"] == a2["listing_id"] == lid
    history = auth_client.get("/api/analyses").get_json()["items"]
    assert [h["id"] for h in history] == [a2["id"], a1["id"]]   # newest first
    listing = auth_client.get(f"/api/listings/{lid}").get_json()["listing"]
    assert listing["latest_analysis_id"] == a2["id"]


def test_analyze_bad_listing_id(auth_client):
    assert auth_client.post("/api/analyze", json={"listing_id": "abc"}).status_code == 400
    assert auth_client.post("/api/analyze", json={"listing_id": 12345}).status_code == 404


def test_analysis_is_private(client):
    register(client, email="owner@example.com")
    aid = client.post("/api/analyze", json=NORMAL_LISTING).get_json()["analysis"]["id"]
    assert client.get(f"/api/analysis/{aid}").status_code == 200
    client.post("/api/auth/logout", json={})
    register(client, email="other@example.com")
    assert client.get(f"/api/analysis/{aid}").status_code == 404
    assert client.get("/api/analysis/99999").status_code == 404


def test_duplicate_listing_detected_between_users_and_redacted(client):
    register(client, email="first@example.com")
    client.post("/api/analyze", json={**NORMAL_LISTING, "locality": "Andheri West", "rent": 95000,
                                      "description": DUP_TEXT})
    client.post("/api/auth/logout", json={})
    register(client, email="second@example.com")
    a = client.post("/api/analyze", json={**NORMAL_LISTING, "locality": "Kharghar", "rent": 16000,
                                          "description": DUP_TEXT}).get_json()["analysis"]
    dup = a["result"]["duplicates"]
    assert dup["possible_duplicate"] is True
    assert dup["conflicting_duplicate"] is True
    assert "duplicate_conflict" in a["indicators"]
    match = dup["matches"][0]
    assert match["private"] is True and match["rent"] is None and match["locality"] is None


def test_similar_endpoint(auth_client):
    lid = auth_client.post("/api/listings", json={**NORMAL_LISTING, "description": DUP_TEXT}).get_json()["listing"]["id"]
    auth_client.post("/api/analyze", json={**NORMAL_LISTING, "description": DUP_TEXT})
    sim = auth_client.get(f"/api/listings/{lid}/similar").get_json()["similar"]
    assert sim and sim[0]["similarity"] >= 0.9
    assert all(s["listing_id"] != lid for s in sim)


def test_dashboard_stats_empty_and_filled(auth_client):
    empty = auth_client.get("/api/dashboard/stats?scope=mine").get_json()
    assert empty["total_listings"] == 0 and empty["average_rent"] is None
    assert empty["risk_distribution"] == {"LOW": 0, "MODERATE": 0, "HIGH": 0, "VERY_HIGH": 0}
    auth_client.post("/api/analyze", json=NORMAL_LISTING)
    auth_client.post("/api/analyze", json=SCAM_LISTING)
    s = auth_client.get("/api/dashboard/stats?scope=mine").get_json()
    assert s["listings_analyzed"] == 2
    assert s["risk_distribution"]["VERY_HIGH"] == 1
    assert s["highest_risk"][0]["rent"] == 9000                 # heap-based top-k
    assert any(i["code"] == "price_high" for i in s["top_indicators"])
    assert s["bhk_distribution"] == {"2 BHK": 2}


def test_dashboard_scope_requires_login_for_mine(client):
    assert client.get("/api/dashboard/stats?scope=mine").status_code == 401
    assert client.get("/api/dashboard/stats?scope=market").status_code == 200


def test_app_runs_without_any_model_artifacts(tmp_path):
    """Missing model directory -> app starts, health reports it, analysis is rule-only."""
    app = create_app("testing", MODEL_DIR=tmp_path, LOAD_ML=True)
    with app.app_context():
        db.create_all()
        client = app.test_client()
        health = client.get("/api/health").get_json()
        assert health["artifacts"] == {"price_baselines": False, "price_model": False, "duplicate_index": False,
                                       "contact_stats": False, "risk_model": False}
        register(client)
        a = client.post("/api/analyze", json=SCAM_LISTING).get_json()["analysis"]
        assert a["result"]["price"]["available"] is False
        assert a["result"]["ml"]["available"] is False
        assert a["risk_score"] >= 50
        info = client.get("/api/model/info").get_json()
        assert info["price_model"] is None and info["risk_model"] is None
        db.drop_all()


def test_pages_render(client):
    for path in ("/", "/login", "/register", "/market", "/dashboard", "/methodology", "/results/1"):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert b"RentalGuard" in resp.data
    assert client.get("/does-not-exist").status_code == 404


def test_api_errors_are_json_without_stack_traces(client):
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404 and resp.is_json
    resp = client.delete("/api/health", json={})
    assert resp.status_code == 405 and resp.is_json
    assert b"Traceback" not in resp.data


def test_security_headers(client):
    resp = client.get("/")
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
