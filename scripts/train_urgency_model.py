"""
SignalBrief — Urgency Classifier (Simple Edition)
===================================================
TF-IDF + Logistic Regression. Trains in < 5 seconds.
No GPU. No PyTorch. No waiting.

Output
------
  models/urgency_classifier.joblib    — trained pipeline (TF-IDF + LR)
  models/urgency_classifier_metrics.json — accuracy, F1, confusion matrix

Usage
-----
  python scripts/train_urgency_model.py
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
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
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

# ─────────────────────────────────────────────
LABEL_MAP = {"low": 0, "medium": 1, "high": 2}
ID2LABEL  = {0: "low", 1: "medium", 2: "high"}
DATA_PATH = "data/training/urgency_dataset.csv"
OUT_DIR   = Path("models")
MODEL_OUT = OUT_DIR / "urgency_classifier.joblib"
METRICS_OUT = OUT_DIR / "urgency_classifier_metrics.json"
SEED = 42
# ─────────────────────────────────────────────


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Load ─────────────────────────────────
    print(f"[SignalBrief] Loading dataset: {DATA_PATH}")
    df = pd.read_csv(DATA_PATH).dropna(subset=["text", "label", "urgency_score"])
    df["label_id"] = df["label"].map(LABEL_MAP)
    df = df.dropna(subset=["label_id"])

    print(f"[SignalBrief] Samples: {len(df)}")
    print(df["label"].value_counts().to_string())

    X = df["text"].tolist()
    y = df["label_id"].astype(int).tolist()

    # ── Split (80 train / 10 val / 10 test) ──
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=SEED, stratify=y
    )
    X_val, X_test, y_val, y_test = train_test_split(
        X_test, y_test, test_size=0.50, random_state=SEED, stratify=y_test
    )
    print(f"\n[SignalBrief] Train={len(X_train)} | Val={len(X_val)} | Test={len(X_test)}")

    # ── Build Pipeline ────────────────────────
    # TF-IDF captures word patterns, char n-grams handle informal text
    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(
            ngram_range=(1, 3),       # unigrams + bigrams + trigrams
            analyzer="word",
            max_features=20_000,
            sublinear_tf=True,        # log-scale TF
            min_df=1,
        )),
        ("clf", LogisticRegression(
            C=5.0,                    # regularization
            class_weight="balanced",  # handles label imbalance
            max_iter=1000,
            random_state=SEED,
            solver="lbfgs",           # lbfgs handles multinomial natively
        )),
    ])

    # -- Train ---------------------------------
    print("\n[SignalBrief] Training TF-IDF + LogisticRegression...")
    pipeline.fit(X_train, y_train)
    print("[SignalBrief] Training done - OK")

    # -- Val check ----------------------------
    y_val_pred = pipeline.predict(X_val)
    val_acc = accuracy_score(y_val, y_val_pred)
    val_f1  = f1_score(y_val, y_val_pred, average="macro")
    print(f"[SignalBrief] Val  Acc={val_acc:.4f}  F1={val_f1:.4f}")

    # -- Test evaluation -----------------------
    y_pred = pipeline.predict(X_test)
    y_prob = pipeline.predict_proba(X_test)   # shape (N, 3)

    acc = accuracy_score(y_test, y_pred)
    f1  = f1_score(y_test, y_pred, average="macro")
    cm  = confusion_matrix(y_test, y_pred).tolist()
    report = classification_report(
        y_test, y_pred,
        target_names=["low", "medium", "high"],
        output_dict=True,
    )

    print(f"\n{'='*50}")
    print("  SignalBrief --- Urgency Classifier Results")
    print(f"{'='*50}")
    print(f"  Accuracy  : {acc:.4f}  ({acc*100:.1f}%)")
    print(f"  F1 Macro  : {f1:.4f}")
    print(f"\n{classification_report(y_test, y_pred, target_names=['low','medium','high'])}")
    print("  Confusion Matrix (rows=actual, cols=predicted):")
    print("  [low, medium, high]")
    for i, row in enumerate(cm):
        print(f"  {['low','medium','high'][i]:8s}: {row}")

    # -- Save model ----------------------------
    joblib.dump(pipeline, MODEL_OUT)
    print(f"\n[SignalBrief] Model saved -> {MODEL_OUT}")

    # -- Save metrics --------------------------
    metrics = {
        "test_accuracy": round(acc, 4),
        "test_f1_macro": round(f1, 4),
        "val_accuracy": round(val_acc, 4),
        "val_f1_macro": round(val_f1, 4),
        "class_report": report,
        "confusion_matrix": cm,
        "label_map": LABEL_MAP,
        "id2label": {str(k): v for k, v in ID2LABEL.items()},
        "model_type": "TfidfVectorizer + LogisticRegression",
        "dataset": DATA_PATH,
        "num_train": len(X_train),
        "num_val": len(X_val),
        "num_test": len(X_test),
    }
    with open(METRICS_OUT, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[SignalBrief] Metrics saved -> {METRICS_OUT}")

    # -- Quick sample predictions --------------
    print("\n[SignalBrief] Sample predictions:")
    samples = [
        "Bro the server is literally on fire, call me now",
        "Can you review my PR when you get a chance? No rush",
        "Hey, free this evening?",
        "URGENT: Client threatening to pull the contract, need you on call",
        "Reminder: team lunch tomorrow",
    ]
    for text in samples:
        probs = pipeline.predict_proba([text])[0]
        label = ID2LABEL[int(np.argmax(probs))]
        # urgency_score: weighted sum (low=0.1, medium=0.5, high=0.95)
        urgency = probs[0]*0.05 + probs[1]*0.45 + probs[2]*0.95
        print(f"  [{label:10s} | score={urgency:.3f}]  {text[:60]}")

    print(f"\n[SignalBrief] Done! Next: restart the backend to activate on-device model.")


if __name__ == "__main__":
    main()
