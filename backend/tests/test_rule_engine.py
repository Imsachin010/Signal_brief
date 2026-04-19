from __future__ import annotations

import unittest

from backend.domain import Classification
from backend.domain import ContextState
from backend.rule_engine import decide


class RuleEngineTests(unittest.TestCase):
    def test_urgent_always_delivers(self) -> None:
        classification = Classification(
            priority="urgent",
            needs_reply=True,
            reason="urgent",
        )
        context = ContextState(
            location_name="Tunnel",
            latitude=None,
            longitude=None,
            accuracy_meters=None,
            signal_strength=15,
            signal_band="low",
            release_window_open=False,
            location_status="live",
        )

        decision = decide(classification, context)

        self.assertEqual(decision.action, "deliver")

    def test_informational_defers_on_low_signal(self) -> None:
        classification = Classification(
            priority="informational",
            needs_reply=False,
            reason="info",
        )
        context = ContextState(
            location_name="Tunnel",
            latitude=None,
            longitude=None,
            accuracy_meters=None,
            signal_strength=22,
            signal_band="low",
            release_window_open=False,
            location_status="live",
        )

        decision = decide(classification, context)

        self.assertEqual(decision.action, "defer")

    def test_informational_defers_on_medium_signal(self) -> None:
        classification = Classification(
            priority="informational",
            needs_reply=False,
            reason="info",
        )
        context = ContextState(
            location_name="City",
            latitude=None,
            longitude=None,
            accuracy_meters=None,
            signal_strength=55,
            signal_band="medium",
            release_window_open=False,
            location_status="live",
        )

        decision = decide(classification, context)

        self.assertEqual(decision.action, "defer")

    def test_actionable_delivers_on_medium_signal(self) -> None:
        classification = Classification(
            priority="actionable",
            needs_reply=True,
            reason="actionable",
        )
        context = ContextState(
            location_name="City",
            latitude=None,
            longitude=None,
            accuracy_meters=None,
            signal_strength=65,
            signal_band="medium",
            release_window_open=False,
            location_status="live",
        )

        decision = decide(classification, context)

        self.assertEqual(decision.action, "deliver")

    def test_high_signal_delivers_all_non_ignored(self) -> None:
        classification = Classification(
            priority="actionable",
            needs_reply=True,
            reason="actionable",
        )
        context = ContextState(
            location_name="Highway",
            latitude=None,
            longitude=None,
            accuracy_meters=None,
            signal_strength=85,
            signal_band="high",
            release_window_open=False,
            location_status="live",
        )

        decision = decide(classification, context)

        self.assertEqual(decision.action, "deliver")


if __name__ == "__main__":
    unittest.main()
