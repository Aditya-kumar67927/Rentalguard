"""Exploratory data analysis of the cleaned Mumbai rental dataset.

Produces PNG plots in docs/eda/ and a data-driven summary docs/eda/eda_summary.md.
All numbers in the summary are computed here - nothing is hand-written.

Usage: python scripts/eda.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "listings_clean.csv"
OUT = ROOT / "docs" / "eda"

BLUE = "#2a78d6"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": "#c3c2b7", "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.titlecolor": INK, "axes.titleweight": "bold", "axes.titlesize": 12, "axes.titlelocation": "left",
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
    "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"],
})


def rupees(x, _pos=None):
    if x >= 100_000:
        return f"₹{x / 100_000:.1f}L"
    return f"₹{x / 1000:.0f}k"


def save(fig, name):
    fig.tight_layout()
    fig.savefig(OUT / name, dpi=130)
    plt.close(fig)


def hbar(series: pd.Series, title: str, xlabel: str, name: str, fmt=None):
    fig, ax = plt.subplots(figsize=(8, max(3, 0.32 * len(series) + 1)))
    s = series.iloc[::-1]
    ax.barh(s.index.astype(str), s.values, color=BLUE, height=0.7)
    ax.grid(axis="y", visible=False)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    if fmt:
        ax.xaxis.set_major_formatter(fmt)
    save(fig, name)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(DATA)
    stats: dict[str, object] = {"rows": len(df)}

    # 1. Rent distribution (log scale - rent is heavily right-skewed)
    fig, ax = plt.subplots(figsize=(8, 4))
    bins = np.logspace(np.log10(df.rent.min()), np.log10(df.rent.max()), 60)
    ax.hist(df.rent, bins=bins, color=BLUE, edgecolor=SURFACE, linewidth=0.5)
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(rupees))
    ax.set_title("Monthly rent distribution (log scale)")
    ax.set_xlabel("Monthly rent")
    ax.set_ylabel("Listings")
    save(fig, "01_rent_distribution.png")
    stats["rent"] = {k: float(v) for k, v in df.rent.describe(percentiles=[.05, .25, .5, .75, .95]).items()}
    stats["rent_skew"] = float(df.rent.skew())

    # 2. Rent by BHK (box plot, BHK 1-5 which have enough data)
    sub = df[df.bhk.between(1, 5)]
    groups = [sub.loc[sub.bhk == b, "rent"] for b in range(1, 6)]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.boxplot(groups, tick_labels=[f"{b} BHK" for b in range(1, 6)], showfliers=False,
               patch_artist=True, boxprops=dict(facecolor="#cde2fb", color=BLUE),
               medianprops=dict(color=BLUE, linewidth=2), whiskerprops=dict(color=MUTED),
               capprops=dict(color=MUTED))
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(rupees))
    ax.set_title("Monthly rent by BHK (outliers hidden, log scale)")
    save(fig, "02_rent_by_bhk.png")
    stats["median_rent_by_bhk"] = df.groupby("bhk").rent.agg(["median", "count"]).astype(float).to_dict("index")

    # 3. Median rent by locality group (top 20 by listing count)
    top = df.locality_group.value_counts().head(20).index
    med = df[df.locality_group.isin(top)].groupby("locality_group").rent.median().sort_values(ascending=False)
    med.index = [i.title() for i in med.index]
    hbar(med, "Median rent - 20 most-listed localities (all BHK)", "Median monthly rent",
         "03_rent_by_locality.png", plt.FuncFormatter(rupees))
    stats["median_rent_top_localities"] = med.to_dict()

    # 4. Rent per sq.ft by zone
    ppsf = df.dropna(subset=["rent_per_sqft"]).groupby("zone").rent_per_sqft.median().sort_values(ascending=False)
    hbar(ppsf, "Median rent per sq.ft by 99acres zone", "₹ per sq.ft per month", "04_rent_per_sqft_by_zone.png")
    stats["median_rent_per_sqft_by_zone"] = ppsf.round(2).to_dict()

    # 5. Deposit-to-rent ratio
    dr = df.deposit_ratio.dropna()
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(dr.clip(upper=15), bins=np.arange(0, 15.5, 0.5), color=BLUE, edgecolor=SURFACE, linewidth=0.5)
    ax.set_title(f"Security deposit as months of rent (n={len(dr):,} listings stating a deposit)")
    ax.set_xlabel("Deposit / monthly rent (clipped at 15)")
    ax.set_ylabel("Listings")
    save(fig, "05_deposit_ratio.png")
    stats["deposit_ratio"] = {k: float(v) for k, v in dr.describe(percentiles=[.05, .25, .5, .75, .95, .99]).items()}

    # 6. Furnishing vs rent per sq.ft
    fur = df.dropna(subset=["rent_per_sqft"]).groupby("furnishing").rent_per_sqft.agg(["median", "count"])
    fur = fur.sort_values("median", ascending=False)
    hbar(fur["median"], "Median rent per sq.ft by furnishing", "₹ per sq.ft per month", "06_furnishing.png")
    stats["furnishing"] = fur.round(2).to_dict("index")

    # 7. Locality frequency (long tail)
    freq = df.locality_group.value_counts()
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(np.arange(1, len(freq) + 1), freq.values, color=BLUE, linewidth=2)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_title("Listings per locality group (rank-frequency, log-log)")
    ax.set_xlabel("Locality rank")
    ax.set_ylabel("Listings")
    save(fig, "07_locality_frequency.png")
    stats["locality_groups"] = int(len(freq))
    stats["locality_groups_ge_20"] = int((freq >= 20).sum())
    stats["locality_groups_lt_5"] = int((freq < 5).sum())
    stats["share_listings_top20_groups"] = float(freq.head(20).sum() / len(df))

    # 8. Property type
    pt = df.property_type.value_counts()
    stats["property_type"] = pt.to_dict()
    hbar(pt, "Property type", "Listings", "08_property_type.png")

    # 9. Area distribution
    area = df.area_sqft.dropna()
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(area.clip(upper=4000), bins=60, color=BLUE, edgecolor=SURFACE, linewidth=0.5)
    ax.set_title("Built-up area distribution (clipped at 4,000 sq.ft)")
    ax.set_xlabel("sq.ft")
    ax.set_ylabel("Listings")
    save(fig, "09_area_distribution.png")
    stats["area_sqft"] = {k: float(v) for k, v in area.describe(percentiles=[.05, .5, .95]).items()}
    stats["corr_log_rent_log_area"] = float(np.corrcoef(np.log(df.dropna(subset=["area_sqft"]).rent),
                                                        np.log(df.dropna(subset=["area_sqft"]).area_sqft))[0, 1])

    # 10. Contact repetition (hashed dealers)
    per_contact = df.contact_hash.value_counts()
    stats["contacts"] = {"unique": int(len(per_contact)), "median_listings": float(per_contact.median()),
                         "max_listings": int(per_contact.max()),
                         "share_listings_by_top_10pct_contacts":
                             float(per_contact.head(max(1, len(per_contact) // 10)).sum() / per_contact.sum())}
    stats["reposts"] = {"listings_with_reposts": int((df.n_reposts > 1).sum()),
                        "max_reposts": int(df.n_reposts.max())}

    (OUT / "eda_stats.json").write_text(json.dumps(stats, indent=2, default=str))
    write_summary(stats)
    print(json.dumps(stats, indent=2, default=str)[:3000])


def write_summary(s: dict) -> None:
    r, d = s["rent"], s["deposit_ratio"]
    bhk = s["median_rent_by_bhk"]
    lines = [
        "# EDA summary (auto-generated by `scripts/eda.py`)",
        "",
        f"Dataset: {s['rows']:,} cleaned listings (99acres Mumbai, July 2018). "
        "All figures below are computed from `data/processed/listings_clean.csv`.",
        "",
        "## Rent",
        f"- Median monthly rent ₹{r['50%']:,.0f}; IQR ₹{r['25%']:,.0f}–₹{r['75%']:,.0f}; "
        f"5th–95th percentile ₹{r['5%']:,.0f}–₹{r['95%']:,.0f}.",
        f"- Distribution is strongly right-skewed (skewness {s['rent_skew']:.1f}), so the price engine "
        "uses medians / log-scale statistics instead of means.",
        "- Median rent by BHK: " + ", ".join(
            f"{int(float(k))} BHK ₹{v['median']:,.0f} (n={int(v['count'])})" for k, v in bhk.items() if v["count"] >= 20) + ".",
        f"- Correlation between log(rent) and log(area): {s['corr_log_rent_log_area']:.2f}.",
        "",
        "![rent](01_rent_distribution.png)",
        "![bhk](02_rent_by_bhk.png)",
        "![locality](03_rent_by_locality.png)",
        "",
        "## Location",
        f"- {s['locality_groups']} locality groups; only {s['locality_groups_ge_20']} have ≥20 listings and "
        f"{s['locality_groups_lt_5']} have <5. The top 20 groups hold {s['share_listings_top20_groups']:.0%} of listings. "
        "This long tail is why the price engine falls back from locality → zone → city-wide peers.",
        "- Median rent per sq.ft by zone: " + ", ".join(f"{k} ₹{v}" for k, v in s["median_rent_per_sqft_by_zone"].items()) + ".",
        "",
        "![zone](04_rent_per_sqft_by_zone.png)",
        "![freq](07_locality_frequency.png)",
        "",
        "## Deposit",
        f"- A deposit could be parsed from the description for {int(d['count']):,} listings.",
        f"- Median deposit = {d['50%']:.1f}× monthly rent; IQR {d['25%']:.1f}–{d['75%']:.1f}×; "
        f"95th percentile {d['95%']:.1f}×; 99th percentile {d['99%']:.1f}×.",
        "",
        "![deposit](05_deposit_ratio.png)",
        "",
        "## Furnishing, property type, area",
        "- Median rent per sq.ft by furnishing: " + ", ".join(
            f"{k} ₹{v['median']} (n={int(v['count'])})" for k, v in s["furnishing"].items()) + ".",
        "- Property types: " + ", ".join(f"{k} {v:,}" for k, v in s["property_type"].items()) + ".",
        f"- Median built-up area {s['area_sqft']['50%']:,.0f} sq.ft (5th–95th pct "
        f"{s['area_sqft']['5%']:,.0f}–{s['area_sqft']['95%']:,.0f}).",
        "",
        "![furnishing](06_furnishing.png)",
        "![type](08_property_type.png)",
        "![area](09_area_distribution.png)",
        "",
        "## Contacts and reposts",
        f"- {s['contacts']['unique']:,} distinct (hashed) dealer contacts; median {s['contacts']['median_listings']:.0f} "
        f"listing(s) per contact, maximum {s['contacts']['max_listings']}. The top 10% of contacts account for "
        f"{s['contacts']['share_listings_by_top_10pct_contacts']:.0%} of listings.",
        "- Implication: repeated contacts are *normal* for brokers in this market, so contact repetition "
        "is only a weak, informational signal in the risk engine.",
        f"- {s['reposts']['listings_with_reposts']:,} cleaned listings had exact reposts in the raw file "
        f"(max {s['reposts']['max_reposts']} copies).",
    ]
    (OUT / "eda_summary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
