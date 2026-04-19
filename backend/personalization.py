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

# ── Persistence path ──────────────────────────────────────────────────────────
_PREFS_FILE = Path(__file__).parent / "prefs.json"

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

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def get(self) -> UserPreferences:
        return self._prefs

    def update(self, partial: dict[str, Any]) -> None:
        """
        Merge a partial update dict into current preferences and persist.

        Accepted keys
        -------------
        sender_weights          dict[str,float]  — merged (not replaced)
        sender_weights_replace  dict[str,float]  — full replacement
        whitelist               list[str]        — full replacement
        whitelist_add           list[str]        — append items
        whitelist_remove        list[str]        — remove items
        dnd_windows             list[[int,int]]  — full replacement
        defer_threshold         float
        deliver_threshold       float
        driving_speed_threshold_kmh  float
        """
        p = self._prefs

        # Sender weights — merge by default, replace if key says so
        if "sender_weights_replace" in partial:
            p.sender_weights = {k: float(v) for k, v in partial["sender_weights_replace"].items()}
        elif "sender_weights" in partial:
            for k, v in partial["sender_weights"].items():
                p.sender_weights[k.lower()] = float(v)

        # Whitelist — three modes
        if "whitelist" in partial:
            # Full replacement (what PreferencesPanel sends)
            p.whitelist = list(partial["whitelist"])
        if "whitelist_add" in partial:
            existing = {w.lower() for w in p.whitelist}
            for name in partial["whitelist_add"]:
                if name.lower() not in existing:
                    p.whitelist.append(name)
                    existing.add(name.lower())
        if "whitelist_remove" in partial:
            remove_lower = {n.lower() for n in partial["whitelist_remove"]}
            p.whitelist = [w for w in p.whitelist if w.lower() not in remove_lower]

        if "dnd_windows" in partial:
            p.dnd_windows = [tuple(w) for w in partial["dnd_windows"]]  # type: ignore[misc]
        if "defer_threshold" in partial:
            p.defer_threshold = float(partial["defer_threshold"])
        if "deliver_threshold" in partial:
            p.deliver_threshold = float(partial["deliver_threshold"])
        if "driving_speed_threshold_kmh" in partial:
            p.driving_speed_threshold_kmh = float(partial["driving_speed_threshold_kmh"])

        self._save()

    def reset_to_defaults(self) -> None:
        """Wipe prefs.json and reload defaults."""
        self._prefs = UserPreferences()
        self._save()

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
