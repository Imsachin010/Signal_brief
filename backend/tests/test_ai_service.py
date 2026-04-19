from __future__ import annotations

import json
import unittest

from backend.ai_service import AIService
from backend.domain import ContextState
from backend.domain import Message


class _FakeGroqResponse:
    def __init__(self, content: str) -> None:
        self.choices = [
            type(
                "Choice", (), {"message": type("Message", (), {"content": content})()}
            )()
        ]


class _FakeGroqCompletions:
    def __init__(self, content: str) -> None:
        self._content = content

    def create(self, **kwargs):
        return _FakeGroqResponse(self._content)


class _FakeGroqClient:
    def __init__(self, content: str) -> None:
        self.chat = type("Chat", (), {"completions": _FakeGroqCompletions(content)})()


class AIServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = AIService(mode="fallback", api_key=None)

    def test_groq_digest_generates_per_message_summaries(self) -> None:
        messages = [
            Message(
                id="msg_1",
                sender="Nisha - Product",
                text="Can you review the dealership pricing note before 6 PM?",
                topic="pricing",
                received_at="2026-04-18T00:00:00+00:00",
                priority="actionable",
                needs_reply=True,
                deadline_hint="6 PM",
                action_items=["Review the request from Nisha - Product."],
                status="deferred",
                decision_reason="Deferred by signal.",
            ),
            Message(
                id="msg_2",
                sender="Daily Brief",
                text="Top five EV launches this week in one quick read.",
                topic="newsletter",
                received_at="2026-04-18T00:00:01+00:00",
                priority="informational",
                needs_reply=False,
                deadline_hint="",
                action_items=[],
                status="deferred",
                decision_reason="Deferred by signal.",
            ),
        ]
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

        groq_payload = {
            "summary": "Two pending updates need attention.",
            "action_items": ["Review the pricing note", "Skim the newsletter later"],
            "highlighted_message_ids": ["msg_1"],
            "message_summaries": [
                {
                    "id": "msg_1",
                    "sender": "Nisha - Product",
                    "summary": "Medium priority request about pricing review before 6 PM.",
                },
                {
                    "id": "msg_2",
                    "sender": "Daily Brief",
                    "summary": "Low priority newsletter that can wait until later.",
                },
            ],
        }
        service = AIService(
            mode="fallback",
            api_key=None,
            groq_api_key="test-key",
            groq_client_factory=lambda: _FakeGroqClient(json.dumps(groq_payload)),
        )

        outcome = service.generate_digest(messages, context)
        digest = outcome.value

        self.assertFalse(outcome.used_fallback)
        self.assertEqual(outcome.provider, "groq")
        self.assertEqual(digest.digest_type, "groq")
        self.assertEqual(len(digest.message_summaries), 2)
        self.assertTrue(all(item["summary"] for item in digest.message_summaries))

    def test_fallback_digest_mentions_high_medium_low_language(self) -> None:
        messages = [
            Message(
                id="msg_1",
                sender="Nisha - Product",
                text="Can you review the dealership pricing note before 6 PM?",
                topic="pricing",
                received_at="2026-04-18T00:00:00+00:00",
                priority="actionable",
                needs_reply=True,
                deadline_hint="6 PM",
                action_items=["Review the request from Nisha - Product."],
                status="deferred",
                decision_reason="Deferred by signal.",
            )
        ]
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

        digest = self.service._fallback_digest(messages)

        self.assertIn("medium priority", digest.summary)
        self.assertEqual(digest.message_summaries[0]["sender"], "Nisha - Product")
        self.assertEqual(
            digest.message_summaries[0]["summary"],
            "medium: Can you review the dealership pricing note before 6 PM?",
        )

    def test_digest_payload_normalizes_heading_text(self) -> None:
        messages = [
            Message(
                id="msg_1",
                sender="Nisha - Product",
                text="Can you review the dealership pricing note before 6 PM?",
                topic="pricing",
                received_at="2026-04-18T00:00:00+00:00",
                priority="actionable",
                needs_reply=True,
                deadline_hint="6 PM",
                action_items=["Review the request from Nisha - Product."],
                status="deferred",
                decision_reason="Deferred by signal.",
            )
        ]
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

        service = AIService(
            mode="fallback",
            api_key=None,
            groq_api_key="test-key",
            groq_client_factory=lambda: _FakeGroqClient(
                json.dumps(
                    {
                        "summary": "[medium] Can you review the pricing note?",
                        "action_items": [],
                        "highlighted_message_ids": [],
                        "message_summaries": [],
                    }
                )
            ),
        )

        digest = service.generate_digest(messages, context).value

        self.assertNotIn("[medium]", digest.summary)
        self.assertEqual(
            digest.summary,
            "1 medium priority messages were held back. Review the high priority items first.",
        )


if __name__ == "__main__":
    unittest.main()
