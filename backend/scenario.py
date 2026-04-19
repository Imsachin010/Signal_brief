from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Literal


ScenarioKind = Literal["message"]


@dataclass(slots=True)
class ScenarioStep:
    delay_seconds: float
    kind: ScenarioKind
    payload: dict[str, Any]


def build_default_scenario() -> list[ScenarioStep]:
    return [
        ScenarioStep(
            delay_seconds=0.08,
            kind="message",
            payload={
                "sender": "Nisha - Product",
                "topic": "pricing",
                "text": "Can you review the dealership pricing note before 6 PM?",
            },
        ),
        ScenarioStep(
            delay_seconds=0.08,
            kind="message",
            payload={
                "sender": "Rewards Mall",
                "topic": "promo",
                "text": "Flash sale: 40% off accessories today only.",
            },
        ),
        ScenarioStep(
            delay_seconds=0.08,
            kind="message",
            payload={
                "sender": "Parents",
                "topic": "family",
                "text": "We reached home. No rush, just keeping you posted.",
            },
        ),
        ScenarioStep(
            delay_seconds=0.08,
            kind="message",
            payload={
                "sender": "Priya",
                "topic": "family",
                "text": "Call me now. Dad is at the clinic and they need the insurance OTP.",
            },
        ),
        ScenarioStep(
            delay_seconds=0.08,
            kind="message",
            payload={
                "sender": "Ops Desk",
                "topic": "customer",
                "text": "Customer escalated the dashboard issue. Need a response tonight.",
            },
        ),
        ScenarioStep(
            delay_seconds=0.08,
            kind="message",
            payload={
                "sender": "Rohit",
                "topic": "meeting",
                "text": "Please confirm if you can join the 7 PM partner sync.",
            },
        ),
        ScenarioStep(
            delay_seconds=0.08,
            kind="message",
            payload={
                "sender": "Daily Brief",
                "topic": "newsletter",
                "text": "Top five EV launches this week in one quick read.",
            },
        ),
        ScenarioStep(
            delay_seconds=0.08,
            kind="message",
            payload={
                "sender": "Anika - Manager",
                "topic": "status",
                "text": "When you park, send me the release readiness summary.",
            },
        ),
    ]
