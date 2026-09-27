# Dataset

## 1. Selected source

| Item | Value |
|---|---|
| Dataset | 99acres Mumbai rental listings (`16-Jul-99acres-mumbai-rental-data.csv`) |
| Published by | GitHub user `baldsatan`, repository [`mumbai-rental-data-analysis`](https://github.com/baldsatan/mumbai-rental-data-analysis) |
| Original origin | Listings on 99acres.com, collected by the repository author on **16 July 2018** with data-miner.io (per the repo README) |
| Download URL (pinned) | `https://raw.githubusercontent.com/baldsatan/mumbai-rental-data-analysis/40caf19f49a3f8b01b9783b979273eb29f982b9e/16-Jul-99acres-mumbai-rental-data.csv` |
| Commit | `40caf19f49a3f8b01b9783b979273eb29f982b9e` (2018-08-03) |
| Date accessed | 2026-09-24 |
| Size | 10.63 MB, SHA-256 `386c3cad9785b14153fc4f691db941f46c2ccf0491b6402686419d4a70ba5d3c` |
| Rows × columns | 13,541 × 22 |
| Local file | `data/raw/mumbai_99acres_rent_2018.csv` (created by `scripts/download_data.py`, never modified) |

### Columns (raw)

`sl no.`, `society`, `type`, `location`, `lattitude`, `longitude`, `bedrooms`, `built-up area`, `furnishing`,
`age`, `floor`, `total floors`, `dealer`, `posted`, `monthly rent`, `property photo`, `property video`,
`society photo`, `society video`, `locality photo`, `locality video`, `description`.

Missing values in raw data: latitude/longitude 11,367; dealer 63; all other columns complete.
Exact duplicate rows: 0. However, 4,547 descriptions are repeated, and 4,402 rows are reposts of the same
property (same society, locality, BHK, area, rent and dealer).

### Why this dataset

It was the best fit among the public options that were checked:

* **Mumbai only.** It covers 532 raw location strings across the Mumbai Metropolitan Region.
* **Rich fields.** It has rent, BHK, built-up area, furnishing, property type, and a dealer (contact) identifier.
* **Free-text descriptions.** These are needed for the NLP and duplicate analysis. Security deposits and bathroom counts are also stated inside many descriptions.

### Licensing and usage

* **The repository has no licence file** (GitHub API `license: null`), and its README does not state usage terms.
* The data was originally collected from 99acres.com, whose terms of use restrict automated collection and
  commercial reuse.
* **How RentalGuard uses it:**
  * RentalGuard does **not** scrape any website.
  * It downloads the publicly posted copy for **non-commercial, educational/portfolio research only**.
  * The raw and processed data files are **git-ignored and not redistributed**. Anyone reproducing the project downloads them from the original repository with `scripts/download_data.py`.
  * Dealer names are replaced by salted SHA-256 hashes during cleaning, and any phone numbers or e-mails found in descriptions are redacted.
* Before any commercial use, obtain licensed data from a provider instead.

### Alternatives evaluated

| Candidate | Result |
|---|---|
| Kaggle *House Rent Prediction Dataset* (`iamsouravbanerjee`, 4,746 rows, 6 cities incl. Mumbai, from magicbricks.com) | Licence "Other (specified in description)", but the description names no licence. It has no descriptions or deposits, and downloading requires a Kaggle account. Not used. |
| Kaggle *House Rent In Mumbai* (`lokeshgupta2020`, 154 KB) | Licence "Unknown", and it requires a Kaggle account. Not used. |
| Commercial scraping APIs (Apify etc.) for NoBroker / MagicBricks | Would mean scraping sites whose terms prohibit it. Rejected. |
| Public, licensed Indian rental-*scam* datasets with labels | None found. Risk labels are therefore synthetic (see `docs/ml.md`). |

### Manual download (if the automatic download fails)

1. Open <https://github.com/baldsatan/mumbai-rental-data-analysis>.
2. Download `16-Jul-99acres-mumbai-rental-data.csv`.
3. Save it as `data/raw/mumbai_99acres_rent_2018.csv`.
4. Run `python scripts/download_data.py`. It detects the existing file and prints its profile.

## 2. Cleaning rules (`scripts/clean_data.py`)

| # | Rule | Effect on this dataset |
|---|---|---|
| 1 | **Encoding:** the file is UTF-8 with some cp1252 lines (e.g. byte `0x85`). Each line is decoded as UTF-8 first, falling back to cp1252. | No mojibake in the output |
| 2 | **Scraper artefacts:** remove `Description :`, `... read more` (spliced mid-word by the scraper) and `- view less`, then apply NFKC normalisation | All descriptions |
| 3 | **BHK:** `"2 BHK"`, `"2 Bedroom"` and `"2BHK"` become 2. `"1 RK"` becomes 1 with `is_rk=True` and type `studio`. Values outside 1–10 are dropped. | 0 dropped |
| 4 | **Rent:** strip currency symbols and commas. Rows with rent < ₹1,000 or > ₹20,00,000 are dropped as invalid. | 0 dropped |
| 5 | **Area:** values < 120 sq.ft, > 15,000 sq.ft, or < 100 sq.ft per bedroom are set to missing, **not deleted** (e.g. 10.76 sq.ft, which is 1 m² converted wrongly) | 3 set missing |
| 6 | **Coordinates:** points outside the MMR bounding box (lat 18.8–19.6, lon 72.7–73.4) are set to missing | 26 set missing |
| 7 | **Furnishing:** `Semifurnished` becomes `semi-furnished`, and `Not Mentioned` becomes `unknown` | – |
| 8 | **Locality normalisation:** lowercase, strip punctuation, `W`/`(West)` become `west`, `Sec-10` becomes `sector 10`, plus aliases (e.g. `Pali Hill` → `bandra west`). `Andheri West`, `andheri west`, `Andheri-West` and `Andheri (W)` all become `andheri west`. | 532 raw strings → 524 keys |
| 9 | **Locality groups:** sub-localities map to the longest known locality (≥15 listings) contained in the name, e.g. `hiranandani gardens powai` → `powai`. Generic tokens like `sector 10` are never used as groups. | 447 groups |
| 10 | **Zone:** 99acres zone parsed from the description (`mumbai andheri-dahisar`, `mumbai navi`, …). If missing, the majority zone of the locality group is used. | 8 zones + `Unknown` |
| 11 | **Deposit:** parsed from the description. Formats handled: `deposit of rs. 500000`, `6 months rent as deposit`, `1 lakh deposit`, `7, 00,000/-`. Values outside 0.5–36× rent are rejected as parse noise. | 3,859 before de-duplication |
| 12 | **Bathrooms:** parsed from `"2 bathrooms"` | 3,636 before de-duplication |
| 13 | **Privacy:** dealer names are salted and hashed (SHA-256, 16 hex chars). Phones and e-mails in descriptions are hashed, then redacted. | 1,237 unique hashed contacts |
| 14 | **Repost de-duplication:** keep the first row per (locality, BHK, area, rent, contact, society). `n_reposts` records the count. | 4,402 removed |
| 15 | **Outlier *flag*:** robust z-score (median/MAD) of log(rent per sq.ft) within each zone; flagged if \|z\| > 3.5. Rows are **kept**, but excluded from price baselines and price-model training. | 25 flagged |

Result: **9,139 listings** in `data/processed/listings_clean.csv`. Per-step counts are in
`data/processed/cleaning_report.json`.

## 3. Processed schema

`listing_id, source_row, society, property_type, location_raw, locality, locality_key, locality_group, zone,
latitude, longitude, bhk, is_rk, area_sqft, bathrooms, furnishing, age_band, floor, total_floors, rent, deposit,
deposit_ratio, rent_per_sqft, price_outlier, contact_hash, desc_contact_hashes, n_photos, n_reposts, posted_date,
description`

## 4. EDA

Run `python scripts/eda.py`. The plots and a data-driven summary are written to `docs/eda/`
([`eda_summary.md`](eda/eda_summary.md)). Key facts, all computed:

* Median rent ₹45,000 (IQR ₹25,000–₹75,000). The distribution is heavily right-skewed (skewness 4.8), so the price engine uses robust statistics.
* The median deposit is 4.4× monthly rent across the 2,517 listings that state one. The 95th percentile is 6.0×.
* 447 locality groups: only 91 have ≥ 20 listings and 256 have < 5. This long tail is why the price engine uses a fallback hierarchy.
* The top 10% of (hashed) dealers post 45% of listings, so a repeated contact is normal and only a weak signal.

## 5. Limitations

* **Age:** all prices are from July 2018, and Mumbai rents have risen since. Current listings will tend to look "above market". Low-price flags are affected less, because they need large deviations.
* **Coverage:** only one portal (99acres) and one snapshot. Some localities are sparse.
* **Selection bias:** broker-heavy. Most listings are from dealers rather than individual owners.
* **Templates:** many descriptions are auto-generated 99acres templates. They are near-identical across different flats, which is why the duplicate detector requires ≥ 90% similarity and only adds risk when details conflict.
* **Missing labels:** no fraud labels exist. Ordinary listings are **not** assumed to be "not scam". See `docs/ml.md` for the synthetic labelling approach.
* **Parsed fields:** deposits and bathrooms come from text parsing and are missing for most rows.
