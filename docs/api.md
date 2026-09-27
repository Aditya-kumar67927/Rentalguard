# REST API

Base path `/api`. All responses are JSON. Errors have the shape:

```json
{"error": "validation_error", "message": "Some fields are invalid.", "fields": {"rent": "Must be between 500 and 5,000,000."}}
```

**Request rules for state-changing calls (POST):**
* The body must be sent with `Content-Type: application/json`. Otherwise the response is 415.
* Requests from a foreign `Origin` are rejected with 403.
* Bodies over 64 KB are rejected with 413.
* Malformed JSON returns 400 `malformed_json`.

**Authentication:** a session cookie set by `/api/auth/login` or `/api/auth/register`.

| Status | Meaning |
|---|---|
| 200 / 201 | OK / created |
| 400 | `validation_error`, `malformed_json` |
| 401 | `authentication_required`, `invalid_credentials` |
| 404 | `not_found`. Also returned for resources owned by another user, so their existence is not revealed |
| 409 | `email_taken`, `already_reported` |
| 413 | `request_entity_too_large` |
| 415 | `unsupported_media_type` |
| 429 | `too_many_attempts` (login rate limit) |
| 500 | `internal_error` (no stack trace) |

---

## Health & model

### `GET /api/health`
```json
{"status": "ok", "database": true, "version": "1.0.0",
 "artifacts": {"price_baselines": true, "price_model": true, "duplicate_index": true, "contact_stats": true, "risk_model": true}}
```
Returns 503 with `"status": "degraded"` if the database is unreachable.

### `GET /api/model/info`
The selected models, their test metrics, rule and peer baselines, and top permutation importances (from `ml_models/metrics.json`).

## Authentication

| Method & path | Body | Response |
|---|---|---|
| `POST /api/auth/register` | `{"name", "email", "password"}` (password ≥ 8 chars, letters and digits) | 201 `{"user": {...}}` and logs in |
| `POST /api/auth/login` | `{"email", "password"}` | 200 `{"user": {...}}` |
| `POST /api/auth/logout` | `{}` | 200 `{"ok": true}` |
| `GET /api/auth/me` | – | `{"user": {...} or null}` |

## Listings

### Listing fields (used by `POST /api/listings` and `POST /api/analyze`)

| Field | Required | Validation |
|---|---|---|
| `locality` | yes | 2–120 chars; normalised (`"Andheri-W"` → `"Andheri West"`) |
| `rent` | yes | 500 – 5,000,000 (`"35,000"` and `"₹35,000"` accepted) |
| `bhk` | yes | integer 1–10 |
| `deposit` | no | 0 – 100,000,000 |
| `area_sqft` | no | 100 – 20,000 |
| `bathrooms` | no | integer 0–10 |
| `furnishing` | no | `furnished`, `semi-furnished`, `unfurnished`, `unknown` |
| `property_type` | no | `apartment`, `studio`, `independent_house` |
| `description` | no | ≤ 5,000 chars |
| `contact` | no | ≤ 100 chars; stored only as a salted SHA-256 hash, never returned |

### `POST /api/listings` (login required)
Creates a listing in the user's history without analysing it. Returns 201 `{"listing": {...}}`.

### `GET /api/listings`
Search, filter and sort.

| Query param | Values |
|---|---|
| `scope` | `mine` (login required, default when logged in) or `market` (dataset + demo) |
| `q` | locality prefix (normalised) |
| `bhk` | 1–4, or 5 meaning 5+ |
| `min_rent`, `max_rent` | integers |
| `risk_level` | `LOW`, `MODERATE`, `HIGH`, `VERY_HIGH` |
| `sort` | `risk_desc`, `risk_asc`, `rent_asc`, `rent_desc`, `newest` |
| `page`, `per_page` | per_page ≤ 100 |

```json
{"items": [{"id": 12, "locality": "Andheri West", "rent": 8000, "bhk": 2.0, "latest_risk_score": 43,
            "latest_risk_level": "MODERATE", "latest_analysis_id": 12, ...}],
 "total": 1, "page": 1, "per_page": 20, "pages": 1, "sort": "risk_desc", "scope": "market"}
```

### `GET /api/listings/<id>`
Returns the listing and its report count. Dataset and demo listings are public. User listings are visible to their owner only.

### `GET /api/listings/<id>/similar?k=5`
Top-k similar listings from the duplicate index. Other users' private listings appear only as `{"private": true, "similarity": ...}`.

### `GET /api/localities?q=andh&limit=8`
Prefix autocomplete (binary search over sorted locality keys), ranked by listing count.

## Analysis

### `POST /api/analyze` (login required)
The body is either the listing fields (a new listing is created and analysed) or `{"listing_id": 5}` to re-analyse.
Returns 201:

```json
{"analysis": {
  "id": 42, "listing_id": 17, "risk_score": 99, "risk_level": "VERY_HIGH", "ml_probability": 0.95,
  "indicators": ["price_high", "payment_before_viewing", "..."],
  "listing": {...},
  "result": {
    "risk_score": 99, "risk_level": "VERY_HIGH", "risk_label": "Very high risk",
    "summary": "Potentially risky listing: multiple strong risk indicators were detected. ...",
    "rule_points": 80, "rule_points_capped": true,
    "contributions": [
      {"code": "price_high", "label": "Unusually low rent", "points": 25, "category": "price",
       "explanation": "Listed rent is 49% below the estimated comparable rent. ...",
       "evidence": ["₹30,000 vs expected ≈ ₹59,000"]}
    ],
    "price": {"actual_rent": 30000, "expected_rent": 59000, "expected_range": [51700, 67400],
              "deviation_percent": 49.2, "z_score": -3.4, "anomaly_level": "HIGH",
              "peer_group": {"level": "locality", "name": "Powai", "bhk": 2, "count": 292}, "...": "..."},
    "deposit": {"level": "NORMAL", "ratio": 3.33, "...": "..."},
    "text": {"urgency_score": 0.0, "advance_payment_detected": true, "no_viewing_detected": true,
             "owner_abroad_detected": true, "risk_phrases": ["no physical viewing", "..."], "...": "..."},
    "duplicates": {"max_similarity": 0.0, "level": "UNIQUE", "matches": [], "...": "..."},
    "contact": {"level": "NOT_PROVIDED", "...": "..."},
    "ml": {"available": true, "risk_probability": 0.95, "points": 19, "model_name": "gradient_boosting"},
    "features": {"price_z": -3.4, "...": "..."},
    "disclaimer": "RentalGuard provides an automated risk assessment ... not proof of fraud ..."
  }}}
```

The numbers in this example are illustrative. Run the demo to see live values.

### `GET /api/analysis/<id>`
The owner's analysis, or a public analysis of a dataset or demo listing.

### `GET /api/analyses?limit=50` (login required)
The user's analysis history, newest first.

## Reports

### `POST /api/reports` (login required)
```json
{"listing_id": 17, "reason": "asked_payment_before_viewing", "details": "optional, ≤ 1000 chars"}
```
Reasons: `asked_payment_before_viewing`, `fake_or_unavailable_property`, `owner_unreachable`, `price_too_good`,
`duplicate_listing`, `identity_mismatch`, `other`. One report per user per listing (409 on repeat).
Reports add risk points on re-analysis (listing +10; contact linked to reports +10).

## Dashboard

### `GET /api/dashboard/stats?scope=market|mine`
```json
{"scope": "market", "total_listings": 9146, "listings_analyzed": 9146, "average_rent": 60000, "median_rent": 45000,
 "average_risk_score": 3.1,
 "risk_distribution": {"LOW": 0, "MODERATE": 0, "HIGH": 0, "VERY_HIGH": 0},
 "bhk_distribution": {"1 BHK": 0, "2 BHK": 0},
 "rent_by_locality": [{"locality": "Powai", "count": 0, "avg_rent": 0}],
 "top_indicators": [{"code": "missing_area", "label": "Area not provided", "count": 0}],
 "highest_risk": [{"id": 1, "locality": "...", "risk_score": 99, "reports": 0, "analysis_id": 1}]}
```
The values shown are placeholders illustrating the shape.
