"""
SignalBrief — Model Evaluation & Benchmarking
==============================================
Evaluates the trained ONNX model on the full dataset,
generates a confusion matrix, and prints benchmark stats.

Usage
-----
  python scripts/evaluate_model.py
  python scripts/evaluate_model.py --model models/urgency_classifier.onnx
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

LABEL_MAP = {"low": 0, "medium": 1, "high": 2}
ID2LABEL = {0: "low", 1: "medium", 2: "high"}


def run_inference(session, tokenizer, text: str, max_len: int) -> tuple[str, float]:
    encoding = tokenizer(
        text,
        max_length=max_len,
        padding="max_length",
        truncation=True,
        return_tensors="np",
    )
    feeds = {
        "input_ids": encoding["input_ids"],
        "attention_mask": encoding["attention_mask"],
    }
    probs, score = session.run(None, feeds)
    pred_class = ID2LABEL[int(np.argmax(probs[0]))]
    return pred_class, float(score[0][0])


def main(args: argparse.Namespace) -> None:
    try:
        import onnxruntime as ort
        from sklearn.metrics import (
            accuracy_score,
            classification_report,
            confusion_matrix,
            f1_score,
        )
        from transformers import AutoTokenizer
    except ImportError as e:
        print(f"[ERROR] Missing dependency: {e}")
        print("Install with: pip install onnxruntime scikit-learn transformers")
        return

    model_path = Path(args.model)
    if not model_path.exists():
        print(f"[ERROR] ONNX model not found: {model_path}")
        print("[ERROR] Run scripts/export_onnx.py first.")
        return

    tokenizer_dir = Path(args.tokenizer_dir)
    config_path = tokenizer_dir / "config.json"

    with open(config_path) as f:
        config = json.load(f)

    max_len = config.get("max_len", 64)

    print(f"[SignalBrief] Loading ONNX session from: {model_path}")
    sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_dir))

    print(f"[SignalBrief] Loading dataset: {args.data}")
    df = pd.read_csv(args.data)
    df = df.dropna(subset=["text", "label"])
    df["label_id"] = df["label"].map(LABEL_MAP)
    df = df.dropna(subset=["label_id"])
    print(f"[SignalBrief] Evaluating {len(df)} samples...\n")

    preds, true_labels, latencies = [], [], []

    for _, row in df.iterrows():
        t0 = time.perf_counter()
        pred_class, _ = run_inference(sess, tokenizer, str(row["text"]), max_len)
        latencies.append((time.perf_counter() - t0) * 1000)
        preds.append(LABEL_MAP[pred_class])
        true_labels.append(int(row["label_id"]))

    acc = accuracy_score(true_labels, preds)
    f1 = f1_score(true_labels, preds, average="macro")
    cm = confusion_matrix(true_labels, preds).tolist()
    report = classification_report(true_labels, preds, target_names=["low", "medium", "high"])

    # ── Print results ─────────────────────────
    print("══════════════════════════════════════════")
    print("  SignalBrief — Urgency Classifier Results")
    print("══════════════════════════════════════════")
    print(f"  Model     : {model_path.name}")
    print(f"  Samples   : {len(df)}")
    print(f"  Accuracy  : {acc:.4f}  ({acc*100:.1f}%)")
    print(f"  F1 Macro  : {f1:.4f}")
    print(f"\n{report}")

    print("  Confusion Matrix (rows=actual, cols=predicted):")
    print("  Labels: [low, medium, high]")
    for i, row in enumerate(cm):
        label = ["low", "medium", "high"][i]
        print(f"  {label:8s}: {row}")

    print(f"\n  Latency (ms):")
    print(f"    avg   = {np.mean(latencies):.1f} ms")
    print(f"    p50   = {np.median(latencies):.1f} ms")
    print(f"    p95   = {np.percentile(latencies, 95):.1f} ms")
    print(f"    p99   = {np.percentile(latencies, 99):.1f} ms")

    # Common failure cases
    print(f"\n  Misclassified samples (first 5):")
    misses = [(df.iloc[i]["text"], ID2LABEL[true_labels[i]], ID2LABEL[preds[i]])
              for i in range(len(preds)) if preds[i] != true_labels[i]][:5]
    for text, actual, predicted in misses:
        short = text[:70] + "..." if len(text) > 70 else text
        print(f"    actual={actual:8s} pred={predicted:8s}  \"{short}\"")

    print("\n══════════════════════════════════════════")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate ONNX urgency model")
    parser.add_argument("--model", default="models/urgency_classifier_int8.onnx")
    parser.add_argument("--tokenizer-dir", default="models/urgency_classifier", dest="tokenizer_dir")
    parser.add_argument("--data", default="data/training/urgency_dataset.csv")
    args = parser.parse_args()
    main(args)
