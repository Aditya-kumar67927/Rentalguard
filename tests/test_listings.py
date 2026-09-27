import pytest

from tests.conftest import NORMAL_LISTING, SCAM_LISTING, register


def create(client, **overrides):
    return client.post("/api/listings", json={**NORMAL_LISTING, **overrides})


def test_create_requires_login(client):
    assert create(client).status_code == 401


def test_create_listing(auth_client):
    resp = create(auth_client, locality="andheri-w", rent="44,000", contact="+91 98765 43210")
    assert resp.status_code == 201
    listing = resp.get_json()["listing"]
    assert listing["locality"] == "Andheri West"
    assert listing["rent"] == 44000
    assert listing["has_contact"] is True
    assert "98765" not in str(listing)          # contact never echoed back
    assert "contact_hash" not in listing


@pytest.mark.parametrize("field,value", [
    ("rent", None), ("rent", 0), ("rent", -100), ("rent", "abc"), ("rent", True), ("rent", "NaN"),
    ("bhk", 0), ("bhk", 2.5), ("bhk", 11), ("bhk", "two"),
    ("area_sqft", -5), ("deposit", -1), ("locality", ""), ("locality", "x" * 200),
    ("furnishing", "luxurious"), ("property_type", "castle"),
])
def test_create_listing_validation(auth_client, field, value):
    resp = create(auth_client, **{field: value})
    assert resp.status_code == 400
    assert field in resp.get_json()["fields"]


def test_missing_description_is_allowed(auth_client):
    resp = create(auth_client, description=None)
    assert resp.status_code == 201
    assert resp.get_json()["listing"]["description"] == ""


def test_extremely_long_description_rejected(auth_client):
    resp = create(auth_client, description="a" * 5001)
    assert resp.status_code == 400
    assert "description" in resp.get_json()["fields"]


def test_request_size_limit(auth_client):
    resp = create(auth_client, description="a" * 70_000)
    assert resp.status_code == 413


def test_malformed_json(auth_client):
    resp = auth_client.post("/api/listings", data="{not json", content_type="application/json")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "malformed_json"


def test_non_object_json(auth_client):
    resp = auth_client.post("/api/listings", json=[1, 2, 3])
    assert resp.status_code == 400


def test_get_listing_privacy(client):
    register(client, email="a@example.com")
    lid = create(client).get_json()["listing"]["id"]
    assert client.get(f"/api/listings/{lid}").status_code == 200
    client.post("/api/auth/logout", json={})
    assert client.get(f"/api/listings/{lid}").status_code == 404        # anonymous
    register(client, email="b@example.com")
    assert client.get(f"/api/listings/{lid}").status_code == 404        # another user
    assert client.get("/api/listings/999999").status_code == 404


def test_search_filter_sort(auth_client):
    auth_client.post("/api/analyze", json=NORMAL_LISTING)
    auth_client.post("/api/analyze", json=SCAM_LISTING)
    auth_client.post("/api/analyze", json={**NORMAL_LISTING, "locality": "Powai", "bhk": 3, "rent": 90000})

    items = auth_client.get("/api/listings?scope=mine&sort=risk_desc").get_json()["items"]
    scores = [i["latest_risk_score"] for i in items]
    assert scores == sorted(scores, reverse=True)

    rents = [i["rent"] for i in auth_client.get("/api/listings?sort=rent_asc").get_json()["items"]]
    assert rents == sorted(rents)

    assert auth_client.get("/api/listings?q=powai").get_json()["total"] == 1
    assert auth_client.get("/api/listings?bhk=3").get_json()["total"] == 1
    assert auth_client.get("/api/listings?min_rent=40000&max_rent=50000").get_json()["total"] == 1
    very_high = auth_client.get("/api/listings?risk_level=VERY_HIGH").get_json()
    assert very_high["total"] == 1 and very_high["items"][0]["rent"] == 9000


def test_search_rejects_bad_parameters(auth_client):
    assert auth_client.get("/api/listings?sort=drop_table").status_code == 400
    assert auth_client.get("/api/listings?risk_level=EXTREME").status_code == 400
    assert auth_client.get("/api/listings?scope=everything").status_code == 400


def test_search_is_injection_safe(auth_client):
    create(auth_client)
    resp = auth_client.get("/api/listings?q=' OR 1=1 --")
    assert resp.status_code == 200 and resp.get_json()["total"] == 0
    resp = auth_client.get("/api/listings?q=%25")      # SQL wildcard is escaped
    assert resp.get_json()["total"] == 0


def test_market_scope_is_public_and_empty_db_ok(client):
    data = client.get("/api/listings?scope=market").get_json()
    assert data["total"] == 0 and data["items"] == []
    assert client.get("/api/listings?scope=mine").status_code == 401


def test_locality_autocomplete(client):
    items = client.get("/api/localities?q=andh").get_json()["items"]
    assert items and items[0]["display"] == "Andheri West"
    assert client.get("/api/localities?q=").get_json()["items"] == []


def test_reports(auth_client):
    lid = create(auth_client).get_json()["listing"]["id"]
    bad = auth_client.post("/api/reports", json={"listing_id": lid, "reason": "because"})
    assert bad.status_code == 400
    ok = auth_client.post("/api/reports", json={"listing_id": lid, "reason": "price_too_good", "details": "x"})
    assert ok.status_code == 201
    dup = auth_client.post("/api/reports", json={"listing_id": lid, "reason": "other"})
    assert dup.status_code == 409
    assert auth_client.post("/api/reports", json={"listing_id": 424242, "reason": "other"}).status_code == 404


def test_reports_raise_risk_on_reanalysis(auth_client):
    first = auth_client.post("/api/analyze", json=NORMAL_LISTING).get_json()["analysis"]
    auth_client.post("/api/reports", json={"listing_id": first["listing_id"], "reason": "owner_unreachable"})
    second = auth_client.post("/api/analyze", json={"listing_id": first["listing_id"]}).get_json()["analysis"]
    assert "listing_reported" in second["indicators"]
    assert second["risk_score"] > first["risk_score"]
