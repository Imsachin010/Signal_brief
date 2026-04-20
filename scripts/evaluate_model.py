"""
SignalBrief — Proper Model Evaluation
======================================
Evaluates the trained urgency classifier (TF-IDF + LogReg)
with a proper stratified train/val/test split on the FULL
dataset, and reports all standard metrics.

Usage
-----
  python scripts/evaluate_model.py

Output
------
  - Accuracy, F1 (macro + weighted)
  - Per-class precision / recall / F1
  - Confusion matrix (ASCII)
  - Latency benchmarks (avg, p50, p95, p99)
  - Top misclassified examples
  - Saves results to models/eval_results.json
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline

# ── Config ────────────────────────────────────────────────────────────────────
DATASET_PATH = Path("data/urgency_dataset.csv")
RESULTS_PATH = Path("models/eval_results.json")

LABEL_MAP  = {"low": 0, "medium": 1, "high": 2}
ID2LABEL   = {0: "low", 1: "medium", 2: "high"}
LABEL_NAMES = ["low", "medium", "high"]

TEST_SIZE  = 0.15   # 15% held-out test set
VAL_SIZE   = 0.15   # 15% validation (from train portion)
RANDOM_STATE = 42
N_FOLDS    = 5      # cross-validation folds
# ─────────────────────────────────────────────────────────────────────────────


def build_pipeline() -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(
            ngram_range=(1, 2),
            max_features=8000,
            sublinear_tf=True,
            min_df=2,
        )),
        ("clf", LogisticRegression(
            C=4.0,
            max_iter=1000,
            class_weight="balanced",
            solver="lbfgs",
            random_state=RANDOM_STATE,
        )),
    ])


def ascii_confusion_matrix(cm: list[list[int]], labels: list[str]) -> str:
    col_w = 10
    header = " " * 12 + "".join(f"{l:>{col_w}}" for l in labels) + "   (predicted)"
    divider = " " * 12 + "─" * (col_w * len(labels))
    rows = [header, divider]
    for i, label in enumerate(labels):
        row_vals = "".join(f"{v:>{col_w}}" for v in cm[i])
        rows.append(f"  {label:>8s}  │{row_vals}")
    return "\n".join(rows)


def bar(value: float, width: int = 30) -> str:
    filled = int(value * width)
    return "█" * filled + "░" * (width - filled) + f"  {value*100:.1f}%"


def main() -> None:
    print()
    print("══════════════════════════════════════════════════════")
    print("   SignalBrief — Urgency Classifier Evaluation")
    print("   Model: TF-IDF (1-2gram, 8k) + Logistic Regression")
    print("══════════════════════════════════════════════════════")

    # ── Load dataset ──────────────────────────────────────────
    if not DATASET_PATH.exists():
        print(f"[ERROR] Dataset not found: {DATASET_PATH}")
        return

    df = pd.read_csv(DATASET_PATH).dropna(subset=["text", "label"])
    df = df[df["label"].isin(LABEL_MAP)]
    df["label_id"] = df["label"].map(LABEL_MAP)

    print(f"\n  Dataset      : {DATASET_PATH}")
    print(f"  Total samples: {len(df)}")
    print(f"  Label distribution:")
    for lbl, cnt in df["label"].value_counts().sort_index().items():
        pct = cnt / len(df)
        print(f"    {str(lbl):>8s}  {bar(pct)}  (n={cnt})")

    # ── Stratified train / val / test split ───────────────────
    X = df["text"].tolist()
    y = df["label_id"].tolist()

    X_temp, X_test, y_temp, y_test = train_test_split(
        X, y,
        test_size=TEST_SIZE,
        stratify=y,
        random_state=RANDOM_STATE,
    )
    val_fraction = VAL_SIZE / (1 - TEST_SIZE)
    X_train, X_val, y_train, y_val = train_test_split(
        X_temp, y_temp,
        test_size=val_fraction,
        stratify=y_temp,
        random_state=RANDOM_STATE,
    )

    print(f"\n  Split (stratified):")
    print(f"    Train : {len(X_train)} samples ({len(X_train)/len(X)*100:.0f}%)")
    print(f"    Val   : {len(X_val)} samples ({len(X_val)/len(X)*100:.0f}%)")
    print(f"    Test  : {len(X_test)} samples ({len(X_test)/len(X)*100:.0f}%)")

    # ── Train ─────────────────────────────────────────────────
    print("\n  Training model... ", end="", flush=True)
    t0_train = time.perf_counter()
    model = build_pipeline()
    model.fit(X_train, y_train)
    train_time = (time.perf_counter() - t0_train) * 1000
    print(f"done in {train_time:.0f} ms")

    # ── Validation set ────────────────────────────────────────
    y_val_pred = model.predict(X_val)
    val_acc = accuracy_score(y_val, y_val_pred)
    val_f1  = f1_score(y_val, y_val_pred, average="macro")
    print(f"\n  Validation Accuracy : {val_acc:.4f}  ({val_acc*100:.1f}%)")
    print(f"  Validation F1 Macro : {val_f1:.4f}")

    # ── Test set ──────────────────────────────────────────────
    print("\n  Running test set inference... ", end="", flush=True)
    latencies: list[float] = []
    y_test_pred: list[int] = []
    for text in X_test:
        t0 = time.perf_counter()
        pred = model.predict([text])[0]
        latencies.append((time.perf_counter() - t0) * 1000)
        y_test_pred.append(int(pred))
    print("done")

    test_acc = accuracy_score(y_test, y_test_pred)
    test_f1  = f1_score(y_test, y_test_pred, average="macro")
    test_f1w = f1_score(y_test, y_test_pred, average="weighted")
    cm       = confusion_matrix(y_test, y_test_pred).tolist()
    report   = classification_report(
        y_test, y_test_pred,
        target_names=LABEL_NAMES,
        digits=4,
    )

    # ── Cross-validation ──────────────────────────────────────
    print(f"\n  Running {N_FOLDS}-fold cross-validation on full dataset...", end="", flush=True)
    skf = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    cv_accs, cv_f1s = [], []
    for fold_train_idx, fold_val_idx in skf.split(X, y):
        X_f_train = [X[i] for i in fold_train_idx]
        y_f_train = [y[i] for i in fold_train_idx]
        X_f_val   = [X[i] for i in fold_val_idx]
        y_f_val   = [y[i] for i in fold_val_idx]
        fold_model = build_pipeline()
        fold_model.fit(X_f_train, y_f_train)
        fold_preds = fold_model.predict(X_f_val)
        cv_accs.append(accuracy_score(y_f_val, fold_preds))
        cv_f1s.append(f1_score(y_f_val, fold_preds, average="macro"))
    print(" done")

    # ── Print results ─────────────────────────────────────────
    print()
    print("══════════════════════════════════════════════════════")
    print("   TEST SET RESULTS  (held-out, never seen in training)")
    print("══════════════════════════════════════════════════════")
    print(f"  Accuracy      : {bar(test_acc)}")
    print(f"  F1 Macro      : {bar(test_f1)}")
    print(f"  F1 Weighted   : {bar(test_f1w)}")
    print()
    print("  Per-class metrics:")
    print(report)

    print("  Confusion Matrix  (rows = actual, cols = predicted):")
    print(ascii_confusion_matrix(cm, LABEL_NAMES))
    print()

    print("══════════════════════════════════════════════════════")
    print(f"   {N_FOLDS}-FOLD CROSS-VALIDATION  (full dataset)")
    print("══════════════════════════════════════════════════════")
    print(f"  Accuracy  fold scores: {[f'{v:.4f}' for v in cv_accs]}")
    print(f"  Accuracy  mean ± std : {np.mean(cv_accs):.4f} ± {np.std(cv_accs):.4f}")
    print(f"  F1 Macro  fold scores: {[f'{v:.4f}' for v in cv_f1s]}")
    print(f"  F1 Macro  mean ± std : {np.mean(cv_f1s):.4f} ± {np.std(cv_f1s):.4f}")
    print()

    print("══════════════════════════════════════════════════════")
    print("   INFERENCE LATENCY  (single-sample, CPU)")
    print("══════════════════════════════════════════════════════")
    print(f"  avg   = {np.mean(latencies):.3f} ms")
    print(f"  p50   = {np.median(latencies):.3f} ms")
    print(f"  p95   = {np.percentile(latencies, 95):.3f} ms")
    print(f"  p99   = {np.percentile(latencies, 99):.3f} ms")
    print(f"  max   = {np.max(latencies):.3f} ms")
    print()

    # ── Misclassifications ────────────────────────────────────
    misses = [
        (X_test[i], ID2LABEL[y_test[i]], ID2LABEL[y_test_pred[i]])
        for i in range(len(y_test_pred))
        if y_test_pred[i] != y_test[i]
    ]
    print("══════════════════════════════════════════════════════")
    print(f"   MISCLASSIFIED EXAMPLES  ({len(misses)} of {len(X_test)} test samples)")
    print("══════════════════════════════════════════════════════")
    if not misses:
        print("  ✓ Zero misclassifications on test set!")
    else:
        for text, actual, predicted in misses[:10]:
            short = text[:72] + "…" if len(text) > 72 else text
            print(f"  actual={actual:>6s}  pred={predicted:>6s}  \"{short}\"")
    print()

    # ── Save results ──────────────────────────────────────────
    results = {
        "model_type": "TfidfVectorizer(ngram 1-2, 8k) + LogisticRegression(C=4, balanced)",
        "dataset": str(DATASET_PATH),
        "num_total": len(X),
        "num_train": len(X_train),
        "num_val":   len(X_val),
        "num_test":  len(X_test),
        "test_accuracy": round(test_acc, 6),
        "test_f1_macro": round(test_f1,  6),
        "test_f1_weighted": round(test_f1w, 6),
        "val_accuracy": round(val_acc, 6),
        "val_f1_macro": round(val_f1,  6),
        "cv_accuracy_mean": round(float(np.mean(cv_accs)), 6),
        "cv_accuracy_std":  round(float(np.std(cv_accs)),  6),
        "cv_f1_mean": round(float(np.mean(cv_f1s)), 6),
        "cv_f1_std":  round(float(np.std(cv_f1s)),  6),
        "cv_fold_accuracies": [round(v, 6) for v in cv_accs],
        "cv_fold_f1s":        [round(v, 6) for v in cv_f1s],
        "confusion_matrix": cm,
        "class_report": classification_report(
            y_test, y_test_pred, target_names=LABEL_NAMES, output_dict=True
        ),
        "latency_ms": {
            "avg": round(float(np.mean(latencies)),   4),
            "p50": round(float(np.median(latencies)), 4),
            "p95": round(float(np.percentile(latencies, 95)), 4),
            "p99": round(float(np.percentile(latencies, 99)), 4),
            "max": round(float(np.max(latencies)),    4),
        },
        "misclassified_count": len(misses),
        "misclassified_examples": [
            {"text": t[:120], "actual": a, "predicted": p}
            for t, a, p in misses[:20]
        ],
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(results, indent=2))
    print(f"  Results saved → {RESULTS_PATH}")
    print("══════════════════════════════════════════════════════")
    print()


if __name__ == "__main__":
    main()
