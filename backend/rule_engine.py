"""
SignalBrief — Rule Engine
==========================
Implements the full triage pipeline from the SignalBrief_Rebuilt_Protocol:

  Section 1 — Triage Score Formula
  ---------------------------------
  score = urgency   * 0.40
        + sender    * 0.25
        + signal    * 0.15
        + context   * 0.10
        + keyword   * 0.10

  Section 4 — Hard Override Rules (applied AFTER score, in order)
  ---------------------------------------------------------------
  Rule 1  Whitelist sender         → WHITELIST_OVERRIDE (always deliver)
  Rule 2  Urgency > 0.85           → DELIVER_IMMEDIATE  (bypass everything)
  Rule 3  DND window + not white   → HOLD_FOR_DIGEST
  Rule 4  Driving + urgent         → DELIVER_AUDIO_ONLY
  Rule 5  No signal / offline      → FALLBACK_VIBRATE   (urgent only)

  Tail-end (score-gated, after override rules pass)
  -------------------------------------------------------
  score >= deliver_threshold  → DELIVER_IMMEDIATE
  score >= defer_threshold    → DEFER_TO_ZONE
  else                        → HOLD_FOR_DIGEST
"""

from __future__ import annotations

from dataclasses import dataclass

from .domain import (
    Classification,
    ContextState,
    DecisionAction,
    DecisionLogEntry,
    MessageFeatureVector,
    TriageAction,
    utc_now,
)
from .personalization import PreferencesManager


# ─────────────────────────────────────────────────────────────────────────────
# Legacy Decision (keeps existing controller.py working unchanged)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class Decision:
    action: DecisionAction
    reason: str


def current_rule_text(context: ContextState) -> str:
    if context.location_status == "unavailable":
        return "Location unavailable. Using neutral signal."
    if context.signal_band == "low":
        return "Deferring non-urgent notifications due to weak signal."
    if context.signal_band == "medium":
        return "Delivering actionable items, deferring informational."
    return "Delivering all non-ignored notifications immediately."


def decide(classification: Classification, context: ContextState) -> Decision:
    """Legacy simple decision — still used when no FeatureVector is available."""
    if classification.priority == "urgent":
        return Decision("deliver", "Urgent items always bypass deferral.")
    if classification.priority == "ignore":
        return Decision("ignore", "Ignored content is tracked but never delivered.")
    if context.signal_band == "low":
        return Decision("defer", "Deferred because signal is too weak.")
    if context.signal_band == "medium":
        if classification.priority == "informational":
            return Decision("defer", "Deferred informational during medium signal.")
        return Decision("deliver", "Delivered actionable during medium signal.")
    return Decision("deliver", "Delivered because signal is high.")


# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — Triage Score Formula
# ─────────────────────────────────────────────────────────────────────────────

# Protocol weights (must sum to 1.0)
_W_URGENCY  = 0.10
_W_SENDER   = 0.25
_W_SIGNAL   = 0.15
_W_CONTEXT  = 0.40
_W_KEYWORD  = 0.10


def compute_triage_score(f: MessageFeatureVector) -> float:
    """
    Protocol Section 1 formula.

    Returns a float in [0, 1].  Higher = more likely to deliver immediately.
    """
    # Component 1 — urgency (ML model score)
    urgency_component = f.urgency_score

    # Component 2 — sender (tier normalised + user weight blended)
    sender_component = (f.sender_tier / 4.0) * f.user_weight

    # Component 3 — signal quality (already in [0, 1])
    signal_component = f.signal_quality

    # Component 4 — context availability
    # Penalise when driving (distraction), boost during work hours
    context_component = 0.5           # neutral baseline
    if f.in_coverage_zone:
        context_component += 0.25
    if f.is_work_hours:
        context_component += 0.15
    if f.is_driving:
        context_component -= 0.20     # reduce non-critical load while driving
    context_component = max(0.0, min(1.0, context_component))

    # Component 5 — hard keyword boost (normalise 0–3+ hits → [0, 1])
    keyword_component = min(f.keyword_count / 3.0, 1.0)

    score = (
        _W_URGENCY * urgency_component
        + _W_SENDER * sender_component
        + _W_SIGNAL * signal_component
        + _W_CONTEXT * context_component
        + _W_KEYWORD * keyword_component
    )
    return round(max(0.0, min(1.0, score)), 4)


# ─────────────────────────────────────────────────────────────────────────────
# Section 4 — Hard Override Rules + Tail-End Gating
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class TriageResult:
    """Returned by apply_triage_rules(). Contains everything needed to act."""
    action: str          # TriageAction literal
    reason: str
    override_applied: bool
    triage_score: float
    log_entry: DecisionLogEntry


def apply_triage_rules(
    *,
    features: MessageFeatureVector,
    message_id: str,
    sender: str,
    text: str,
    signal_offline: bool,
    prefs: PreferencesManager,
) -> TriageResult:
    """
    Runs all 5 hard override rules (Section 4) then falls through to
    score-gated tail-end delivery logic.

    Parameters
    ----------
    features       : pre-computed MessageFeatureVector (call compute_triage_score first)
    message_id     : used for the DecisionLogEntry
    sender         : original sender string
    text           : original message text
    signal_offline : True if signal_quality == 0 / no coverage
    prefs          : PreferencesManager singleton

    Returns
    -------
    TriageResult   — action + reason + log entry
    """
    score = features.triage_score
    p = prefs.get()

    # ── RULE 1: Whitelist always delivers ─────────────────────────────────
    if prefs.is_whitelisted(sender):
        return _result(
            "WHITELIST_OVERRIDE",
            f"Sender '{sender}' is on the whitelist — always deliver.",
            override=True,
            score=score,
            msg_id=message_id,
            sender=sender,
            text=text,
            features=features,
        )

    # ── RULE 2: Very high urgency bypasses everything ─────────────────────
    if features.urgency_score >= 0.85:
        return _result(
            "DELIVER_IMMEDIATE",
            f"Urgency score {features.urgency_score:.3f} exceeds 0.85 hard threshold.",
            override=True,
            score=score,
            msg_id=message_id,
            sender=sender,
            text=text,
            features=features,
        )

    # ── RULE 2b: Critical keywords bypass everything ─────────────────────
    if features.keyword_count > 0:
        return _result(
            "KEYWORD_OVERRIDE",
            "Message contains a highly critical keyword (e.g. hospital, emergency).",
            override=True,
            score=score,
            msg_id=message_id,
            sender=sender,
            text=text,
            features=features,
        )

    # ── RULE 3: DND window — only whitelist passes (already handled above) ─
    if prefs.is_in_dnd(features.hour_of_day):
        return _result(
            "HOLD_FOR_DIGEST",
            "DND window active — holding for digest.",
            override=True,
            score=score,
            msg_id=message_id,
            sender=sender,
            text=text,
            features=features,
        )

    # ── RULE 4: Driving + anything urgent → audio-only (no visual) ────────
    if features.is_driving and features.urgency_score >= 0.60:
        return _result(
            "DELIVER_AUDIO_ONLY",
            f"Driving detected (speed={features.speed_kmh:.0f} km/h) — audio-only delivery.",
            override=True,
            score=score,
            msg_id=message_id,
            sender=sender,
            text=text,
            features=features,
        )

    # ── RULE 5: Offline / no coverage — vibrate for urgent, else hold ─────
    if signal_offline:
        if features.urgency_score >= 0.70:
            return _result(
                "FALLBACK_VIBRATE",
                "No network coverage — vibration-only alert for urgent message.",
                override=True,
                score=score,
                msg_id=message_id,
                sender=sender,
                text=text,
                features=features,
            )
        return _result(
            "HOLD_FOR_DIGEST",
            "No network coverage — queued for delivery when signal returns.",
            override=True,
            score=score,
            msg_id=message_id,
            sender=sender,
            text=text,
            features=features,
        )

    # ── TAIL END: Score-gated delivery ────────────────────────────────────
    # No hard rule fired — triage score decides.
    
    # Scale thresholds based on signal. Better signal -> lower threshold -> more throughput.
    # At 1.0 signal, threshold drops by 0.20. At 0.0 signal, shifts up by 0.10.
    signal_shift = 0.10 - (features.signal_quality * 0.30)
    
    eff_deliver = max(0.10, min(0.95, p.deliver_threshold + signal_shift))
    eff_defer   = max(0.05, min(0.90, p.defer_threshold + signal_shift))

    if score >= eff_deliver:
        return _result(
            "DELIVER_IMMEDIATE",
            f"Score {score:.3f} >= dynamic deliver threshold {eff_deliver:.2f} (Base: {p.deliver_threshold}).",
            override=False,
            score=score,
            msg_id=message_id,
            sender=sender,
            text=text,
            features=features,
        )

    if score >= eff_defer:
        return _result(
            "DEFER_TO_ZONE",
            f"Score {score:.3f} — deferred because below dynamic {eff_deliver:.2f}.",
            override=False,
            score=score,
            msg_id=message_id,
            sender=sender,
            text=text,
            features=features,
        )

    return _result(
        "HOLD_FOR_DIGEST",
        f"Triage score {score:.3f} < defer threshold {p.defer_threshold:.2f} — digest only.",
        override=False,
        score=score,
        msg_id=message_id,
        sender=sender,
        text=text,
        features=features,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _result(
    action: str,
    reason: str,
    *,
    override: bool,
    score: float,
    msg_id: str,
    sender: str,
    text: str,
    features: MessageFeatureVector,
) -> TriageResult:
    log_entry = DecisionLogEntry(
        message_id=msg_id,
        timestamp=utc_now(),
        sender=sender,
        message_preview=text[:80],
        urgency_score=features.urgency_score,
        sender_tier=features.sender_tier,
        triage_score=score,
        action=action,
        reason=reason,
        override_applied=override,
    )
    return TriageResult(
        action=action,
        reason=reason,
        override_applied=override,
        triage_score=score,
        log_entry=log_entry,
    )


# ── Map TriageAction → legacy DecisionAction for controller compatibility ─────

def triage_to_decision(action: str) -> Decision:
    """
    Converts a TriageAction string to the legacy Decision used
    by the existing controller code that calls decide().
    """
    deliver_set = {"DELIVER_IMMEDIATE", "WHITELIST_OVERRIDE", "KEYWORD_OVERRIDE",
                   "DELIVER_AUDIO_ONLY", "FALLBACK_VIBRATE", "FLUSH_DIGEST"}
    defer_set   = {"DEFER_TO_ZONE"}
    # HOLD_FOR_DIGEST → maps to defer in legacy terms
    if action in deliver_set:
        return Decision("deliver", action)
    if action in defer_set:
        return Decision("defer", action)
    return Decision("defer", action)   # HOLD_FOR_DIGEST
