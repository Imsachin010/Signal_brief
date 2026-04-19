"""
SignalBrief — ONNX Export Script
=================================
Converts the trained DistilBERT urgency classifier to ONNX format
with INT8 dynamic quantization for embedded/automotive deployment.

Requirements
------------
  pip install onnx onnxruntime

Usage
-----
  python scripts/export_onnx.py
  python scripts/export_onnx.py --model models/urgency_classifier --output models/urgency_classifier.onnx

Output
------
  models/urgency_classifier.onnx          Full precision ONNX
  models/urgency_classifier_int8.onnx     INT8 quantized (~4x smaller)
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from transformers import AutoModel, AutoTokenizer

# ── Rebuild model class (must match train script) ──────────────────────────────
class UrgencyClassifier(nn.Module):
    def __init__(self, base_model, num_labels: int = 3, dropout: float = 0.2) -> None:
        super().__init__()
        self.base = base_model
        hidden = self.base.config.hidden_size
        self.dropout = nn.Dropout(dropout)
        self.classifier = nn.Linear(hidden, num_labels)
        self.score_head = nn.Sequential(
            nn.Linear(hidden, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
            nn.Sigmoid(),
        )

    def forward(self, input_ids, attention_mask):
        outputs = self.base(input_ids=input_ids, attention_mask=attention_mask)
        cls_output = outputs.last_hidden_state[:, 0, :]
        cls_output = self.dropout(cls_output)
        logits = self.classifier(cls_output)
        score = self.score_head(cls_output).squeeze(-1)
        return logits, score


# ── ONNX wrapper — export only the classification path ────────────────────────
class ONNXExportWrapper(nn.Module):
    """Wraps UrgencyClassifier to expose only the ONNX-compatible forward."""

    def __init__(self, model: UrgencyClassifier) -> None:
        super().__init__()
        self.model = model

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor):
        logits, score = self.model(input_ids, attention_mask)
        probs = torch.softmax(logits, dim=-1)   # shape (B, 3)
        return probs, score.unsqueeze(-1)        # both exported


def main(args: argparse.Namespace) -> None:
    model_dir = Path(args.model)
    output_path = Path(args.output)
    output_int8 = output_path.parent / (output_path.stem + "_int8.onnx")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    config_path = model_dir / "config.json"
    weights_path = model_dir / "best_model.pt"

    if not weights_path.exists():
        print(f"[ERROR] Model weights not found at {weights_path}")
        print("[ERROR] Run scripts/train_urgency_model.py first.")
        return

    with open(config_path) as f:
        config = json.load(f)

    print(f"[SignalBrief] Loading trained model from: {model_dir}")
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    base = AutoModel.from_pretrained(config["model_name"])

    model = UrgencyClassifier(base, num_labels=3)
    model.load_state_dict(torch.load(weights_path, map_location="cpu"))
    model.eval()

    export_model = ONNXExportWrapper(model)
    export_model.eval()

    # ── Dummy input ───────────────────────────
    print("[SignalBrief] Creating dummy input...")
    dummy_text = "URGENT: Server is down, customers can't login - call NOW"
    encoding = tokenizer(
        dummy_text,
        max_length=config["max_len"],
        padding="max_length",
        truncation=True,
        return_tensors="pt",
    )
    dummy_input_ids = encoding["input_ids"]
    dummy_attention_mask = encoding["attention_mask"]

    # ── Export to ONNX ────────────────────────
    print(f"[SignalBrief] Exporting to ONNX: {output_path}")
    torch.onnx.export(
        export_model,
        (dummy_input_ids, dummy_attention_mask),
        str(output_path),
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        input_names=["input_ids", "attention_mask"],
        output_names=["class_probs", "urgency_score"],
        dynamic_axes={
            "input_ids": {0: "batch_size"},
            "attention_mask": {0: "batch_size"},
            "class_probs": {0: "batch_size"},
            "urgency_score": {0: "batch_size"},
        },
    )
    print(f"[SignalBrief] ONNX exported → {output_path}")
    print(f"[SignalBrief] File size: {output_path.stat().st_size / 1e6:.1f} MB")

    # ── Verify ONNX ───────────────────────────
    try:
        import onnx
        onnx_model = onnx.load(str(output_path))
        onnx.checker.check_model(onnx_model)
        print("[SignalBrief] ONNX model check: PASSED ✓")
    except ImportError:
        print("[SignalBrief] onnx not installed — skipping verification")

    # ── INT8 Quantization ─────────────────────
    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic

        print(f"\n[SignalBrief] Quantizing to INT8: {output_int8}")
        quantize_dynamic(
            str(output_path),
            str(output_int8),
            weight_type=QuantType.QInt8,
        )
        size_mb = output_int8.stat().st_size / 1e6
        print(f"[SignalBrief] INT8 model saved → {output_int8}")
        print(f"[SignalBrief] INT8 file size: {size_mb:.1f} MB")
    except ImportError:
        print("[SignalBrief] onnxruntime.quantization not available — skipping INT8 step")

    # ── Latency benchmark ─────────────────────
    try:
        import onnxruntime as ort

        print("\n[SignalBrief] Running latency benchmark (20 runs)...")
        sess = ort.InferenceSession(str(output_path), providers=["CPUExecutionProvider"])
        feeds = {
            "input_ids": dummy_input_ids.numpy(),
            "attention_mask": dummy_attention_mask.numpy(),
        }
        # Warmup
        for _ in range(3):
            sess.run(None, feeds)

        times = []
        for _ in range(20):
            t0 = time.perf_counter()
            out = sess.run(None, feeds)
            times.append((time.perf_counter() - t0) * 1000)

        probs, score = out
        pred_class = ["low", "medium", "high"][int(np.argmax(probs[0]))]
        print(f"[SignalBrief] Sample prediction: class={pred_class}, urgency_score={score[0][0]:.3f}")
        print(f"[SignalBrief] Latency — avg: {np.mean(times):.1f}ms | p95: {np.percentile(times, 95):.1f}ms")
    except ImportError:
        print("[SignalBrief] onnxruntime not available — skipping benchmark")

    print(f"\n[SignalBrief] Export complete.")
    print(f"  Full ONNX : {output_path}")
    print(f"  INT8 ONNX : {output_int8}")
    print(f"\n[SignalBrief] Next step: the backend will auto-load the INT8 model on startup.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export DistilBERT model to ONNX")
    parser.add_argument("--model", default="models/urgency_classifier", help="Trained model dir")
    parser.add_argument("--output", default="models/urgency_classifier.onnx", help="Output ONNX path")
    args = parser.parse_args()
    main(args)
