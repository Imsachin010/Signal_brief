"""
SignalBrief — Personalization Layer
=====================================
Protocol Section 4 — User Preferences, sender tiers, DND windows,
whitelist management, and sender weight resolution.

Changes vs v1:
 - Preferences are persisted to a JSON file (prefs.json in the backend dir).
   They survive server restarts. update() always writes through to disk.
 - update() now handles a full `whitelist` list (replace), not just add/remove.
 - to_dict() is the canonical serialisation shape — same as what the frontend POST.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── Persistence paths ─────────────────────────────────────────────────────────
_PREFS_FILE   = Path(__file__).parent / "prefs.json"
_HISTORY_FILE = Path(__file__).parent / "pref_history.json"

# ─────────────────────────────────────────────────────────────────────────────
# Sender Tier Map: pattern substring → tier (0=unknown … 4=whitelist)
# Protocol Table 4.1
# ─────────────────────────────────────────────────────────────────────────────
_TIER_PATTERNS: list[tuple[str, int]] = [
    # Tier 4 — whitelist (checked separately via is_whitelisted)
    # Tier 3 — manager / boss signals
    ("manager", 3), ("boss", 3), ("ceo", 3), ("director", 3),
    ("vp ", 3),    ("lead", 3), ("hr", 3), ("recruiter", 3),
    # Tier 2 — family
    ("mom", 2), ("dad", 2), ("wife", 2), ("husband", 2),
    ("sister", 2), ("brother", 2), ("family", 2), ("home", 2),
    # Tier 1 — peers / colleagues (default fall-through)
]

_DEFAULT_SENDER_WEIGHTS: dict[str, float] = {
    "mom": 1.0,
    "dad": 1.0,
    "boss": 0.9,
    "manager": 0.9,
}

_DEFAULT_WHITELIST: list[str] = ["Mom", "Dad", "Emergency", "Hospital"]

_DEFAULT_DND_WINDOWS: list[tuple[int, int]] = [(22, 7)]

_URGENT_KEYWORDS: frozenset[str] = frozenset({
    "urgent", "asap", "immediately", "emergency", "sos", "critical",
    "right now", "call me now", "call now", "on fire", "breach",
    "hack", "ransomware", "alert", "escalation", "p0", "p1",
    "production down", "prod down", "failure", "fire", "evacuate",
})


# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class UserPreferences:
    sender_weights: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_SENDER_WEIGHTS)
    )
    whitelist: list[str] = field(               # ordered, displayable list
        default_factory=lambda: list(_DEFAULT_WHITELIST)
    )
    dnd_windows: list[tuple[int, int]] = field(
        default_factory=lambda: list(_DEFAULT_DND_WINDOWS)
    )
    driving_speed_threshold_kmh: float = 15.0
    defer_threshold: float = 0.45
    deliver_threshold: float = 0.65


class PreferencesManager:
    """
    Singleton preferences store with file persistence.
    Loads from prefs.json on first access; writes through on every update().
    """

    def __init__(self) -> None:
        self._prefs = self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> UserPreferences:
        """Load from prefs.json or return defaults."""
        if _PREFS_FILE.exists():
            try:
                raw = json.loads(_PREFS_FILE.read_text(encoding="utf-8"))
                p = UserPreferences()
                if "sender_weights" in raw:
                    p.sender_weights = {k: float(v) for k, v in raw["sender_weights"].items()}
                if "whitelist" in raw:
                    p.whitelist = list(raw["whitelist"])
                if "dnd_windows" in raw:
                    p.dnd_windows = [tuple(w) for w in raw["dnd_windows"]]  # type: ignore[misc]
                if "defer_threshold" in raw:
                    p.defer_threshold = float(raw["defer_threshold"])
                if "deliver_threshold" in raw:
                    p.deliver_threshold = float(raw["deliver_threshold"])
                if "driving_speed_threshold_kmh" in raw:
                    p.driving_speed_threshold_kmh = float(raw["driving_speed_threshold_kmh"])
                log.info("Preferences loaded from %s", _PREFS_FILE)
                return p
            except Exception as exc:
                log.warning("Could not load prefs.json (%s) — using defaults.", exc)
        return UserPreferences()

    def _save(self) -> None:
        """Write current state to prefs.json."""
        try:
            _PREFS_FILE.write_text(
                json.dumps(self.to_dict(), indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            log.warning("Could not save prefs.json: %s", exc)

    def _log_change(self, summary: str, changed_fields: list[str]) -> None:
        """Append one entry to pref_history.json (capped at 200 entries)."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "changed_fields": changed_fields,
        }
        history: list[dict] = []
        if _HISTORY_FILE.exists():
            try:
                history = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
            except Exception:
                history = []
        history.append(entry)
        # Keep tail — avoid unbounded growth
        history = history[-200:]
        try:
            _HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")
        except Exception as exc:
            log.warning("Could not write pref_history.json: %s", exc)

    def get_history(self, limit: int = 30) -> list[dict]:
        """Return the most recent `limit` preference change entries (newest first)."""
        if not _HISTORY_FILE.exists():
            return []
        try:
            history: list[dict] = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
            return list(reversed(history[-limit:]))
        except Exception:
            return []

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def get(self) -> UserPreferences:
        return self._prefs

    def update(self, partial: dict[str, Any]) -> None:
        """
        Merge a partial update dict into current preferences and persist.
        Also appends a timestamped entry to pref_history.json.
        """
        p = self._prefs
        changed_fields: list[str] = []
        summaries: list[str] = []

        if "sender_weights_replace" in partial:
            p.sender_weights = {k: float(v) for k, v in partial["sender_weights_replace"].items()}
            changed_fields.append("sender_weights")
            summaries.append(f"Sender weights replaced ({len(p.sender_weights)} entries)")
        elif "sender_weights" in partial:
            for k, v in partial["sender_weights"].items():
                p.sender_weights[k.lower()] = float(v)
            changed_fields.append("sender_weights")
            summaries.append(f"Sender weights updated: {list(partial['sender_weights'].keys())}")

        if "whitelist" in partial:
            old = set(p.whitelist)
            p.whitelist = list(partial["whitelist"])
            added = sorted(set(p.whitelist) - old)
            removed = sorted(old - set(p.whitelist))
            changed_fields.append("whitelist")
            parts = []
            if added:   parts.append(f"added {added}")
            if removed: parts.append(f"removed {removed}")
            summaries.append("Whitelist: " + (" | ".join(parts) or "no change"))
        if "whitelist_add" in partial:
            existing = {w.lower() for w in p.whitelist}
            newly = [n for n in partial["whitelist_add"] if n.lower() not in existing]
            for name in newly:
                p.whitelist.append(name)
            if newly:
                changed_fields.append("whitelist")
                summaries.append(f"Whitelist: added {newly}")
        if "whitelist_remove" in partial:
            remove_lower = {n.lower() for n in partial["whitelist_remove"]}
            before = set(p.whitelist)
            p.whitelist = [w for w in p.whitelist if w.lower() not in remove_lower]
            removed = sorted(before - set(p.whitelist))
            if removed:
                changed_fields.append("whitelist")
                summaries.append(f"Whitelist: removed {removed}")

        if "dnd_windows" in partial:
            p.dnd_windows = [tuple(w) for w in partial["dnd_windows"]]  # type: ignore[misc]
            changed_fields.append("dnd_windows")
            summaries.append(f"DND windows set to {p.dnd_windows}")
        if "defer_threshold" in partial:
            old = p.defer_threshold
            p.defer_threshold = float(partial["defer_threshold"])
            changed_fields.append("defer_threshold")
            summaries.append(f"Defer threshold: {old:.2f} → {p.defer_threshold:.2f}")
        if "deliver_threshold" in partial:
            old = p.deliver_threshold
            p.deliver_threshold = float(partial["deliver_threshold"])
            changed_fields.append("deliver_threshold")
            summaries.append(f"Deliver threshold: {old:.2f} → {p.deliver_threshold:.2f}")
        if "driving_speed_threshold_kmh" in partial:
            old = p.driving_speed_threshold_kmh
            p.driving_speed_threshold_kmh = float(partial["driving_speed_threshold_kmh"])
            changed_fields.append("driving_speed_threshold_kmh")
            summaries.append(f"Driving threshold: {old:.0f} → {p.driving_speed_threshold_kmh:.0f} km/h")

        self._save()
        if changed_fields:
            self._log_change(" | ".join(summaries) or "No changes", changed_fields)

    def reset_to_defaults(self) -> None:
        """Wipe prefs.json and reload defaults."""
        self._prefs = UserPreferences()
        self._save()
        self._log_change("All preferences reset to protocol defaults", ["all"])

    # ── Queries ──────────────────────────────────────────────────────────────

    def is_whitelisted(self, sender: str) -> bool:
        return any(w.lower() in sender.lower() for w in self._prefs.whitelist)

    def get_sender_tier(self, sender: str) -> int:
        """Returns tier 0–4 for the given sender name."""
        if self.is_whitelisted(sender):
            return 4
        # High sender weight also upgrades tier
        if self.get_sender_weight(sender) >= 0.85:
            return 3
        s = sender.lower()
        for pattern, tier in _TIER_PATTERNS:
            if pattern in s:
                return tier
        return 1   # default peer tier

    def get_sender_weight(self, sender: str) -> float:
        """Returns user-configured weight [0.0, 1.0]. Default = 0.5."""
        s = sender.lower()
        for key, weight in self._prefs.sender_weights.items():
            if key.lower() in s:
                return weight
        return 0.5

    def is_in_dnd(self, hour: int | None = None) -> bool:
        """Returns True if the current hour falls in any DND window."""
        if hour is None:
            hour = datetime.now(timezone.utc).hour
        for start, end in self._prefs.dnd_windows:
            if start > end:   # crosses midnight
                if hour >= start or hour < end:
                    return True
            else:
                if start <= hour < end:
                    return True
        return False

    def count_urgent_keywords(self, text: str) -> int:
        """Count how many hard urgency keyword fragments appear in text."""
        lower = text.lower()
        return sum(1 for kw in _URGENT_KEYWORDS if kw in lower)

    def to_dict(self) -> dict[str, Any]:
        p = self._prefs
        hour = datetime.now(timezone.utc).hour
        return {
            "sender_weights": dict(p.sender_weights),
            "whitelist": sorted(p.whitelist),
            "dnd_windows": [list(w) for w in p.dnd_windows],
            "driving_speed_threshold_kmh": p.driving_speed_threshold_kmh,
            "defer_threshold": p.defer_threshold,
            "deliver_threshold": p.deliver_threshold,
            # Live status flags — consumed by frontend
            "dnd_active_now": self.is_in_dnd(hour),
            "current_hour_utc": hour,
        }


# Module-level singleton — shared across controller and rule_engine
preferences = PreferencesManager()
