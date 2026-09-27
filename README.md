# RentalGuard

**Analyze rental listings before you commit.**

RentalGuard is a Mumbai rental-listing risk analyzer. It compares a listing with 9,139 real Mumbai
rental listings and scans it for warning signs:
* unusually low rent or high deposits
* risky payment and pressure language
* cloned or duplicate listings
* repeated contacts

The output is an **explainable risk assessment**: a score from 0 to 100, a risk level, and every contributing
indicator with its evidence.

> RentalGuard never says a listing *is* a scam. It reports *potentially risky* characteristics and recommends
> further verification. Scores can be wrong in both directions.

---

## Problem

Rental fraud in Indian metros usually follows recognisable patterns:
* a flat listed far below market rent
* an "owner" who is abroad and cannot show it
* a request for a token amount or deposit *before* any viewing
* pressure to pay immediately
* a real listing's photos and text copied and reposted elsewhere at a lower price

Renters, often new to the city, have little data to judge whether a listing is unusual.

## Solution

RentalGuard runs five independent, explainable analyzers and one ML model:

| Analyzer | What it checks |
|---|---|
| **Price anomaly** | Expected rent from comparable listings: robust median rent per sq.ft by locality and BHK, with a fallback hierarchy, blended with a gradient-boosted regression model. Produces a robust z-score. |
| **Deposit** | The deposit-to-rent ratio compared with the zone's distribution (Mumbai median 4.4×). |
| **Text / NLP** | Rules with negation handling for advance payment, payment before viewing, no viewing, owner abroad, urgency, unusual payment channels and OTP requests. TF-IDF character n-grams catch paraphrases and misspellings. |
| **Duplicates** | Normalisation, then an exact hash, then MinHash LSH candidates, then TF-IDF cosine. Flags near-identical text that appears with a different price or zone. |
| **Contacts** | Salted SHA-256 hashed identifiers. Repetition across localities and user reports are reported as patterns, not accusations. |
| **ML classifier** | Gradient boosting over all the signals, trained on documented **synthetic** labels. Adds at most 20 of the 100 points. |

```text
risk_score = min(80, Σ indicator points) + round(20 × ML probability)
LOW 0–24 · MODERATE 25–49 · HIGH 50–74 · VERY_HIGH 75–100
```

## Features

* Register, log in, log out. Passwords are hashed and sessions are secure.
* Analyze a listing: a form with locality autocomplete, demo listings, a loading state and fetch-based submission (no page reload).
* Results:
  * score gauge, level and summary
  * a ranked list of indicators, each with its points, explanation and evidence
  * price range chart
  * deposit, text, duplicate, contact and ML panels
  * the description with the risky phrases highlighted
* Report a listing. Reports feed back into later risk scores.
* History of your own listings, with search by locality, filters (BHK, rent range, risk level) and sorting (risk, rent, date).
* Market explorer: the same search over the 9,139 reference listings and 7 demo listings, all pre-scored.
* Dashboard (Chart.js):
  * listings analyzed, average and median rent, average score
  * risk distribution
  * top indicators
  * rent by locality
  * BHK distribution
  * a heap-based verification priority queue
* Methodology page with live model metrics.
* REST API with validation, consistent JSON errors and no stack traces. See [`docs/api.md`](docs/api.md).
* Security:
  * CSRF guard
  * strict Content-Security-Policy
  * login rate limiting
  * 64 KB request limit
  * owner-only access to data
  * contact hashing and PII redaction

## Architecture

```text
 Browser (HTML/CSS/vanilla JS, Chart.js)
        │ fetch() JSON
        ▼
 Flask app factory ── security (CSRF, CSP, sessions, rate limit) ── validation
        │
 routes: pages · auth · listings · analysis · dashboard
        │
 AnalysisService ──► RiskEngine
                        ├─ PriceAnalyzer     (hash-map peer baselines + HistGradientBoosting)
                        ├─ TextAnalyzer      (regex rules + TF-IDF char n-grams)
                        ├─ DuplicateDetector (SHA-1 map + MinHash LSH + TF-IDF cosine)
                        ├─ ContactAnalyzer   (hashed-contact counts + SQL report counts)
                        └─ RiskModel         (GradientBoostingClassifier, joblib)
        │
 SQLAlchemy ORM ──► SQLite (default) / PostgreSQL (optional), switched via DATABASE_URL

 Offline pipeline: download_data → clean_data → eda → create_features → app.ml.train → seed_database
```

Details, DB schema, complexity analysis and security design: [`docs/architecture.md`](docs/architecture.md).

## Tech stack

| Layer | Technologies |
|---|---|
| Frontend | HTML5, CSS3 (custom design system, dark mode, responsive), vanilla JavaScript (Fetch API), Chart.js 4 |
| Backend | Python 3.14, Flask 3.1, Flask-SQLAlchemy / SQLAlchemy 2.0, Werkzeug security, python-dotenv, gunicorn |
| Database | SQLite (default, local dev and tests), PostgreSQL (optional via `DATABASE_URL`) |
| ML / data | pandas, NumPy, SciPy, scikit-learn 1.9 (TF-IDF, HistGradientBoosting, GradientBoosting, RandomForest, LogisticRegression, Ridge), joblib, matplotlib |
| Testing | pytest, Flask test client |
| DevOps | Git |

## Dataset

| | |
|---|---|
| Source | 99acres.com Mumbai rental listings collected **16 July 2018**, published on GitHub by `baldsatan` |
| URL | <https://github.com/baldsatan/mumbai-rental-data-analysis> (pinned to commit `40caf19`) |
| Accessed | 2026-09-24 |
| Size | 13,541 rows × 22 columns (10.6 MB) → **9,139** after cleaning and removing 4,402 reposts |
| Columns | society, type, location, lat/long, bedrooms, built-up area, furnishing, age, floor, dealer, posted date, monthly rent, media counts, description |
| Licence | **No licence stated** in the repository. Used here for non-commercial educational research only. The data is downloaded by script and **not redistributed** (git-ignored). Dealer names are hashed, and phones and e-mails are redacted. |
| Limitations | 2018 prices; one portal; broker-heavy; sparse long-tail localities; deposit and bathrooms parsed from text |

Full provenance, the alternatives evaluated, and all 15 cleaning rules: [`docs/dataset.md`](docs/dataset.md).
EDA plots and an auto-generated summary are in [`docs/eda/`](docs/eda/eda_summary.md).

## ML

**Price model (real data).** Target: log(rent). Features: locality group, zone, furnishing, property type, BHK, log(area), bathrooms. Results on a held-out 20% test split:

| Model | Median abs. % error | MAE | R² (log) |
|---|---|---|---|
| Peer-median baseline | 13.8% | ₹15,578 | 0.815 |
| Ridge | 12.7% | ₹12,164 | 0.921 |
| Random forest | 10.9% | ₹11,412 | 0.917 |
| **HistGradientBoosting** | **10.4%** | **₹10,459** | **0.937** |

**Risk classifier (synthetic labels).** No licensed, labelled rental-scam dataset exists publicly, so labels come from a documented **generative simulation**:
* It starts from real listings.
* Legitimate and risky scenarios use overlapping tactics.
* 3% of labels are flipped as noise.
* Features are computed by the production analyzers.

Results on a 1,200-row test split:

| Model | Precision | Recall | F1 | ROC-AUC | PR-AUC |
|---|---|---|---|---|---|
| Rule score only (baseline) | 0.788 | 0.617 | 0.692 | 0.883 | 0.775 |
| Logistic regression | 0.774 | 0.799 | 0.786 | 0.907 | 0.837 |
| Random forest | 0.773 | 0.824 | 0.798 | 0.915 | 0.845 |
| **Gradient boosting** | **0.859** | **0.760** | **0.807** | **0.915** | **0.863** |

**On real data.** Scored with the full engine, the 9,139 unlabelled 2018 listings come out 98.5% LOW, 1.5% MODERATE
and 1 HIGH. This is the tool's flag rate on ordinary market listings.

> These classifier metrics measure how well the model recovers the **simulation**. They are **not** real-world
> fraud-detection accuracy. See [`docs/ml.md`](docs/ml.md) for features, cross-validation, confusion matrices,
> importances, a label-leakage bug that was found and fixed, and limitations.

## DSA

| Where | Structure / algorithm | Why |
|---|---|---|
| Price baselines, locality index, contact stats | **Hash map** | O(1) lookup of "2 BHK in Andheri West" peers |
| Evidence de-duplication, shingles, indicator codes | **Set** | Unique phrases and indicators; Jaccard similarity |
| Contribution ranking, search sort | **Sorting** (+ DB B-tree indexes) | Explanations ordered by impact; listing ranking |
| Locality autocomplete | **Binary search** (`bisect`) on sorted keys | O(log n + m) prefix search |
| Dashboard verification queue | **Heap** (bounded min-heap top-k) | O(n log k) top-risk listings with a computed priority |
| Duplicate detection | **String similarity**: TF-IDF cosine, **MinHash + LSH** | Avoids O(n²): 97.7% fewer comparisons with recall 1.0 at ≥ 0.9 similarity (measured) |
| Login protection | **Deque sliding window** | O(1) amortised rate limiting |

Complexity analysis and benchmark: [`docs/architecture.md#4-data-structures--algorithms`](docs/architecture.md).

## Installation

```bash
git clone <your-repo-url> rentalguard
cd rentalguard

python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env   (then set SECRET_KEY)
```

## Database

* By default (`DATABASE_URL` empty) the app uses SQLite at `instance/rentalguard.db`.
* For PostgreSQL, set `DATABASE_URL=postgresql://user:password@host:5432/rentalguard`.
* Tables are created automatically on start-up.

To load the scored reference and demo listings (the market explorer and dashboard use them):

```bash
python scripts/seed_database.py              # all 9,139 listings (~7 min, each is risk-scored)
python scripts/seed_database.py --limit 500  # quicker
```

## Training (data & ML pipeline)

```bash
python scripts/download_data.py      # download + profile raw CSV → data/raw/
python scripts/clean_data.py         # → data/processed/listings_clean.csv
python scripts/eda.py                # → docs/eda/*.png + eda_summary.md
python scripts/create_features.py    # → ml_models/price_baselines.json, contact_stats.json, duplicate_index.joblib
python -m app.ml.train               # → ml_models/price_model.joblib, risk_model.joblib, metrics.json
python scripts/benchmark_duplicates.py   # optional: O(n²) vs LSH benchmark
```

All steps are seeded and reproducible. `python -m app.ml.train --regenerate` rebuilds the synthetic dataset.

## Running

```bash
python run.py
# → http://127.0.0.1:5000
```

Production-style: `gunicorn "app:create_app('production')"` (requires `SECRET_KEY`).

## Testing

```bash
pytest
```

The suite covers:
* price analyzer, deposit parsing, text analyzer (including false-positive cases), duplicate detector (including LSH-versus-brute-force recall)
* risk engine
* authentication and security (rate limit, CSRF, open redirect, cookies)
* listing API validation edge cases: missing, zero and negative rent; invalid BHK; long descriptions; malformed JSON; oversized bodies
* search, sort and filter; privacy between users; duplicate detection across users
* empty database; missing model artifacts
* DSA helpers

Tests use small synthetic artifacts, so they don't need the downloaded dataset.

**Browser end-to-end check** (headless Chrome over the DevTools protocol; needs Node ≥ 22 and a running server):

```bash
node tests/e2e/browser_flow.mjs http://127.0.0.1:5000 "C:/Program Files/Google/Chrome/Application/chrome.exe"
```

It goes through register → analyze → results → report → history filters → market search → dashboard charts →
methodology → logout, and fails on any JS exception, console error or unexpected HTTP error.

## Limitations

* **Not proof of fraud.** RentalGuard is a risk-assessment aid. A high score means "verify carefully", not "scam".
* **False positives:**
  * genuine discounts
  * a landlord who really is abroad and uses an agent
  * broker templates that look like duplicates
  * 2018 prices that make today's rents look high
* **False negatives:**
  * scams priced at market rate
  * polished wording that avoids known phrases
  * contact details not entered
  * risky wording in languages other than English (Hindi and Marathi are not supported)
* **Synthetic labels.** The ML classifier's metrics describe agreement with a simulation. Real performance is unknown until the model is trained on verified reports.
* **Price variation.** Rent varies by building, floor, view and condition, none of which are fully captured. Comparable ranges are statistical (roughly the interquartile range).
* **Geography.** Mumbai Metropolitan Region only, from one 2018 portal snapshot. Sparse localities fall back to zone or city-wide peers, with wider uncertainty.
* **Scaling.** The duplicate index lives in process memory (a single gunicorn worker). See `docs/architecture.md`.

## Future improvements

* Collect verified outcomes from reports and retrain the classifier on real labels, with calibration.
* Refresh the price data from a licensed, current source, and add an inflation or time index.
* Support Hindi and Marathi in text analysis. Add image reverse-search for reused listing photos.
* Move the duplicate index to a shared store (Redis or pgvector) for multi-worker deployments.
* Add Alembic migrations, CI (GitHub Actions running pytest), and an end-to-end browser test suite.

## Project structure

```text
app/            Flask app: config, security, validation, models/, routes/, services/, ml/, utils/, templates/, static/
scripts/        download_data, clean_data, eda, create_features, seed_database, benchmark_duplicates
data/           raw/ (downloaded), processed/, synthetic/, demo/demo_listings.json (hand-written demo data)
ml_models/      trained artifacts + metrics.json
docs/           architecture.md, dataset.md, ml.md, api.md, eda/
notebooks/      01_eda.ipynb
tests/          pytest suite
```
