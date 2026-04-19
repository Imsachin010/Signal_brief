from __future__ import annotations

import unittest

from backend.ai_service import AIService
from backend.controller import SignalBriefController


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.controller = SignalBriefController(
            AIService(mode="fallback", api_key=None)
        )

    async def test_urgent_message_delivers_during_low_signal(self) -> None:
        await self.controller.set_demo_signal(
            signal_strength=18, location_name="Tunnel"
        )

        snapshot = await self.controller.ingest_message(
            sender="Priya",
            topic="family",
            text="Call me now. Dad is at the clinic and they need the insurance OTP.",
        )

        message = snapshot["messages"][0]
        self.assertEqual(message["priority"], "urgent")
        self.assertEqual(message["status"], "delivered")
        self.assertEqual(snapshot["phone_cards"][0]["kind"], "urgent_delivery")
        self.assertEqual(snapshot["ui"]["stage"], "idle")

    async def test_release_window_opens_when_context_recovers(self) -> None:
        await self.controller.set_demo_signal(
            signal_strength=28, location_name="Tunnel"
        )
        await self.controller.ingest_message(
            sender="Ops Desk",
            topic="customer",
            text="Please review the escalated account issue tonight.",
        )

        snapshot = await self.controller.set_demo_signal(
            signal_strength=88, location_name="Office"
        )

        self.assertTrue(snapshot["context"]["release_window_open"])
        self.assertEqual(snapshot["queue"]["deferred_count"], 1)
        self.assertEqual(snapshot["ui"]["stage"], "brief_ready")
        self.assertEqual(snapshot["ui"]["primary_action"], "generate_digest")

    async def test_digest_release_summarizes_deferred_backlog(self) -> None:
        await self.controller.set_demo_signal(
            signal_strength=22, location_name="Highway"
        )
        await self.controller.ingest_message(
            sender="Rohit",
            topic="meeting",
            text="Please confirm if you can join the 7 PM partner sync.",
        )
        await self.controller.set_demo_signal(
            signal_strength=92, location_name="Office"
        )
        await self.controller.generate_digest()

        snapshot = await self.controller.release_digest()

        self.assertEqual(snapshot["queue"]["deferred_count"], 0)
        self.assertEqual(snapshot["queue"]["summarized_count"], 1)
        self.assertEqual(snapshot["phone_cards"][-1]["kind"], "digest_release")
        self.assertEqual(snapshot["ui"]["stage"], "released")
        self.assertEqual(snapshot["current_digest"]["digest_type"], "fallback")

    async def test_digest_contains_message_summaries(self) -> None:
        await self.controller.set_demo_signal(
            signal_strength=25, location_name="Tunnel"
        )
        await self.controller.ingest_message(
            sender="Daily Brief",
            topic="newsletter",
            text="Top five EV launches this week in one quick read.",
        )
        await self.controller.generate_digest()

        snapshot = await self.controller.snapshot()
        digest = snapshot["current_digest"]

        self.assertGreaterEqual(len(digest["message_summaries"]), 1)
        self.assertTrue(
            all("[" not in item["summary"] for item in digest["message_summaries"])
        )

    async def test_release_digest_without_generated_digest_is_safe(self) -> None:
        snapshot = await self.controller.release_digest()

        self.assertIsNone(snapshot["current_digest"])
        self.assertEqual(snapshot["queue"]["summarized_count"], 0)

    async def test_start_scenario_sets_running_state(self) -> None:
        snapshot = await self.controller.start_scenario()

        self.assertTrue(snapshot["runtime"]["scenario_running"])


if __name__ == "__main__":
    unittest.main()
