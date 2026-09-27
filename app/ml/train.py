"""Train and evaluate RentalGuard's models.

    python -m app.ml.train                 # train everything
    python -m app.ml.train --regenerate    # also regenerate the synthetic risk dataset
    python -m app.ml.train --samples 6000  # synthetic dataset size

Stage 1 - price regression (real data, target = log monthly rent)
    Ridge / RandomForest / HistGradientBoosting vs a peer-median baseline,
    5-fold CV on the training split + a held-out 20% test split.
Stage 2 - synthetic risk dataset (app/ml/synthetic.py)
Stage 3 - risk classifier (synthetic labels)
    LogisticRegression / RandomForest / GradientBoosting, stratified 5-fold CV,
    held-out test, compared with the rule-only score as a baseline.

All metrics are written to ml_models/metrics.json; nothing is hand-entered.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (GradientBoostingClassifier, HistGradientBoostingRegressor,
                              RandomForestClassifier, RandomForestRegressor)
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score, mean_absolute_error,
                             precision_score, r2_score, recall_score, roc_auc_score)
from sklearn.model_selection import KFold, StratifiedKFold, cross_validate, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from app.ml.features import RISK_FEATURES, bhk_bucket
from app.ml.model_loader import METRICS, PRICE_MODEL, RISK_MODEL
from app.ml.preprocessing import PRICE_CATEGORICAL, PRICE_FEATURES, PRICE_NUMERIC, price_feature_frame

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "processed" / "listings_clean.csv"
SYNTHETIC = ROOT / "data" / "synthetic" / "risk_training.csv"
MODEL_DIR = ROOT / "ml_models"
SEED = 42


# ============================================================================
# Stage 1: price model
# ============================================================================
def price_pipelines() -> dict[str, Pipeline]:
    onehot = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=10), PRICE_CATEGORICAL),
        ("num", Pipeline([("imp", SimpleImputer(strategy="median", add_indicator=True)),
                          ("sc", StandardScaler())]), PRICE_NUMERIC),
    ])
    ordinal = ColumnTransformer([
        ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1,
                               encoded_missing_value=-1), PRICE_CATEGORICAL),
        ("num", "passthrough", PRICE_NUMERIC),
    ], verbose_feature_names_out=False)
    n_cat = len(PRICE_CATEGORICAL)
    return {
        "ridge": Pipeline([("prep", onehot), ("model", Ridge(alpha=1.0))]),
        "random_forest": Pipeline([("prep", ColumnTransformer([
            ("cat", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=10), PRICE_CATEGORICAL),
            ("num", SimpleImputer(strategy="median", add_indicator=True), PRICE_NUMERIC)])),
            ("model", RandomForestRegressor(n_estimators=300, min_samples_leaf=3, n_jobs=-1, random_state=SEED))]),
        "hist_gradient_boosting": Pipeline([("prep", ordinal), ("model", HistGradientBoostingRegressor(
            categorical_features=list(range(n_cat)), max_iter=400, learning_rate=0.05,
            l2_regularization=1.0, random_state=SEED))]),
    }


def peer_median_baseline(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Median rent of (locality_group, bhk) in the training split; falls back to bhk median."""
    tr = train.assign(b=train.bhk.map(bhk_bucket))
    te = test.assign(b=test.bhk.map(bhk_bucket))
    grp = tr.groupby(["locality_group", "b"]).rent.agg(["median", "size"])
    grp = grp[grp["size"] >= 5]["median"].to_dict()
    by_bhk = tr.groupby("b").rent.median().to_dict()
    overall = tr.rent.median()
    return np.array([grp.get((g, b), by_bhk.get(b, overall)) for g, b in zip(te.locality_group, te.b)])


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    ape = np.abs(y_pred - y_true) / y_true
    return {"mae_rupees": round(float(mean_absolute_error(y_true, y_pred)), 0),
            "median_ape": round(float(np.median(ape)), 4),
            "within_20pct": round(float(np.mean(ape <= 0.20)), 4),
            "r2_log": round(float(r2_score(np.log(y_true), np.log(y_pred))), 4)}


def train_price_model(df: pd.DataFrame, model_groups: set[str]) -> dict:
    data = df[~df.price_outlier.astype(bool)].reset_index(drop=True)
    X = price_feature_frame(data, model_groups)
    y = np.log(data.rent.to_numpy(float))
    idx_tr, idx_te = train_test_split(np.arange(len(data)), test_size=0.2, random_state=SEED)
    Xtr, Xte, ytr, yte = X.iloc[idx_tr], X.iloc[idx_te], y[idx_tr], y[idx_te]

    results = {"rows": int(len(data)), "train_rows": int(len(idx_tr)), "test_rows": int(len(idx_te)),
               "features": PRICE_FEATURES, "models": {}}
    base = peer_median_baseline(data.iloc[idx_tr], data.iloc[idx_te])
    results["models"]["peer_median_baseline"] = {"test": regression_metrics(np.exp(yte), base)}
    print("  peer_median_baseline", results["models"]["peer_median_baseline"]["test"])

    kf = KFold(5, shuffle=True, random_state=SEED)
    best_name, best_mae, fitted = None, np.inf, {}
    for name, pipe in price_pipelines().items():
        t = time.time()
        cv = cross_validate(pipe, Xtr, ytr, cv=kf, scoring=["neg_mean_absolute_error", "r2"], n_jobs=1)
        pipe.fit(Xtr, ytr)
        test = regression_metrics(np.exp(yte), np.exp(pipe.predict(Xte)))
        results["models"][name] = {"cv_mae_log_mean": round(float(-cv["test_neg_mean_absolute_error"].mean()), 4),
                                   "cv_mae_log_std": round(float(cv["test_neg_mean_absolute_error"].std()), 4),
                                   "cv_r2_log_mean": round(float(cv["test_r2"].mean()), 4),
                                   "test": test, "train_seconds": round(time.time() - t, 1)}
        fitted[name] = pipe
        print(f"  {name}: cv MAE(log) {-cv['test_neg_mean_absolute_error'].mean():.3f} test {test}")
        if -cv["test_neg_mean_absolute_error"].mean() < best_mae:
            best_name, best_mae = name, -cv["test_neg_mean_absolute_error"].mean()

    best = fitted[best_name]
    imp = permutation_importance(best, Xte, yte, n_repeats=5, random_state=SEED, scoring="neg_mean_absolute_error")
    results["selected"] = best_name
    results["selection_criterion"] = "lowest 5-fold CV MAE of log(rent) on the training split"
    results["permutation_importance"] = {f: round(float(m), 4) for f, m in
                                         sorted(zip(PRICE_FEATURES, imp.importances_mean), key=lambda t: -t[1])}
    # Refit the selected model on all data for serving
    best.fit(X, y)
    joblib.dump({"pipeline": best, "model_name": best_name, "features": PRICE_FEATURES,
                 "version": datetime.now(timezone.utc).strftime("%Y%m%d%H%M")}, MODEL_DIR / PRICE_MODEL, compress=3)
    return results


# ============================================================================
# Stage 3: risk classifier
# ============================================================================
def risk_pipelines() -> dict[str, Pipeline]:
    return {
        "logistic_regression": Pipeline([("sc", StandardScaler()), ("model", LogisticRegression(
            max_iter=2000, class_weight="balanced", C=1.0))]),
        "random_forest": Pipeline([("model", RandomForestClassifier(
            n_estimators=400, min_samples_leaf=3, class_weight="balanced", n_jobs=-1, random_state=SEED))]),
        "gradient_boosting": Pipeline([("model", GradientBoostingClassifier(
            n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=SEED))]),
    }


def classification_metrics(y: np.ndarray, proba: np.ndarray, threshold: float = 0.5) -> dict:
    pred = (proba >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {"precision": round(float(precision_score(y, pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y, pred, zero_division=0)), 4),
            "f1": round(float(f1_score(y, pred, zero_division=0)), 4),
            "roc_auc": round(float(roc_auc_score(y, proba)), 4),
            "pr_auc": round(float(average_precision_score(y, proba)), 4),
            "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
            "threshold": threshold}


def train_risk_model(syn: pd.DataFrame) -> dict:
    X = syn[RISK_FEATURES]
    y = syn.risk_label.to_numpy()
    Xtr, Xte, ytr, yte, rtr, rte = train_test_split(X, y, syn.rule_points.to_numpy(), test_size=0.2,
                                                    stratify=y, random_state=SEED)
    results = {"rows": int(len(syn)), "positive_rate": round(float(y.mean()), 4),
               "train_rows": int(len(Xtr)), "test_rows": int(len(Xte)), "features": RISK_FEATURES,
               "label_source": "synthetic simulation (app/ml/synthetic.py)", "models": {}}

    # Baseline: the transparent rule score alone (>= 25 points = MODERATE or above)
    results["models"]["rule_score_baseline"] = {"test": classification_metrics(yte, rte / 80.0, 25 / 80.0)}
    print("  rule_score_baseline", results["models"]["rule_score_baseline"]["test"])

    skf = StratifiedKFold(5, shuffle=True, random_state=SEED)
    best_name, best_ap, fitted = None, -1.0, {}
    for name, pipe in risk_pipelines().items():
        t = time.time()
        cv = cross_validate(pipe, Xtr, ytr, cv=skf, scoring=["precision", "recall", "f1", "roc_auc",
                                                                "average_precision"])
        pipe.fit(Xtr, ytr)
        test = classification_metrics(yte, pipe.predict_proba(Xte)[:, 1])
        results["models"][name] = {
            "cv": {m: {"mean": round(float(cv[f"test_{m}"].mean()), 4), "std": round(float(cv[f"test_{m}"].std()), 4)}
                   for m in ("precision", "recall", "f1", "roc_auc", "average_precision")},
            "test": test, "train_seconds": round(time.time() - t, 1)}
        fitted[name] = pipe
        print(f"  {name}: cv PR-AUC {cv['test_average_precision'].mean():.3f} test {test}")
        if cv["test_average_precision"].mean() > best_ap:
            best_name, best_ap = name, cv["test_average_precision"].mean()

    best = fitted[best_name]
    imp = permutation_importance(best, Xte, yte, n_repeats=5, random_state=SEED, scoring="average_precision")
    results["selected"] = best_name
    results["selection_criterion"] = "highest 5-fold CV average precision (PR-AUC) on the training split"
    results["permutation_importance"] = {f: round(float(m), 4) for f, m in
                                         sorted(zip(RISK_FEATURES, imp.importances_mean), key=lambda t: -t[1])}
    lr = fitted["logistic_regression"]
    results["logistic_coefficients"] = {f: round(float(c), 4) for f, c in
                                        zip(RISK_FEATURES, lr.named_steps["model"].coef_[0])}
    joblib.dump({"pipeline": best, "model_name": best_name, "features": RISK_FEATURES,
                 "version": datetime.now(timezone.utc).strftime("%Y%m%d%H%M")}, MODEL_DIR / RISK_MODEL, compress=3)
    return results


# ============================================================================
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Train RentalGuard models")
    parser.add_argument("--regenerate", action="store_true", help="regenerate the synthetic dataset")
    parser.add_argument("--samples", type=int, default=6000)
    args = parser.parse_args(argv)

    if not DATA.exists() or not (MODEL_DIR / "price_baselines.json").exists():
        sys.exit("Run scripts/clean_data.py and scripts/create_features.py first.")
    df = pd.read_csv(DATA)
    baselines = json.loads((MODEL_DIR / "price_baselines.json").read_text(encoding="utf-8"))
    metrics = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "python": platform.python_version(), "sklearn": sklearn.__version__, "seed": SEED}

    print("[train] stage 1: price model")
    metrics["price_model"] = train_price_model(df, set(baselines["model_groups"]))

    if args.regenerate or not SYNTHETIC.exists():
        print(f"[train] stage 2: generating {args.samples} synthetic samples")
        from app.ml.synthetic import generate
        from app.services.registry import build_engine
        engine, _ = build_engine(MODEL_DIR, load_ml=False)
        engine.price.model = joblib.load(MODEL_DIR / PRICE_MODEL)["pipeline"]
        SYNTHETIC.parent.mkdir(parents=True, exist_ok=True)
        syn = generate(df, engine, n=args.samples)
        syn.to_csv(SYNTHETIC, index=False)
    else:
        print(f"[train] stage 2: reusing {SYNTHETIC.relative_to(ROOT)} (use --regenerate to rebuild)")
        syn = pd.read_csv(SYNTHETIC)

    print("[train] stage 3: risk classifier")
    metrics["risk_model"] = train_risk_model(syn)
    (MODEL_DIR / METRICS).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"[train] done. price model: {metrics['price_model']['selected']}, "
          f"risk model: {metrics['risk_model']['selected']} -> {MODEL_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
