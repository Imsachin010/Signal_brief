from __future__ import annotations

import json
import logging
import random
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# On-Device Urgency Classifier  (TF-IDF + Logistic Regression)
# Loads automatically when models/urgency_classifier.joblib exists.
# Train it with:  python scripts/train_urgency_model.py   (takes < 5 seconds)
# Falls back to keyword rules if the model file is missing.
# ──────────────────────────────────────────────────────────────────────────────

class SklearnUrgencyClassifier:
    """
    Lightweight urgency classifier backed by a joblib-serialised
    TF-IDF + LogisticRegression sklearn pipeline.

    Outputs
    -------
    label         : "low" | "medium" | "high"
    urgency_score : float [0, 1]  — weighted class probability
    """

    _MODEL_PATH = Path("models") / "urgency_classifier.joblib"
    _ID2LABEL   = {0: "low", 1: "medium", 2: "high"}

    def __init__(self) -> None:
        self._pipeline = None
        self._load()

    def _load(self) -> None:
        if not self._MODEL_PATH.exists():
            logger.info(
                "[SklearnUrgencyClassifier] Model not found — using keyword fallback. "
                "Run: python scripts/train_urgency_model.py"
            )
            return
        try:
            import joblib  # type: ignore

            self._pipeline = joblib.load(self._MODEL_PATH)
            logger.info(f"[SklearnUrgencyClassifier] Loaded: {self._MODEL_PATH}")
        except Exception as exc:
            logger.warning(f"[SklearnUrgencyClassifier] Load failed: {exc}")
            self._pipeline = None

    @property
    def available(self) -> bool:
        return self._pipeline is not None

    def predict(self, text: str) -> tuple[str, float]:
        """
        Returns (label, urgency_score).
        urgency_score is a weighted sum of class probabilities:
          score = P(low)*0.05 + P(medium)*0.45 + P(high)*0.95
        """
        if not self.available:
            raise RuntimeError("Sklearn model not loaded")

        import numpy as np  # type: ignore

        probs = self._pipeline.predict_proba([text])[0]   # shape (3,) — low/med/high
        label = self._ID2LABEL[int(np.argmax(probs))]
        urgency_score = float(probs[0] * 0.05 + probs[1] * 0.45 + probs[2] * 0.95)
        return label, urgency_score


# Singleton — loaded once at startup
_ONNX_CLASSIFIER = SklearnUrgencyClassifier()

from groq import Groq

from .domain import Classification
from .domain import ContextState
from .domain import Digest
from .domain import Message
from .domain import Priority
from .domain import ReplySuggestion
from .domain import build_id
from .domain import utc_now


PRIORITIES: tuple[Priority, ...] = ("urgent", "actionable", "informational", "ignore")
URGENT_TERMS = (
    "urgent",
    "asap",
    "immediately",
    "emergency",
    "call me now",
    "critical",
    "right now",
    "otp",
    "password",
    "code",
    "clinic",
    "hospital",
    "payment failed",
)
ACTIONABLE_TERMS = (
    "please",
    "can you",
    "need you",
    "review",
    "approve",
    "reply",
    "confirm",
    "check",
    "send",
    "join",
    "meeting",
    "today",
    "tomorrow",
    "before",
    "eod",
)
IGNORE_TERMS = (
    "sale",
    "discount",
    "offer",
    "newsletter",
    "promo",
    "reward",
    "coupon",
    "subscribe",
    "marketing",
)


@dataclass(slots=True)
class AIOutcome:
    value: object
    used_fallback: bool
    provider: str


class AIService:
    def __init__(
        self,
        mode: str,
        api_key: str | None,
        *,
        model: str = "sarvam-105b",
        timeout_seconds: float = 8.0,
        groq_api_key: str | None = None,
        groq_model: str = "openai/gpt-oss-120b",
        groq_client_factory: Callable[[], Groq] | None = None,
    ) -> None:
        self.mode = mode
        self.api_key = api_key or ""
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.groq_api_key = groq_api_key or ""
        self.groq_model = groq_model
        self._groq_client_factory = groq_client_factory or (
            lambda: Groq(api_key=self.groq_api_key)
        )

    @property
    def sarvam_enabled(self) -> bool:
        return self.mode == "sarvam" and bool(self.api_key)

    @property
    def tts_enabled(self) -> bool:
        """TTS only needs the Sarvam API key, regardless of the AI mode."""
        return bool(self.api_key)

    @property
    def groq_enabled(self) -> bool:
        return bool(self.groq_api_key)

    def classify_message(
        self,
        *,
        sender: str,
        text: str,
        topic: str,
        context: ContextState,
    ) -> AIOutcome:
        fallback = self._fallback_classification(sender=sender, text=text)

        # ── On-device ONNX model (highest priority when available) ────────────
        if _ONNX_CLASSIFIER.available:
            try:
                onnx_label, urgency_score = _ONNX_CLASSIFIER.predict(text)
                # Map ONNX label → domain Priority
                _label_to_priority = {
                    "high": "urgent",
                    "medium": "actionable",
                    "low": "informational",
                }
                priority = _label_to_priority.get(onnx_label, "informational")
                needs_reply = priority in ("urgent", "actionable") or "?" in text
                action_items = self._extract_action_items(
                    sender=sender, text=text, priority=priority  # type: ignore[arg-type]
                )
                deadline_hint = self._extract_deadline_hint(text)
                classification = Classification(
                    priority=priority,  # type: ignore[arg-type]
                    needs_reply=needs_reply,
                    reason=(
                        f"On-device DistilBERT: urgency_score={urgency_score:.3f}, "
                        f"class={onnx_label}"
                    ),
                    action_items=action_items,
                    deadline_hint=deadline_hint,
                )
                return AIOutcome(classification, False, "onnx_on_device")
            except Exception as exc:
                logger.warning(f"[ONNXUrgencyClassifier] inference failed: {exc}")

        if not self.sarvam_enabled:
            return AIOutcome(fallback, True, "fallback")

        try:
            payload = self._chat_json_sarvam(
                system_prompt=(
                    "You classify notifications by priority. "
                    "Use these priority levels: high (urgent/critical), medium (actionable), low (informational), ignore (promo). "
                    "Return JSON only with keys priority, needs_reply, reason, action_items, deadline_hint. "
                    "Return priority as one of: high, medium, low, ignore."
                ),
                user_prompt=(
                    f"Sender: {sender}\n"
                    f"Topic: {topic}\n"
                    f"Current signal: {context.signal_band}\n"
                    f"Message: {text}"
                ),
                max_tokens=220,
            )
            raw_priority = str(payload.get("priority", "low"))
            priority_map = {
                "high": "urgent",
                "medium": "actionable",
                "low": "informational",
                "ignore": "ignore",
            }
            priority = priority_map.get(raw_priority, raw_priority)
            if priority not in PRIORITIES:
                priority = "informational"
            action_items = payload.get("action_items") or []
            deadline_hint = payload.get("deadline_hint") or ""
            classification = Classification(
                priority=priority,
                needs_reply=bool(payload.get("needs_reply")),
                reason=str(payload.get("reason") or fallback.reason),
                action_items=[str(item) for item in action_items][:4],
                deadline_hint=str(deadline_hint),
            )
            return AIOutcome(classification, False, "sarvam")
        except Exception:
            return AIOutcome(fallback, True, "fallback")

    def generate_digest(
        self,
        messages: list[Message],
        context: ContextState,
    ) -> AIOutcome:
        fallback = self._fallback_digest(messages)
        if self.groq_enabled:
            try:
                return AIOutcome(self._groq_digest(messages, context), False, "groq")
            except Exception:
                return AIOutcome(fallback, True, "fallback")

        if not self.sarvam_enabled:
            return AIOutcome(fallback, True, "fallback")

        try:
            return AIOutcome(self._sarvam_digest(messages, context), False, "sarvam")
        except Exception:
            return AIOutcome(fallback, True, "fallback")

    def generate_reply(
        self,
        *,
        message: Message,
        digest: Digest | None,
    ) -> AIOutcome:
        fallback = self._fallback_reply(message)

        # Try Groq first (richer, more human-like)
        if self.groq_enabled:
            try:
                return AIOutcome(self._groq_reply(message, digest), False, "groq")
            except Exception:
                pass

        if not self.sarvam_enabled:
            return AIOutcome(fallback, True, "fallback")

        try:
            digest_context = digest.summary if digest else "No digest generated yet."
            payload = self._chat_json_sarvam(
                system_prompt=(
                    "You write short, natural human reply messages. "
                    "Sound like a real person texting or emailing back — conversational, warm, and direct. "
                    "Never use robotic phrases. Vary your phrasing each time. "
                    "Return JSON only with keys text and tone. "
                    "text must be 1-2 sentences max. tone must be one word: calm, professional, or urgent."
                ),
                user_prompt=(
                    f"Sender: {message.sender}\n"
                    f"Priority: {message.priority}\n"
                    f"Original message: {message.text}\n"
                    f"Context: {digest_context}"
                ),
                max_tokens=120,
            )
            reply = ReplySuggestion(
                message_id=message.id,
                text=str(payload["text"]),
                tone=str(payload.get("tone") or "calm"),
            )
            return AIOutcome(reply, False, "sarvam")
        except Exception:
            return AIOutcome(fallback, True, "fallback")

    def _groq_reply(self, message: Message, digest: Digest | None) -> ReplySuggestion:
        client = self._groq_client_factory()
        digest_context = digest.summary if digest else ""
        response = client.chat.completions.create(
            model=self.groq_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write short, natural reply messages on behalf of a busy person. "
                        "Sound like a real human texting or emailing — warm, direct, and varied. "
                        "Never use stiff or robotic phrases like 'I acknowledge your message'. "
                        "Each reply should feel freshly written, not templated. "
                        "Keep it to 1-2 sentences. "
                        "Return JSON with exactly two keys: "
                        '"text" (the reply string) and "tone" (one word: calm, professional, or urgent).'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"From: {message.sender}\n"
                        f"Their message: {message.text}\n"
                        f"Priority level: {message.priority}\n"
                        + (f"Context: {digest_context}\n" if digest_context else "")
                        + "Write a brief, human reply I can send back."
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.85,
            max_completion_tokens=120,
        )
        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)
        return ReplySuggestion(
            message_id=message.id,
            text=str(payload.get("text") or "").strip(),
            tone=str(payload.get("tone") or "calm").lower(),
        )

    def _chat_json_sarvam(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> dict[str, Any]:
        request_body = json.dumps(
            {
                "model": self.model,
                "temperature": 0.1,
                "seed": 7,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
        ).encode()
        request = urllib.request.Request(
            "https://api.sarvam.ai/v1/chat/completions",
            data=request_body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "api-subscription-key": self.api_key,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                raw_response = response.read().decode()
        except urllib.error.URLError as exc:
            raise RuntimeError("Sarvam request failed") from exc

        response_payload = json.loads(raw_response)
        content = response_payload["choices"][0]["message"]["content"]
        assert content is not None
        return self._extract_json(content)

    def generate_voice_brief(self, urgent_messages: list[Message]) -> str:
        """Generate a spoken driving briefing for urgent messages using Sarvam bulbulv3 TTS.

        Only high-priority (urgent) messages are voiced.
        Uses Groq to paraphrase naturally if available, otherwise falls back to
        a clean programmatic script.
        Returns a base64-encoded WAV audio string.
        Raises RuntimeError if the Sarvam API key is not configured or the request fails.
        """
        if not self.tts_enabled:
            raise RuntimeError("Sarvam API key is not configured.")

        # Build the script — Groq with programmatic fallback on any failure or empty output
        script = ""
        if self.groq_enabled:
            try:
                script = self._groq_voice_script(urgent_messages)
            except Exception:
                script = ""

        if not script or not script.strip():
            # Groq unavailable, failed, or returned empty — use reliable fallback
            script = self._build_voice_script(urgent_messages)

        request_body = json.dumps(
            {
                "text": script,
                "target_language_code": "en-IN",
                "model": "bulbul:v3",
                "speaker": "pooja",
                "pace": 0.95,
                "sample_rate": 22050,
                "temperature": 0.65,
            }
        ).encode()
        request = urllib.request.Request(
            "https://api.sarvam.ai/text-to-speech",
            data=request_body,
            method="POST",
            headers={
                "api-subscription-key": self.api_key,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20.0) as response:
                raw = response.read().decode()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise RuntimeError(f"Sarvam TTS error {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Sarvam TTS request failed: {exc.reason}") from exc

        payload = json.loads(raw)
        audios = payload.get("audios") or []
        if not audios:
            raise RuntimeError(f"Sarvam TTS returned no audio. Response: {raw[:200]}")
        return str(audios[0])

    def _clean_sender_name(self, sender: str) -> str:
        """Strip role suffixes and return just the first name or short identifier.

        Examples:
            'Nisha - Product'  -> 'Nisha'
            'Anika - Manager'  -> 'Anika'
            'Ops Desk'         -> 'Ops Desk'
            'Daily Brief'      -> 'Daily Brief'
            'Parents'          -> 'your parents'
        """
        if " - " in sender:
            sender = sender.split(" - ")[0].strip()
        # Personalise common generic senders
        lower = sender.lower()
        if lower in ("parents", "family"):
            return "your parents"
        if lower in ("mom", "mum", "mother"):
            return "your mum"
        if lower in ("dad", "father"):
            return "your dad"
        return sender

    def _groq_voice_script(self, urgent_messages: list[Message]) -> str:
        """Use Groq to produce a natural, human-sounding driving voice brief.

        Only urgent messages are included. The output is a complete spoken
        paragraph ready for TTS — no JSON, no markdown.
        """
        if not urgent_messages:
            return "You have no urgent messages from your drive. Stay safe."

        lines = []
        for msg in urgent_messages:
            name = self._clean_sender_name(msg.sender)
            lines.append(f"- {name}: {msg.text}")
        messages_block = "\n".join(lines)

        client = self._groq_client_factory()
        response = client.chat.completions.create(
            model=self.groq_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write short spoken driving briefings for a car assistant. "
                        "Rules:\n"
                        "1. Only include the urgent messages provided — nothing else.\n"
                        "2. For each message say '[Name] said [gist of what they want].' "
                        "Do NOT quote the message verbatim. Capture the intent in plain language.\n"
                        "3. Start with a brief opening like "
                        "'You have N urgent message(s) from your drive.' \n"
                        "4. End with 'Check your SignalBrief for the full details.' \n"
                        "5. Output plain spoken text only — no bullets, no markdown, no JSON. "
                        "Keep it under 60 words total."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Urgent messages:\n{messages_block}",
                },
            ],
            # reasoning_effort=low keeps internal reasoning tokens minimal so the
            # output budget is not consumed before the actual text is produced.
            reasoning_effort="low",
            temperature=0.55,
            max_completion_tokens=600,
        )
        return (response.choices[0].message.content or "").strip()

    def _build_voice_script(self, urgent_messages: list[Message]) -> str:
        """Fallback: build a spoken briefing programmatically from urgent messages."""
        if not urgent_messages:
            return "You have no urgent messages from your drive. Stay safe."

        count = len(urgent_messages)
        msg_word = "urgent message" if count == 1 else "urgent messages"
        parts = [f"You have {count} {msg_word} from your drive."]

        for msg in urgent_messages:
            name = self._clean_sender_name(msg.sender)
            # Trim the raw text to a clean gist — first sentence only, max 120 chars
            gist = msg.text.strip()
            if "." in gist:
                gist = gist.split(".")[0].strip()
            if len(gist) > 120:
                gist = gist[:117].rstrip() + "..."
            parts.append(f"{name} said: {gist}.")

        parts.append("Check your SignalBrief for the full details.")
        return " ".join(parts)

    def _groq_digest(self, messages: list[Message], context: ContextState) -> Digest:
        client = self._groq_client_factory()
        prompt = self._render_digest_prompt(messages, context)
        response = client.chat.completions.create(
            model=self.groq_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You generate a concise notification briefing. "
                        "Write a short header plus one concise summary line per message. "
                        "Never copy the raw message text verbatim. "
                        "Use high, medium, low priority language only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "signalbrief_digest",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string"},
                            "action_items": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "highlighted_message_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "message_summaries": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "sender": {"type": "string"},
                                        "summary": {"type": "string"},
                                    },
                                    "required": ["id", "sender", "summary"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": [
                            "summary",
                            "action_items",
                            "highlighted_message_ids",
                            "message_summaries",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            temperature=0.2,
            max_completion_tokens=1024,
            top_p=1,
            reasoning_effort="medium",
        )
        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)
        return self._digest_from_payload(payload, messages, digest_type="groq")

    def _sarvam_digest(self, messages: list[Message], context: ContextState) -> Digest:
        prompt = self._render_digest_prompt(messages, context)
        payload = self._chat_json_sarvam(
            system_prompt=(
                "You generate a notification briefing. For each pending message, provide a one-line summary. "
                "Return JSON with keys: summary (overall header), action_items (list), message_summaries (list of {id, sender, summary}). "
                "The message_summaries must include every message ID provided. Keep each message summary to 1-2 sentences."
            ),
            user_prompt=prompt,
            max_tokens=500,
        )
        return self._digest_from_payload(payload, messages, digest_type="sarvam")

    def _render_digest_prompt(
        self, messages: list[Message], context: ContextState
    ) -> str:
        priority_map = {
            "urgent": "high",
            "actionable": "medium",
            "informational": "low",
            "ignore": "ignore",
        }
        rendered_messages = "\n\n".join(
            f"ID: {message.id}\nPriority: {priority_map.get(message.priority, message.priority)}\nFrom: {message.sender}\nTopic: {message.topic}\nMessage: {message.text}"
            for message in messages
        )
        return (
            f"Location: {context.location_name}\n"
            f"Signal: {context.signal_band}\n"
            f"Pending messages to summarize:\n{rendered_messages}"
        )

    def _digest_from_payload(
        self, payload: dict[str, Any], messages: list[Message], *, digest_type: str
    ) -> Digest:
        raw_summaries = payload.get("message_summaries") or []
        message_summaries = [
            {
                "id": str(item.get("id", "")),
                "sender": str(item.get("sender", "")),
                "summary": str(item.get("summary", "")),
            }
            for item in raw_summaries
        ]
        digest = Digest(
            id=build_id("digest"),
            created_at=utc_now(),
            summary=str(payload.get("summary") or "Summary generated."),
            digest_type=digest_type,
            urgent_count=sum(message.priority == "urgent" for message in messages),
            actionable_count=sum(
                message.priority == "actionable" for message in messages
            ),
            informational_count=sum(
                message.priority == "informational" for message in messages
            ),
            ignored_count=sum(message.priority == "ignore" for message in messages),
            action_items=[str(item) for item in payload.get("action_items") or []][:5],
            highlighted_message_ids=[
                str(item) for item in payload.get("highlighted_message_ids") or []
            ][:5],
            message_summaries=message_summaries,
        )
        if not digest.summary or digest.summary.startswith("["):
            digest.summary = self._fallback_digest(messages).summary
        if not digest.message_summaries:
            digest.message_summaries = self._fallback_digest(messages).message_summaries
        return digest

    def _extract_json(self, content: str) -> dict[str, Any]:
        stripped = content.strip()
        stripped = (
            stripped.removeprefix("```json").removeprefix("```").removesuffix("```")
        )
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        assert match is not None
        return json.loads(match.group(0))

    def _fallback_classification(self, *, sender: str, text: str) -> Classification:
        lowered = text.lower()

        priority: Priority
        if any(term in lowered for term in IGNORE_TERMS):
            priority = "ignore"
        elif any(term in lowered for term in URGENT_TERMS):
            priority = "urgent"
        elif any(term in lowered for term in ACTIONABLE_TERMS) or "?" in text:
            priority = "actionable"
        else:
            priority = "informational"

        needs_reply = priority in ("urgent", "actionable") or "?" in text
        action_items = self._extract_action_items(
            sender=sender, text=text, priority=priority
        )
        deadline_hint = self._extract_deadline_hint(text)

        reason = {
            "urgent": "Detected urgency keywords or time-sensitive escalation.",
            "actionable": "Detected a request, question, or follow-up task.",
            "informational": "Detected a neutral update with no immediate action.",
            "ignore": "Detected promotional or low-value content.",
        }[priority]
        return Classification(
            priority=priority,
            needs_reply=needs_reply,
            reason=reason,
            action_items=action_items,
            deadline_hint=deadline_hint,
        )

    def _fallback_digest(self, messages: list[Message]) -> Digest:
        high_count = sum(message.priority == "urgent" for message in messages)
        medium_count = sum(message.priority == "actionable" for message in messages)
        low_count = sum(message.priority == "informational" for message in messages)
        ignored_count = sum(message.priority == "ignore" for message in messages)

        action_items: list[str] = []
        highlighted_message_ids: list[str] = []
        message_summaries: list[dict[str, str]] = []

        for message in messages:
            if (
                message.priority in ("urgent", "actionable")
                and len(highlighted_message_ids) < 5
            ):
                highlighted_message_ids.append(message.id)

            message_summaries.append(
                {
                    "id": message.id,
                    "sender": message.sender,
                    "summary": self._summarize_message(message),
                }
            )

            for item in message.action_items:
                if item not in action_items:
                    action_items.append(item)
                if len(action_items) == 5:
                    break
            if len(action_items) == 5:
                break

        parts = []
        if high_count > 0:
            parts.append(f"{high_count} high priority")
        if medium_count > 0:
            parts.append(f"{medium_count} medium priority")
        if low_count > 0:
            parts.append(f"{low_count} low priority")

        if parts:
            header = f"{' and '.join(parts)} messages were held back. Review the high priority items first."
        else:
            header = "No messages were held back."
        return Digest(
            id=build_id("digest"),
            created_at=utc_now(),
            summary=header,
            digest_type="fallback",
            urgent_count=high_count,
            actionable_count=medium_count,
            informational_count=low_count,
            ignored_count=ignored_count,
            action_items=action_items,
            highlighted_message_ids=highlighted_message_ids,
            message_summaries=message_summaries,
        )

    def _summarize_message(self, message: Message) -> str:
        priority_label = {
            "urgent": "high",
            "actionable": "medium",
            "informational": "low",
            "ignore": "ignore",
        }.get(message.priority, "low")
        text = message.text.strip().rstrip(".")
        if len(text) > 88:
            text = text[:85].rstrip() + "..."
        return f"{priority_label}: {text}"

    def _fallback_reply(self, message: Message) -> ReplySuggestion:
        sender_name = message.sender.split()[0] if message.sender else "there"

        if message.priority == "urgent":
            options = [
                f"On it — will sort this out right now, {sender_name}.",
                f"Just saw this, handling it immediately.",
                f"Got it — dropping everything and dealing with this now.",
                f"On it right away, give me a few minutes.",
                f"Seen. I'm on this immediately, {sender_name}.",
            ]
            tone = "urgent"
        elif message.needs_reply:
            options = [
                f"Hey {sender_name}, just catching up — will get back to you shortly.",
                "Sorry for the delay, I was in a low-signal window — on it now.",
                f"Got your message, {sender_name}. Will follow up very soon.",
                "Just out of a busy stretch — I'll take care of this shortly.",
                f"Seen, {sender_name}. Give me a bit and I'll get back to you.",
            ]
            tone = "calm"
        else:
            options = [
                "Thanks for the update!",
                f"Got it, {sender_name} — appreciate the heads up.",
                "Noted, thanks!",
                "Cheers for letting me know.",
                "Got this, thank you!",
            ]
            tone = "calm"

        return ReplySuggestion(
            message_id=message.id,
            text=random.choice(options),
            tone=tone,
        )

    def _extract_action_items(
        self,
        *,
        sender: str,
        text: str,
        priority: Priority,
    ) -> list[str]:
        lowered = text.lower()
        items: list[str] = []
        if "review" in lowered:
            items.append(f"Review the request from {sender}.")
        if "approve" in lowered:
            items.append(f"Approve the item requested by {sender}.")
        if "call" in lowered:
            items.append(f"Call {sender}.")
        if "reply" in lowered or "confirm" in lowered or "?" in text:
            items.append(f"Reply to {sender}.")
        if "meeting" in lowered or "join" in lowered:
            items.append(f"Check the meeting request from {sender}.")
        if priority == "urgent" and not items:
            items.append(f"Prioritize a response to {sender}.")
        return items[:4]

    def _extract_deadline_hint(self, text: str) -> str:
        lowered = text.lower()
        for term in ("today", "tomorrow", "tonight", "eod", "6 pm", "5 pm"):
            if term in lowered:
                return term
        return ""
