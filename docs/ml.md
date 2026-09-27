# Machine learning

RentalGuard trains two models with `python -m app.ml.train`. All numbers below come from
`ml_models/metrics.json` (generated 2026-09-24, Python 3.14.3, scikit-learn 1.9.1, seed 42).

**Second bug found and fixed:** almost no training rows lack an area, so the price model's missing-value branch
produced absurd estimates (₹2.49 lakh for a Powai 2 BHK). When a listing has no area, the peer group's median
area is now imputed before the model is called. The synthetic data and classifier were regenerated after this fix.

## 1. Price model (real data)

**Task:** predict `log(monthly rent)` for a listing.

**Data:** the 9,114 cleaned listings that are not price outliers. 80/20 train/test split (7,291 / 1,823 rows).

**Features** (`app/ml/preprocessing.py`):

| Feature | Type | Notes |
|---|---|---|
| `locality_group` | categorical | groups with < 10 listings become `other` |
| `zone` | categorical | 99acres zone |
| `furnishing` | categorical | furnished / semi / unfurnished / unknown |
| `property_type` | categorical | apartment / studio / independent_house |
| `bhk` | numeric | clipped to 1–6 |
| `log_area` | numeric | log(built-up sq.ft), missing allowed |
| `bathrooms` | numeric | parsed from text, mostly missing |

**Models compared.** 5-fold CV runs on the training split. Test metrics are on the untouched 20%.

| Model | CV MAE (log) | Test MAE | Test median abs. % error | Within ±20% | R² (log) |
|---|---|---|---|---|---|
| Peer median baseline (locality group × BHK) | – | ₹15,578 | 13.8% | 64.5% | 0.815 |
| Ridge regression (one-hot) | 0.174 | ₹12,164 | 12.7% | 69.5% | 0.921 |
| Random forest | 0.166 | ₹11,412 | 10.9% | 71.3% | 0.917 |
| **HistGradientBoosting** (selected) | **0.149** | **₹10,459** | **10.4%** | **76.1%** | **0.937** |

The model is selected by the lowest CV MAE, then refit on all data for serving.

**Explainability:**
* Permutation importance on the test set (increase in MAE when a feature is shuffled): locality_group 0.365, log_area 0.174, zone 0.140, bhk 0.090, furnishing 0.024, property_type 0.002, bathrooms ≈ 0.
* In the app the model is **not** used alone. The expected rent is a log-space blend of the explainable peer estimate and the model estimate, weighted `w_peer = n/(n+15)`. The UI shows the peer group, its size, both estimates and the weight.

## 2. Risk classifier (synthetic labels)

### Why synthetic labels

No openly licensed, labelled dataset of Indian rental scams was found (see `docs/dataset.md`). Labelling
ordinary 99acres listings as "not scam" and keyword matches as "scam" would make the task trivial and the
metrics meaningless. Instead, `app/ml/synthetic.py` **simulates a generative process**:

1. Every sample starts from a **real cleaned listing**, with its real rent, locality, area, description and hashed dealer.
2. A latent class is drawn: risky with probability 0.25.
3. Each class applies *tactics* with **overlapping** probabilities:

| Tactic | Legitimate | Risky |
|---|---|---|
| Rent change | 8%: genuine discount ×0.5–0.8 | 60%: bait price ×0.3–0.75 |
| Risky wording appended | 4% (landlords sometimes phrase things badly) | 70% (1–3 snippets; some regex-detectable, some only by TF-IDF, some undetectable) |
| Benign wording ("token after site visit", "urgent requirement of tenant") | 15% | – |
| Description cloned from another listing | – (but real broker templates already create look-alikes) | 35% |
| Inflated deposit (8–20× rent) | – | 25% |
| Area removed | 5% | 30% |
| Very short text | 3% | 20% |
| Contact | real dealer distribution (same for both classes) | same |

4. 3% of labels are flipped to model annotation noise.
5. Features are computed by **the production analyzers**: price, deposit, text, duplicate and contact. There is no separate feature code, so train/serve skew cannot occur.

Result: `data/synthetic/risk_training.csv`, 6,000 rows, positive rate 26.1%, 2.9% label noise.
Tactic counts: risky wording 1,119; bait price 882; missing area 664; benign wording 662; cloned text 514; short
text 452; genuine discount 385; inflated deposit 354; risky wording on legitimate listings 200.

**Bug found and fixed:** in the first version of the generator, the deposit was carried over from the base
listing while the rent was lowered. That inflated deposit/rent for every bait-price sample and leaked the label
into `deposit_ratio_rel`. The generator now keeps the *ratio* and applies it to the final rent.

### Features (`app/ml/features.py::RISK_FEATURES`)

`price_log_ratio, price_z, price_available, deposit_ratio_rel, deposit_provided, advance_payment,
payment_before_viewing, no_viewing, owner_away, urgency_score, unusual_payment, off_platform, semantic_risk,
dup_similarity, dup_conflict, contact_log_listings, contact_reported, desc_log_len, missing_area, n_text_categories`

### Evaluation

Stratified 80/20 split (4,800 / 1,200 rows). 5-fold stratified CV runs on the training split. Accuracy is **not**
used because of class imbalance. The baseline is the transparent rule score alone (≥ 25 points counts as positive).

| Model | Precision | Recall | F1 | ROC-AUC | PR-AUC | Confusion (tn/fp/fn/tp) |
|---|---|---|---|---|---|---|
| Rule score only (baseline) | 0.788 | 0.617 | 0.692 | 0.883 | 0.775 | 835 / 52 / 120 / 193 |
| Logistic regression (balanced) | 0.774 | 0.799 | 0.786 | 0.907 | 0.837 | 814 / 73 / 63 / 250 |
| Random forest (balanced) | 0.773 | 0.824 | 0.798 | 0.915 | 0.845 | 811 / 76 / 55 / 258 |
| **Gradient boosting** (selected) | **0.859** | **0.760** | **0.807** | **0.915** | **0.863** | 848 / 39 / 75 / 238 |

Gradient boosting has the highest CV PR-AUC (0.863 ± 0.028). Its CV F1 is 0.816 ± 0.014 and CV ROC-AUC 0.925 ± 0.012.

**Permutation importance** (test PR-AUC drop): price_z 0.150, deposit_ratio_rel 0.101, n_text_categories 0.063,
semantic_risk 0.062, price_log_ratio 0.025, missing_area 0.019, desc_log_len 0.017, dup_similarity 0.008.
Individual text flags score low because `n_text_categories` and `semantic_risk` carry the same information.
`deposit_ratio_rel` ranks highly because the simulated inflated-deposit tactic (8–20×) never overlaps real
deposits (95th percentile 6×). **This reflects a design choice of the simulation, not an empirical finding.**

### How the probability is used

`risk_score = min(80, Σ rule points) + round(20 × probability)`. The model can move a score by at most 20
points, and the UI shows its contribution as its own line item.

## 3. Limitations and honest interpretation

* The classifier metrics measure **how well the model recovers the simulation**, not real-world fraud-detection accuracy. With real labelled reports, precision and recall would very likely be lower.
* The simulation encodes assumptions (which tactics scammers use and how often). If those assumptions are wrong, the model is wrong in the same way.
* The price model reflects **2018** rents from one portal.
* Neither model is calibrated against real outcomes. The probability must not be read as "the chance this listing is a scam".
* Improvement path: collect user reports (`/api/reports`) and verified outcomes, then retrain the classifier on real labels and re-evaluate against the rule baseline.

## 4. Reproducing

```bash
python scripts/download_data.py
python scripts/clean_data.py
python scripts/create_features.py
python -m app.ml.train --regenerate      # ~5 minutes on a laptop
```

Randomness is seeded: split/model seed 42 and synthetic generator seed 7.
