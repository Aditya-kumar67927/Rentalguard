# Architecture

## 1. Overview

```text
                         ┌──────────────────────────── Browser ─────────────────────────────┐
                         │  HTML templates (Jinja) + CSS + vanilla JS (fetch API, Chart.js)  │
                         └───────────────┬──────────────────────────────────▲────────────────┘
                                         │ JSON over HTTPS (session cookie) │
┌────────────────────────────────────────▼──────────────────────────────────┴───────────────┐
│ Flask app (application factory, app/__init__.py)                                          │
│  security.py: CSRF guard (JSON + Origin), headers/CSP, sessions, login rate-limiter       │
│  routes/: pages · auth · listings · analysis · dashboard      validation.py (whitelist)   │
│                                   │                                                        │
│                   services/analysis_service.py  (DB ⇄ engine glue, privacy redaction)      │
│                                   │                                                        │
│  ┌──────────────────────── services/risk_engine.py ─────────────────────────┐             │
│  │ price_analyzer  text_analyzer  duplicate_detector  contact_analyzer  ML  │             │
│  └────┬───────────────┬──────────────────┬──────────────────┬──────────┬────┘             │
│       │ hash-map       │ regex + TF-IDF   │ MinHash-LSH +     │ hashed   │ joblib           │
│       │ baselines      │ (char n-grams)   │ TF-IDF cosine     │ counts   │ GradientBoosting │
└───────┼────────────────┼──────────────────┼───────────────────┼──────────┼─────────────────┘
        │                                    │                   │          │
   ml_models/price_baselines.json   ml_models/duplicate_index.joblib   ml_models/*.joblib
        ▲                                    ▲                   ▲          ▲
        └──────── scripts/create_features.py ┴───────────────────┘   app/ml/train.py
                               ▲                                            ▲
                    data/processed/listings_clean.csv ◄── scripts/clean_data.py ◄── data/raw (download_data.py)

            SQLAlchemy ORM ──► SQLite (dev/tests)  |  PostgreSQL (production), via DATABASE_URL
```

### Request lifecycle: `POST /api/analyze`

1. `security._csrf_guard` rejects non-JSON or cross-origin requests. `MAX_CONTENT_LENGTH` rejects bodies > 64 KB.
2. `api_login_required` checks the session.
3. `validation.validate_listing` whitelists and type-checks every field.
4. `AnalysisService.create_listing` normalises the locality (hash-map lookup), hashes the contact, and inserts a `Listing`.
5. `RiskEngine.assess` runs:
   * **price**: peer lookup, then an optional model estimate, then the robust z-score
   * **deposit**: ratio compared against zone percentiles
   * **text**: regex rules with a negation window, then the TF-IDF prototype similarity
   * **duplicates**: exact hash, LSH candidates, then the cosine ranking and conflict check
   * **contact**: dataset counts plus SQL counts and report counts
   * **ML**: probability from the features, adding at most 20 points
6. Contributions are sorted by points, and the score and level are computed.
7. An `Analysis` row is written, plus one `AnalysisIndicator` row per indicator. The listing's `latest_*` columns are denormalised for fast filtering and sorting. The listing is added to the in-memory duplicate index.
8. Another user's private listings appearing in duplicate matches are redacted to similarity only.

## 2. Modules

| Path | Responsibility |
|---|---|
| `app/__init__.py` | Application factory, error handlers (JSON for `/api`, HTML otherwise, never stack traces), CLI |
| `app/config.py` | Dev / testing / production config from environment variables |
| `app/security.py` | Sessions, login-required decorators, sliding-window rate limiter, CSRF guard, CSP and security headers, open-redirect guard |
| `app/validation.py` | Input validation for listings and registration |
| `app/models/` | `User`, `Listing`, `Analysis`, `AnalysisIndicator`, `Report` |
| `app/routes/` | Blueprints: `pages`, `auth`, `listings` (+ search, localities, reports), `analysis`, `dashboard` (+ health, model info) |
| `app/services/price_analyzer.py` | Expected rent, comparable range, robust anomaly score, deposit analysis |
| `app/services/text_analyzer.py` | Rule-based NLP and TF-IDF semantic similarity |
| `app/services/duplicate_detector.py` | MinHash LSH, TF-IDF cosine, exact-hash map, conflict detection |
| `app/services/contact_analyzer.py` | Contact repetition and report patterns on hashed identifiers |
| `app/services/risk_engine.py` | Explainable additive scoring |
| `app/services/registry.py` | Loads artifacts and degrades gracefully when any are missing |
| `app/ml/` | Preprocessing, features, synthetic data generator, training, prediction, loaders |
| `app/utils/` | Locality normalisation, money/deposit parsing, text cleaning and redaction, privacy hashing, search structures |
| `scripts/` | download → clean → EDA → features → seed; benchmark |

## 3. Database schema

```text
users(id PK, email UNIQUE idx, name, password_hash, created_at)
listings(id PK, user_id FK idx NULL, source idx ['user'|'dataset'|'demo'], external_id UNIQUE,
         locality, locality_key idx, locality_group idx, zone, rent idx, deposit, bhk, area_sqft, bathrooms,
         furnishing, property_type, description, contact_hash idx,
         latest_analysis_id, latest_risk_score idx, latest_risk_level idx, created_at idx)
         INDEX (locality_key, bhk), INDEX (source, latest_risk_score)
analyses(id PK, listing_id FK idx, user_id FK, risk_score idx, risk_level idx, ml_probability,
         result_json, created_at)  INDEX (user_id, created_at)
analysis_indicators(id PK, analysis_id FK idx, code idx, points)
reports(id PK, listing_id FK idx, user_id FK idx, reason, details, created_at)
         UNIQUE (listing_id, user_id)
```

Index rationale:
* `(locality_key, bhk)` serves locality search and peer queries.
* `latest_risk_score` and `rent` serve the sort options.
* `latest_risk_level` serves the level filter.
* `(user_id, created_at)` serves history.
* `analysis_indicators.code` serves the "top indicators" `GROUP BY`.

All queries go through the SQLAlchemy ORM with bound parameters, and the locality search uses `startswith(...,
autoescape=True)` so `%` and `_` are literal. This prevents SQL injection.

## 4. Data structures & algorithms

Every structure below solves a concrete problem in the app.

| Structure / algorithm | Where | Problem solved | Complexity |
|---|---|---|---|
| **Hash map** (dict) | `price_baselines.json` levels keyed `"locality|bhk"`; `localities` index; `contact_stats` keyed by hash; `DuplicateDetector.id_to_pos`; `exact` digest → ids | O(1) peer-group, locality, contact and exact-duplicate lookups instead of scanning 9k rows | O(1) average per lookup |
| **Hash set** | Text evidence de-dup `seen`; shingle sets; contact hash set; `indicator_codes`; `resolve_group` candidates | Unique indicators and phrases; Jaccard similarity on shingle sets | O(1) membership |
| **Sorting** | Risk contributions ranked by points; search results (`ORDER BY` on indexed columns); `LocalityIndex` built once from sorted keys | Explanations ordered by importance; listing ranking | O(k log k) for k ≤ 20 contributions; the DB uses B-tree indexes |
| **Binary search** (`bisect`) | `utils/search.py::LocalityIndex.prefix` | Autocomplete: find all keys with a prefix in a sorted array | O(log n + m), versus an O(n) scan |
| **Heap / priority queue** | `utils/search.py::top_k` (dashboard "verification priority queue"); `heapq.nlargest` in autocomplete | k highest-priority listings where priority = risk score + 10 × reports is computed in Python (a report join), streamed without sorting all n | O(n log k) time, O(k) memory |
| **Deque sliding window** | `security.SlidingWindowLimiter` | Login brute-force protection (≤ N failures per 15 min per IP and e-mail) | O(1) amortised per request |
| **String similarity: TF-IDF + cosine** | `duplicate_detector.py` (word 1–2 grams), `text_analyzer.py` (char 3–5 grams) | Duplicate ranking; paraphrase and misspelling detection | Sparse dot product, O(nnz) |
| **MinHash + LSH banding** | `duplicate_detector.MinHashLSH` | Avoids O(n²) all-pairs / O(n) per-query comparisons | Signature O(s · p) for s shingles and p=128 permutations; query O(b) bucket lookups + candidates |
| **Robust statistics** (median / MAD) | price baselines, outlier flag | Skewed rent distribution (skewness 4.8); means and SDs are distorted by luxury listings | O(n log n) offline |
| **Longest n-gram match against a set** | `utils/locality.resolve_group` | "hiranandani gardens powai" → "powai" | O(k²) for k tokens |

### O(n²) vs LSH: measured

`python scripts/benchmark_duplicates.py` on the 9,139 dataset descriptions (threshold cosine ≥ 0.9, laptop CPU,
results in `docs/benchmark_duplicates.json`):

| Method | Pairs scored | Pairs found | Recall | Time |
|---|---|---|---|---|
| Brute force (X · Xᵀ in blocks) | 41,756,091 (all n(n−1)/2) | 5,224 | 1.000 | 9.9 s |
| MinHash LSH (128 perms, 32 bands × 4 rows) | 959,164 (−97.7%) | 5,224 | 1.000 | 7.0 s |

**Interpretation:**
* LSH scored 43× fewer pairs with no loss of recall at this threshold.
* The wall-clock gain is small here because the brute force runs as a vectorised sparse matrix product in C, while the LSH candidate loop is pure Python.
* The asymptotic advantage matters as n grows. Brute-force cost grows with n², while LSH cost grows with the number of documents that share buckets.
* For the per-request path (one new listing against the index), LSH narrows 9,139 documents to about 200 candidates (measured on a 300-listing sample) before exact cosine scoring.
* Per-query recall at ≥ 0.9 on a 300-document sample was 90% (102/113 brute-force neighbours). The misses are short texts where TF-IDF cosine is high but word-3-gram Jaccard is low. This trade-off is accepted, and a test guards it (`tests/test_duplicate_detector.py::test_lsh_recall_matches_bruteforce`).

## 5. Scoring model (risk engine)

```text
risk_score = min(80, Σ rule points) + round(20 × ML probability)       ∈ [0, 100]
LOW < 25 ≤ MODERATE < 50 ≤ HIGH < 75 ≤ VERY_HIGH
```

| Indicator | Points | Indicator | Points |
|---|---|---|---|
| Unusually low rent (HIGH) | 25 | Unusual payment method | 15 |
| Rent below comparables (MODERATE) | 12 | Sensitive info (OTP / bank) request | 20 |
| Unusually high deposit (> max(p99, 10×)) | 15 | Restricted contact channel | 5 |
| Deposit above p95 | 8 | Urgency (10 × urgency score, min 3) | 3–10 |
| Payment before viewing | 20 | TF-IDF similarity to risky wording (only if no rule fired) | 8 |
| Advance / token request | 15 | Duplicate with conflicting price or zone | 15 |
| No physical viewing | 15 | Possible duplicate / repost | 3 |
| Owner abroad / unavailable | 10 | Contact linked to reported listings | 10 |
| Reported by users (this listing) | 10 | Widespread contact (≥ 20 listings, ≥ 8 localities) | 4 |
| Very short description | 5 | Area missing | 3 |

On the 9,139 real 2018 listings, the text rules fire on 13 (0.14%), all low-weight urgency wording. This is a
check on the false-positive rate of the rule layer.

Scored end-to-end with the full engine (`scripts/seed_database.py`), the 9,139 real listings come out
**9,004 LOW (98.5%), 134 MODERATE (1.5%), 1 HIGH, 0 VERY_HIGH**, with a mean score of 3.5. The listings are
unlabelled, so this is the tool's *flag rate* on ordinary market data, not a measured false-positive rate.

## 6. Security design

| Concern | Mitigation |
|---|---|
| Passwords | Werkzeug `generate_password_hash` (scrypt, random salt); plaintext never stored |
| Sessions | Signed cookie, `HttpOnly`, `SameSite=Lax`, `Secure` in production, cleared on login (fixation) |
| CSRF | State-changing `/api` calls must be `application/json` (no cross-site form or simple request can send that without a CORS preflight, which is never granted), plus an `Origin` host check and SameSite cookies |
| Brute force | Sliding-window limiter on failed logins, keyed by IP and e-mail |
| Account enumeration | Identical error for an unknown e-mail and a wrong password |
| Injection | ORM bound parameters; escaped `LIKE`; sort and filter values whitelisted |
| XSS | Jinja autoescaping; the front-end builds DOM with `textContent` only; strict CSP (no inline script or style); Chart.js pinned with SRI |
| Clickjacking | `X-Frame-Options: DENY`, `frame-ancestors 'none'` |
| Request size | `MAX_CONTENT_LENGTH = 64 KB`; description ≤ 5,000 chars |
| Error leakage | Central handlers return generic JSON/HTML; tracebacks only in server logs |
| Privacy | Contacts salted and hashed; phones and e-mails redacted from dataset text; users cannot see each other's listings or analyses (404, not 403) |
| Open redirect | `safe_next` only allows relative paths |
| Secrets | `.env` git-ignored; `.env.example` documents variables; production refuses to start without `SECRET_KEY` |

## 7. Deployment notes

* **Gunicorn** runs with one worker process and four threads. The duplicate index lives in process memory, and user listings are added to it incrementally, so multiple worker processes would each hold a partially different index. Horizontal scaling would move the index to a shared store such as Redis, or rebuild it periodically.
* **Artifacts** are loaded once at start-up (about 1–2 s). If any are missing, the corresponding analyzer is disabled and `/api/health` reports it.
