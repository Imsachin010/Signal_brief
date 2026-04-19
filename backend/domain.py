from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Literal
from uuid import uuid4


LocationStatus = Literal["live", "unavailable"]
SignalBand = Literal["low", "medium", "high"]
Priority = Literal["urgent", "actionable", "informational", "ignore"]
MessageStatus = Literal[
    "received",
    "classified",
    "deferred",
    "delivered",
    "summarized",
    "ignored",
]
DecisionAction = Literal["deliver", "defer", "ignore"]
PhoneCardKind = Literal["urgent_delivery", "digest_release"]

# Protocol Section 1 — Action Space
TriageAction = Literal[
    "DELIVER_IMMEDIATE",
    "DELIVER_AUDIO_ONLY",
    "DEFER_TO_ZONE",
    "HOLD_FOR_DIGEST",
    "WHITELIST_OVERRIDE",
    "FALLBACK_VIBRATE",
    "FLUSH_DIGEST",
]


def build_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def signal_band(signal_strength: int) -> SignalBand:
    assert 0 <= signal_strength <= 100
    if signal_strength < 40:
        return "low"
    if signal_strength < 70:
        return "medium"
    return "high"


def to_dict(value: Any) -> Any:
    return asdict(value)


@dataclass(slots=True)
class Classification:
    priority: Priority
    needs_reply: bool
    reason: str
    action_items: list[str] = field(default_factory=list)
    deadline_hint: str = ""


@dataclass(slots=True)
class Message:
    id: str
    sender: str
    text: str
    topic: str
    received_at: str
    priority: Priority
    needs_reply: bool
    deadline_hint: str
    action_items: list[str]
    status: MessageStatus
    decision_reason: str
    triage_score: float = 0.0          # Protocol Section 1 — computed triage score
    urgency_score: float = 0.0         # Raw ML model output [0, 1]
    triage_action: str = ""            # TriageAction string taken for this message


@dataclass(slots=True)
class Digest:
    id: str
    created_at: str
    summary: str
    digest_type: str
    urgent_count: int
    actionable_count: int
    informational_count: int
    ignored_count: int
    action_items: list[str]
    highlighted_message_ids: list[str]
    message_summaries: list[dict[str, str]]


@dataclass(slots=True)
class ReplySuggestion:
    message_id: str
    text: str
    tone: str


@dataclass(slots=True)
class PhoneCard:
    id: str
    kind: PhoneCardKind
    title: str
    body: str
    accent: str
    created_at: str


LocationStatusType = Literal["live", "unavailable"]


@dataclass(slots=True)
class ContextState:
    location_name: str
    latitude: float | None
    longitude: float | None
    accuracy_meters: float | None
    signal_strength: int
    signal_band: SignalBand
    release_window_open: bool
    location_status: LocationStatusType


@dataclass(slots=True)
class Event:
    id: str
    type: str
    timestamp: str
    payload: dict[str, Any]


# ── Protocol Section 1 — Message Feature Vector ───────────────────────────────
@dataclass(slots=True)
class MessageFeatureVector:
    """
    All 15 features used to compute a triage_score per protocol Section 1.
    Assembled once per message in controller.ingest_message().
    """
    # Content signals
    urgency_score: float          # ML model output [0, 1]
    keyword_count: int            # Count of hard urgency keywords
    message_length_bucket: int    # 0=short(<20w), 1=medium, 2=long

    # Sender signals
    sender_tier: int              # 0=unknown, 1=peer, 2=family, 3=manager, 4=whitelist
    user_weight: float            # User-configured sender weight [0.0, 1.0]
    sender_avg_urgency: float     # Historical avg (defaults to 0.5 if no history)

    # Context signals (snapshot at message arrival)
    speed_kmh: float              # 0.0 when no vehicle context
    signal_quality: float         # Normalised [0, 1] from signal_strength
    latency_ms: float             # Estimated from signal quality
    in_coverage_zone: bool
    is_driving: bool
    is_work_hours: bool

    # Derived (computed by compute_triage_score)
    triage_score: float = 0.0


# ── Protocol Section 4 — Decision Log Entry ───────────────────────────────────
@dataclass(slots=True)
class DecisionLogEntry:
    """One row in the decision log panel (DecisionLog.tsx)."""
    message_id: str
    timestamp: str
    sender: str
    message_preview: str          # first 80 chars
    urgency_score: float
    sender_tier: int
    triage_score: float
    action: str                   # TriageAction value
    reason: str                   # Human-readable why
    override_applied: bool        # True if a hard rule fired
