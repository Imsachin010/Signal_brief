"""
SignalBrief -- Geo-Zone System
================================
Protocol Section 3 -- Zone transition detection and flush triggering.

Tracks the car's movement between signal quality zones (GREEN/YELLOW/RED/DEAD)
and fires events when zone transitions happen:

  DEAD  -> GREEN/YELLOW  =>  flush deferred queue
  GREEN -> DEAD          =>  hold new messages
  *     -> RED           =>  restrict to critical-only
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


# ---- Zone Definitions -------------------------------------------------------

ZONE_COLOURS = ("GREEN", "YELLOW", "RED", "DEAD")

# Thresholds (must match context_engine.py)
ZONE_THRESHOLDS = {
    "GREEN":  0.70,
    "YELLOW": 0.40,
    "RED":    0.15,
    "DEAD":   0.00,
}


def classify_zone(signal_quality: float) -> str:
    """
    Map a signal_quality [0,1] to a zone colour string.
    """
    if signal_quality >= ZONE_THRESHOLDS["GREEN"]:
        return "GREEN"
    if signal_quality >= ZONE_THRESHOLDS["YELLOW"]:
        return "YELLOW"
    if signal_quality >= ZONE_THRESHOLDS["RED"]:
        return "RED"
    return "DEAD"


# ---- Zone Transition Event ---------------------------------------------------

@dataclass
class ZoneTransitionEvent:
    """Fired whenever the car crosses a zone boundary."""
    from_zone: str
    to_zone: str
    location_label: str
    signal_quality: float
    # What the system should do:
    should_flush_queue: bool       # True when recovering from DEAD/RED
    should_hold_messages: bool     # True when entering DEAD
    should_restrict_critical: bool # True when in RED
    flush_reason: str


# ---- Transition Logic --------------------------------------------------------

def evaluate_transition(
    prev_zone: str,
    new_zone: str,
    location_label: str,
    signal_quality: float,
) -> Optional[ZoneTransitionEvent]:
    """
    Returns a ZoneTransitionEvent if the zone changed, else None.
    """
    if prev_zone == new_zone:
        return None

    should_flush = False
    should_hold = False
    should_restrict = False
    flush_reason = ""

    # --- Recovery transitions (bad -> good) ---
    if prev_zone == "DEAD" and new_zone in ("GREEN", "YELLOW", "RED"):
        should_flush = True
        flush_reason = f"Leaving DEAD zone at {location_label} -- flushing deferred queue."

    elif prev_zone == "RED" and new_zone in ("GREEN", "YELLOW"):
        should_flush = True
        flush_reason = f"Signal improved to {new_zone} at {location_label} -- releasing queue."

    elif prev_zone == "YELLOW" and new_zone == "GREEN":
        should_flush = True
        flush_reason = f"Entered GREEN zone at {location_label} -- delivering all deferred."

    # --- Degradation transitions ---
    if new_zone == "DEAD":
        should_hold = True

    if new_zone == "RED":
        should_restrict = True

    return ZoneTransitionEvent(
        from_zone=prev_zone,
        to_zone=new_zone,
        location_label=location_label,
        signal_quality=signal_quality,
        should_flush_queue=should_flush,
        should_hold_messages=should_hold,
        should_restrict_critical=should_restrict,
        flush_reason=flush_reason,
    )


# ---- Geo Zone Tracker --------------------------------------------------------

class GeoZoneTracker:
    """
    Tracks the vehicle's current zone.
    Call update(signal_quality, label) after each context_engine.step().
    Register callbacks to react to zone transitions.
    """

    def __init__(self) -> None:
        self._current_zone: str = "GREEN"
        self._callbacks: list[Callable[[ZoneTransitionEvent], None]] = []
        self._history: list[ZoneTransitionEvent] = []

    @property
    def current_zone(self) -> str:
        return self._current_zone

    def register_callback(self, fn: Callable[[ZoneTransitionEvent], None]) -> None:
        """Register a function to call when a zone transition fires."""
        self._callbacks.append(fn)

    def update(self, signal_quality: float, location_label: str) -> Optional[ZoneTransitionEvent]:
        """
        Feed a new signal quality reading.
        Returns a ZoneTransitionEvent if zone changed, else None.
        Callbacks are called synchronously.
        """
        new_zone = classify_zone(signal_quality)
        event = evaluate_transition(
            prev_zone=self._current_zone,
            new_zone=new_zone,
            location_label=location_label,
            signal_quality=signal_quality,
        )
        if event:
            self._current_zone = new_zone
            self._history.append(event)
            if len(self._history) > 50:
                self._history = self._history[-50:]
            for cb in self._callbacks:
                try:
                    cb(event)
                except Exception:
                    pass
        else:
            self._current_zone = new_zone

        return event

    def zone_history(self, limit: int = 20) -> list[dict]:
        """Return recent zone transitions as plain dicts."""
        tail = self._history[-limit:]
        return [
            {
                "from_zone": e.from_zone,
                "to_zone": e.to_zone,
                "location_label": e.location_label,
                "signal_quality": round(e.signal_quality, 3),
                "should_flush_queue": e.should_flush_queue,
                "should_hold_messages": e.should_hold_messages,
                "flush_reason": e.flush_reason,
            }
            for e in reversed(tail)
        ]

    def reset(self) -> None:
        self._current_zone = "GREEN"
        self._history.clear()


# Module singleton
geo_tracker = GeoZoneTracker()
