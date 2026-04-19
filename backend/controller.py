from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import httpx

from .ai_service import AIService
from .domain import Classification
from .domain import ContextState
from .domain import Digest
from .domain import Event
from .domain import Message
from .domain import PhoneCard
from .domain import ReplySuggestion
from .domain import build_id
from .domain import signal_band
from .domain import to_dict
from .domain import utc_now
from .rule_engine import current_rule_text
from .rule_engine import decide
from .rule_engine import apply_triage_rules
from .rule_engine import compute_triage_score
from .rule_engine import triage_to_decision
from .domain import MessageFeatureVector
from .domain import DecisionLogEntry
from .personalization import preferences as _prefs
from .context_engine import context_engine as _ctx_engine
from .context_engine import VehicleContextState
from .geo_zones import geo_tracker as _geo_tracker
from .geo_zones import ZoneTransitionEvent
from .message_queue import deferred_queue as _deferred_queue
from .message_queue import QueuedMessage
from .scenario import build_default_scenario

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_LOCATION_CACHE: dict[str, str] = {}

DEMO_SIGNAL_OVERRIDES: dict[tuple[float, float], int] = {
    (12.972, 77.595): 25,
    (40.713, -74.006): 55,
    (35.676, 139.65): 85,
}


class SignalBriefController:
    def __init__(self, ai_service: AIService) -> None:
        self.ai_service = ai_service
        self._lock = asyncio.Lock()
        self._messages: list[Message] = []
        self._context = ContextState(
            location_name="",
            latitude=None,
            longitude=None,
            accuracy_meters=None,
            signal_strength=55,
            signal_band="medium",
            release_window_open=False,
            location_status="unavailable",
        )
        self._previous_signal = 55
        self._current_digest: Digest | None = None
        self._current_reply: ReplySuggestion | None = None
        self._phone_cards: list[PhoneCard] = []
        self._recent_events: list[Event] = []
        self._fallback_count = 0
        self._scenario_task: asyncio.Task[None] | None = None
        self._digest_released = False
        self._decision_log: list[DecisionLogEntry] = []
        self._vehicle_state: VehicleContextState | None = None
        # Register zone-transition callback
        _geo_tracker.register_callback(self._on_zone_transition)

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            messages = [to_dict(message) for message in self._messages]
            context = to_dict(self._context)
            digest = to_dict(self._current_digest) if self._current_digest else None
            reply = to_dict(self._current_reply) if self._current_reply else None
            phone_cards = [to_dict(card) for card in self._phone_cards[-6:]]
            recent_events = [to_dict(event) for event in self._recent_events[-12:]]
            queue = self._queue_counts(messages)
            runtime = {
                "scenario_running": self._scenario_task is not None
                and not self._scenario_task.done(),
                "ai_mode": "sarvam" if self.ai_service.sarvam_enabled else "fallback",
                "sarvam_configured": self.ai_service.sarvam_enabled,
                "tts_enabled": self.ai_service.tts_enabled,
                "fallback_count": self._fallback_count,
                "active_rule_text": current_rule_text(self._context),
            }
            ui = self._build_ui(
                context=context,
                messages=messages,
                queue=queue,
                runtime=runtime,
                digest=digest,
            )

        return {
            "context": context,
            "messages": messages,
            "queue": queue,
            "current_digest": digest,
            "current_reply": reply,
            "phone_cards": phone_cards,
            "recent_events": recent_events,
            "runtime": runtime,
            "ui": ui,
        }

    async def start_scenario(self, live_message: dict | None = None) -> dict[str, Any]:
        await self._stop_scenario()
        async with self._lock:
            self._messages = []
            self._current_digest = None
            self._current_reply = None
            self._phone_cards = []
            self._recent_events = []
            self._digest_released = False
        await self._publish("scenario.started", {"message": "Default demo started."})
        task = asyncio.create_task(
            self._run_scenario(live_message=live_message), name="signalbrief-scenario"
        )
        async with self._lock:
            self._scenario_task = task
        return await self.snapshot()

    async def pause_scenario(self) -> dict[str, Any]:
        await self._stop_scenario()
        await self._publish("scenario.paused", {"message": "Scenario paused."})
        return await self.snapshot()

    async def reset(self) -> dict[str, Any]:
        await self._stop_scenario()
        async with self._lock:
            self._messages = []
            self._context = ContextState(
                location_name="",
                latitude=None,
                longitude=None,
                accuracy_meters=None,
                signal_strength=55,
                signal_band="medium",
                release_window_open=False,
                location_status="unavailable",
            )
            self._previous_signal = 55
            self._current_digest = None
            self._current_reply = None
            self._phone_cards = []
            self._recent_events = []
            self._digest_released = False
        await self._publish("scenario.reset", {"message": "State reset."})
        await self._publish("context.updated", {"context": to_dict(self._context)})
        await self._publish("queue.updated", {"message_count": 0})
        return await self.snapshot()

    def _round_cell(self, lat: float, lon: float) -> str:
        rounded_lat = round(lat, 3)
        rounded_lon = round(lon, 3)
        return f"{rounded_lat},{rounded_lon}"

    def _compute_signal(self, cell: str) -> int:
        hash_input = f"signal_{cell}".encode()
        hash_value = int(hashlib.sha256(hash_input).hexdigest()[:8], 16)
        base_signal = 20 + (hash_value % 73)
        return base_signal

    def _time_fluctuation(self) -> int:
        import time

        second_of_minute = int(time.time()) % 60
        return (second_of_minute % 9) - 4

    def _smooth_signal(self, prev: int, target: int) -> int:
        return round(prev * 0.7 + target * 0.3)

    async def _reverse_geocode(self, lat: float, lon: float) -> str | None:
        cell = self._round_cell(lat, lon)
        if cell in _LOCATION_CACHE:
            return _LOCATION_CACHE[cell]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    NOMINATIM_URL,
                    params={
                        "lat": lat,
                        "lon": lon,
                        "format": "json",
                        "addressdetails": 1,
                    },
                )
                if response.status_code == 200:
                    data = response.json()
                    address = data.get("address", {})
                    city = (
                        address.get("city")
                        or address.get("town")
                        or address.get("village")
                    )
                    if city:
                        _LOCATION_CACHE[cell] = city
                        return city
                    display_name = data.get("display_name", "")
                    if display_name:
                        parts = display_name.split(",")
                        _LOCATION_CACHE[cell] = parts[0] if parts else display_name
                        return parts[0] if parts else display_name
        except Exception:
            pass
        return None

    async def set_demo_signal(
        self,
        *,
        signal_strength: int,
        location_name: str,
    ) -> dict[str, Any]:
        async with self._lock:
            previous_release = self._context.release_window_open
            has_backlog = any(msg.status == "deferred" for msg in self._messages)
            signal_strength = max(5, min(95, signal_strength))
            self._previous_signal = signal_strength
            signal_band_val = signal_band(signal_strength)
            context = ContextState(
                location_name=location_name,
                latitude=None,
                longitude=None,
                accuracy_meters=None,
                signal_strength=signal_strength,
                signal_band=signal_band_val,
                release_window_open=signal_band_val == "high" and has_backlog,
                location_status="live",
            )
            self._context = context

        await self._publish("context.updated", {"context": to_dict(context)})
        await self._publish("queue.updated", {"message_count": len(self._messages)})
        if context.release_window_open and not previous_release:
            await self._publish(
                "release_window.opened", {"location": context.location_name}
            )
        return await self.snapshot()

    async def update_location(
        self,
        *,
        latitude: float,
        longitude: float,
        accuracy_meters: float,
    ) -> dict[str, Any]:
        async with self._lock:
            previous_release = self._context.release_window_open
            has_backlog = any(msg.status == "deferred" for msg in self._messages)
            coord_key = (round(latitude, 3), round(longitude, 3))
            if coord_key in DEMO_SIGNAL_OVERRIDES:
                target_signal = DEMO_SIGNAL_OVERRIDES[coord_key]
            else:
                cell = self._round_cell(latitude, longitude)
                target_signal = self._compute_signal(cell)
                target_signal += self._time_fluctuation()
            target_signal = max(5, min(95, target_signal))
            smoothed = self._smooth_signal(self._previous_signal, target_signal)
            self._previous_signal = smoothed
            signal_band_val = signal_band(smoothed)
            location_name = await self._reverse_geocode(latitude, longitude)
            if location_name is None:
                location_name = f"{latitude},{longitude}"
            context = ContextState(
                location_name=location_name,
                latitude=latitude,
                longitude=longitude,
                accuracy_meters=accuracy_meters,
                signal_strength=smoothed,
                signal_band=signal_band_val,
                release_window_open=signal_band_val == "high" and has_backlog,
                location_status="live",
            )
            self._context = context

        await self._publish("context.updated", {"context": to_dict(context)})
        await self._publish("queue.updated", {"message_count": len(self._messages)})
        if context.release_window_open and not previous_release:
            await self._publish(
                "release_window.opened", {"location": context.location_name}
            )
        return await self.snapshot()

    async def set_context(
        self,
        *,
        mode: str,
        signal_strength: int,
        route_segment: str,
    ) -> dict[str, Any]:
        return await self.snapshot()

    async def ingest_message(
        self,
        *,
        sender: str,
        text: str,
        topic: str,
    ) -> dict[str, Any]:
        message = Message(
            id=build_id("msg"),
            sender=sender,
            text=text,
            topic=topic,
            received_at=utc_now(),
            priority="informational",
            needs_reply=False,
            deadline_hint="",
            action_items=[],
            status="received",
            decision_reason="Waiting for classification.",
        )
        async with self._lock:
            self._messages.append(message)
            context = self._context

        await self._publish("message.received", {"message_id": message.id})

        outcome = self.ai_service.classify_message(
            sender=sender,
            text=text,
            topic=topic,
            context=context,
        )
        classification = outcome.value
        assert isinstance(classification, Classification)
        if outcome.used_fallback:
            async with self._lock:
                self._fallback_count += 1
            await self._publish(
                "ai.fallback_used",
                {"operation": "classify_message", "message_id": message.id},
            )

        decision = decide(classification, context)

        # ── Automotive Triage Pipeline ─────────────────────────────────────
        # Build feature vector from ML classification + context + prefs
        signal_quality = context.signal_strength / 100.0
        is_offline = context.signal_strength <= 5 or context.signal_band == "low"
        from datetime import datetime, timezone as _tz
        current_hour = datetime.now(_tz.utc).hour
        is_work_hours = 9 <= current_hour < 18

        # Extract urgency_score from classification reason (set by ONNX path)
        urgency_score = 0.5  # default
        if "urgency_score=" in classification.reason:
            try:
                urgency_score = float(
                    classification.reason.split("urgency_score=")[1].split(",")[0]
                )
            except (ValueError, IndexError):
                pass
        elif classification.priority == "urgent":
            urgency_score = 0.85
        elif classification.priority == "actionable":
            urgency_score = 0.50
        elif classification.priority == "informational":
            urgency_score = 0.20

        sender_tier = _prefs.get_sender_tier(sender)
        user_weight = _prefs.get_sender_weight(sender)
        keyword_count = _prefs.count_urgent_keywords(text)
        words = text.split()
        length_bucket = 0 if len(words) < 10 else (1 if len(words) < 30 else 2)

        features = MessageFeatureVector(
            urgency_score=urgency_score,
            keyword_count=keyword_count,
            message_length_bucket=length_bucket,
            sender_tier=sender_tier,
            user_weight=user_weight,
            sender_avg_urgency=0.5,
            speed_kmh=0.0,
            signal_quality=signal_quality,
            latency_ms=max(50.0, (1.0 - signal_quality) * 800),
            in_coverage_zone=context.signal_band != "low",
            is_driving=False,
            is_work_hours=is_work_hours,
        )
        features.triage_score = compute_triage_score(features)

        triage_result = apply_triage_rules(
            features=features,
            message_id=message.id,
            sender=sender,
            text=text,
            signal_offline=is_offline,
            prefs=_prefs,
        )
        # Override the legacy decision with the triage result
        decision = triage_to_decision(triage_result.action)
        # ── End Triage Pipeline ────────────────────────────────────────────

        async with self._lock:
            stored_message = self._find_message(message.id)
            stored_message.priority = classification.priority
            stored_message.needs_reply = classification.needs_reply
            stored_message.deadline_hint = classification.deadline_hint
            stored_message.action_items = classification.action_items
            stored_message.urgency_score = urgency_score
            stored_message.triage_score = triage_result.triage_score
            stored_message.triage_action = triage_result.action
            if decision.action == "deliver":
                stored_message.status = "delivered"
            elif decision.action == "defer":
                stored_message.status = "deferred"
            else:
                stored_message.status = "ignored"
            stored_message.decision_reason = triage_result.reason
            self._decision_log.append(triage_result.log_entry)
            if len(self._decision_log) > 100:
                self._decision_log = self._decision_log[-100:]
            # Sync into physical deferred queue for zone-flush tracking
            if triage_result.action in ("DEFER_TO_ZONE", "HOLD_FOR_DIGEST"):
                _deferred_queue.enqueue(QueuedMessage(
                    message_id=stored_message.id,
                    sender=stored_message.sender,
                    text=stored_message.text,
                    triage_score=triage_result.triage_score,
                    urgency_score=urgency_score,
                    triage_action=triage_result.action,
                    queued_at=utc_now(),
                ))
            if (
                stored_message.priority == "urgent"
                and stored_message.status == "delivered"
            ):
                self._phone_cards.append(
                    PhoneCard(
                        id=build_id("card"),
                        kind="urgent_delivery",
                        title=f"Urgent: {stored_message.sender}",
                        body=stored_message.text,
                        accent="urgent",
                        created_at=utc_now(),
                    )
                )

        await self._publish(
            "message.classified",
            {
                "message_id": message.id,
                "priority": classification.priority,
                "needs_reply": classification.needs_reply,
            },
        )
        await self._publish(
            "decision.made",
            {
                "message_id": message.id,
                "action": decision.action,
                "reason": decision.reason,
            },
        )
        await self._publish("queue.updated", {"message_count": len(self._messages)})
        return await self.snapshot()

    async def generate_digest(self) -> dict[str, Any]:
        async with self._lock:
            deferred_messages = [
                message for message in self._messages if message.status == "deferred"
            ]
            context = self._context

        if not deferred_messages:
            return await self.snapshot()

        outcome = self.ai_service.generate_digest(deferred_messages, context)
        digest = outcome.value
        assert isinstance(digest, Digest)
        if outcome.used_fallback:
            async with self._lock:
                self._fallback_count += 1
            await self._publish(
                "ai.fallback_used",
                {"operation": "generate_digest", "digest_id": digest.id},
            )

        async with self._lock:
            self._current_digest = digest
            self._digest_released = False

        await self._publish(
            "digest.generated",
            {
                "digest_id": digest.id,
                "highlighted_message_ids": digest.highlighted_message_ids,
            },
        )
        await self._publish("queue.updated", {"message_count": len(self._messages)})
        return await self.snapshot()

    async def release_digest(self) -> dict[str, Any]:
        missing_digest = False
        async with self._lock:
            if self._current_digest is None:
                missing_digest = True
            else:
                digest = self._current_digest
                for message in self._messages:
                    if message.status == "deferred":
                        message.status = "summarized"
                        message.decision_reason = "Released inside the summary digest."
                self._context.release_window_open = False
                self._digest_released = True
                self._phone_cards.append(
                    PhoneCard(
                        id=build_id("card"),
                        kind="digest_release",
                        title="SignalBrief Release",
                        body=digest.summary,
                        accent="digest",
                        created_at=utc_now(),
                    )
                )

        if missing_digest:
            return await self.snapshot()

        await self._publish("digest.released", {"digest_id": digest.id})
        await self._publish("context.updated", {"context": to_dict(self._context)})
        await self._publish("queue.updated", {"message_count": len(self._messages)})
        return await self.snapshot()

    async def generate_reply(self, message_id: str) -> dict[str, Any]:
        async with self._lock:
            message = self._find_message(message_id)
            digest = self._current_digest

        outcome = self.ai_service.generate_reply(message=message, digest=digest)
        reply = outcome.value
        assert isinstance(reply, ReplySuggestion)
        if outcome.used_fallback:
            async with self._lock:
                self._fallback_count += 1
            await self._publish(
                "ai.fallback_used",
                {"operation": "generate_reply", "message_id": message_id},
            )

        async with self._lock:
            self._current_reply = reply

        await self._publish("reply.generated", {"message_id": message_id})
        return await self.snapshot()

    async def _run_scenario(self, live_message: dict | None = None) -> None:
        completed = False
        try:
            steps = list(build_default_scenario())
            if live_message:
                from .scenario import ScenarioStep
                steps.append(
                    ScenarioStep(
                        delay_seconds=0.08,
                        kind="message",
                        payload=live_message,
                    )
                )
            for step in steps:
                await asyncio.sleep(step.delay_seconds)
                if step.kind == "message":
                    await self.ingest_message(**step.payload)
            completed = True
        except asyncio.CancelledError:
            raise
        finally:
            async with self._lock:
                self._scenario_task = None
            if completed:
                await self._publish(
                    "scenario.completed",
                    {"message": "Scenario complete."},
                )

    async def _stop_scenario(self) -> None:
        async with self._lock:
            task = self._scenario_task
            self._scenario_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        event = Event(
            id=build_id("event"),
            type=event_type,
            timestamp=utc_now(),
            payload=payload,
        )
        message = json.dumps(to_dict(event))
        async with self._lock:
            self._recent_events.append(event)
            self._recent_events = self._recent_events[-40:]

    def _find_message(self, message_id: str) -> Message:
        for message in self._messages:
            if message.id == message_id:
                return message
        raise AssertionError(f"Unknown message: {message_id}")

    def _queue_counts(self, messages: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "deferred_count": sum(
                message["status"] == "deferred" for message in messages
            ),
            "delivered_count": sum(
                message["status"] == "delivered" for message in messages
            ),
            "summarized_count": sum(
                message["status"] == "summarized" for message in messages
            ),
            "ignored_count": sum(
                message["status"] == "ignored" for message in messages
            ),
            "urgent_count": sum(
                message["priority"] == "urgent" for message in messages
            ),
            "actionable_count": sum(
                message["priority"] == "actionable" for message in messages
            ),
            "informational_count": sum(
                message["priority"] == "informational" for message in messages
            ),
        }

    def _build_ui(
        self,
        *,
        context: dict[str, Any],
        messages: list[dict[str, Any]],
        queue: dict[str, int],
        runtime: dict[str, Any],
        digest: dict[str, Any] | None,
    ) -> dict[str, Any]:
        deferred_count = queue["deferred_count"]
        urgent_override = self._latest_urgent_override(messages)
        scenario_running = bool(runtime["scenario_running"])

        stage = "idle"
        if digest and self._digest_released:
            stage = "released"
        if deferred_count > 0:
            stage = "holding"
        if deferred_count > 0 and urgent_override is not None:
            stage = "urgent_bypass"
        if context["release_window_open"] and deferred_count > 0:
            stage = "brief_ready"
        if digest and not self._digest_released:
            stage = "brief_generated"

        if stage == "brief_generated":
            return {
                "stage": stage,
                "headline": "The brief is ready.",
                "supporting_text": (
                    "SignalBrief has collapsed the held backlog into one clean summary."
                ),
                "primary_action": "release_digest",
                "primary_action_label": "Release brief",
                "primary_action_reason": (
                    "Show how the user receives a concise, prioritized update."
                ),
                "secondary_hint": (
                    f"{digest['urgent_count']} urgent and {digest['actionable_count']} "
                    "actionable items were preserved."
                ),
                "show_phone_preview": True,
            }

        if stage == "brief_ready":
            return {
                "stage": stage,
                "headline": (
                    "The context is safe again. SignalBrief can now prepare the brief."
                ),
                "supporting_text": (
                    "Generate the brief to turn the held backlog into one guided release."
                ),
                "primary_action": "generate_digest",
                "primary_action_label": "Generate brief",
                "primary_action_reason": (
                    "This is where the backlog becomes a summary instead of a burst."
                ),
                "secondary_hint": (
                    f"{deferred_count} held messages are waiting to be summarized."
                ),
                "show_phone_preview": False,
            }

        if stage == "urgent_bypass":
            assert urgent_override is not None
            return {
                "stage": stage,
                "headline": (
                    "SignalBrief is holding the backlog, but one urgent alert broke through."
                ),
                "supporting_text": (
                    "Critical items bypass deferral so attention is protected without missing emergencies."
                ),
                "primary_action": "none",
                "primary_action_label": "",
                "primary_action_reason": (
                    "Wait for a better context, then generate the brief."
                ),
                "secondary_hint": (
                    f"Urgent override from {urgent_override['sender']} was delivered immediately."
                ),
                "show_phone_preview": False,
            }

        if stage == "holding":
            return {
                "stage": stage,
                "headline": (
                    "SignalBrief is holding non-urgent notifications while attention is limited."
                ),
                "supporting_text": (
                    "The backlog is being kept quiet now so it can be delivered cleanly later."
                ),
                "primary_action": "none",
                "primary_action_label": "",
                "primary_action_reason": (
                    "No action is needed yet. The release window has not opened."
                ),
                "secondary_hint": f"{deferred_count} messages are currently being held back.",
                "show_phone_preview": False,
            }

        if stage == "released":
            return {
                "stage": stage,
                "headline": (
                    "SignalBrief released a clean brief instead of replaying every notification."
                ),
                "supporting_text": (
                    "The user sees the important items first, with less interruption and less noise."
                ),
                "primary_action": "reset",
                "primary_action_label": "Reset demo",
                "primary_action_reason": "Run the story again from the start.",
                "secondary_hint": (
                    f"{queue['summarized_count']} messages were delivered through the brief."
                ),
                "show_phone_preview": True,
            }

        if scenario_running:
            return {
                "stage": stage,
                "headline": "The demo is running. SignalBrief is waiting for the first meaningful context change.",
                "supporting_text": (
                    "Incoming notifications will be triaged as soon as they arrive."
                ),
                "primary_action": "none",
                "primary_action_label": "",
                "primary_action_reason": "Let the scenario play for a moment.",
                "secondary_hint": "",
                "show_phone_preview": False,
            }

        return {
            "stage": stage,
            "headline": (
                "Start the demo to see SignalBrief hold low-value notifications during a busy moment."
            ),
            "supporting_text": (
                "The story is simple: hold the noise now, then release one clear brief later."
            ),
            "primary_action": "start_demo",
            "primary_action_label": "Start demo",
            "primary_action_reason": (
                "This begins the scripted drive scenario and incoming message stream."
            ),
            "secondary_hint": "",
            "show_phone_preview": False,
        }

    def _latest_urgent_override(
        self,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        urgent_messages = [
            message
            for message in messages
            if message["priority"] == "urgent" and message["status"] == "delivered"
        ]
        if not urgent_messages:
            return None
        return urgent_messages[-1]

    def get_decision_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the last `limit` decision log entries as plain dicts."""
        tail = self._decision_log[-limit:]
        return [to_dict(entry) for entry in reversed(tail)]  # newest first

    def get_preferences(self) -> dict[str, Any]:
        """Return current user preferences."""
        from .personalization import preferences as _p
        return _p.to_dict()

    def update_preferences(self, partial: dict[str, Any]) -> dict[str, Any]:
        """Merge partial preference update and return updated state."""
        from .personalization import preferences as _p
        _p.update(partial)
        return _p.to_dict()

    # ---- Automotive Simulation Methods ----------------------------------------

    async def simulate_step(self) -> dict[str, Any]:
        """
        Advance the Bangalore route by one waypoint.
        - Updates VehicleContextState
        - Updates the legacy ContextState for backward compat
        - Triggers geo-zone transition callbacks (which may flush queue)
        - Returns full snapshot
        """
        # Advance context engine
        vehicle_state = _ctx_engine.step()
        async with self._lock:
            self._vehicle_state = vehicle_state
            # Sync legacy ContextState so existing UI/endpoints still work
            signal_int = int(vehicle_state.signal_quality * 100)
            self._context = ContextState(
                location_name=vehicle_state.location_label,
                latitude=vehicle_state.latitude,
                longitude=vehicle_state.longitude,
                accuracy_meters=50.0,
                signal_strength=signal_int,
                signal_band=vehicle_state.signal_band,
                release_window_open=(
                    vehicle_state.zone_colour in ("GREEN", "YELLOW")
                    and _deferred_queue.count > 0
                ),
                location_status="live",
            )

        # Fire zone-transition callbacks (synchronous, outside lock)
        _geo_tracker.update(vehicle_state.signal_quality, vehicle_state.location_label)

        await self._publish("context.updated", {
            "location": vehicle_state.location_label,
            "zone": vehicle_state.zone_colour,
            "signal_quality": vehicle_state.signal_quality,
            "network_type": vehicle_state.network_type,
            "speed_kmh": vehicle_state.speed_kmh,
            "waypoint_index": vehicle_state.waypoint_index,
        })

        return await self.snapshot()

    def _on_zone_transition(self, event: ZoneTransitionEvent) -> None:
        """
        Called synchronously by GeoZoneTracker when zone changes.
        Handles queue flush on recovery.
        (Note: runs outside the asyncio lock -- do not await here)
        """
        if event.should_flush_queue and not _deferred_queue.is_empty():
            if event.to_zone in ("GREEN", "YELLOW"):
                result = _deferred_queue.flush(trigger_reason=event.flush_reason)
            else:
                result = _deferred_queue.flush_critical_only(
                    trigger_reason=event.flush_reason
                )

            # Mark flushed messages as delivered in _messages list
            immediate_ids = {m.message_id for m in result.immediate}
            for msg in self._messages:
                if msg.id in immediate_ids and msg.status == "deferred":
                    msg.status = "delivered"
                    msg.decision_reason = (
                        f"Flushed on zone recovery: {event.from_zone} -> {event.to_zone}"
                    )

        if event.should_hold_messages:
            # Future messages will go to queue -- no action needed here
            pass

    def get_vehicle_context(self) -> dict[str, Any]:
        """Return current VehicleContextState as dict (or defaults if not started)."""
        if self._vehicle_state is None:
            state = _ctx_engine.current()
        else:
            state = self._vehicle_state
        return {
            "waypoint_index": state.waypoint_index,
            "latitude": state.latitude,
            "longitude": state.longitude,
            "location_label": state.location_label,
            "speed_kmh": state.speed_kmh,
            "is_driving": state.is_driving,
            "signal_quality": state.signal_quality,
            "network_type": state.network_type,
            "latency_ms": state.latency_ms,
            "signal_band": state.signal_band,
            "zone_colour": state.zone_colour,
            "zone_colour_hex": {
                "GREEN": "#22c55e",
                "YELLOW": "#eab308",
                "RED": "#ef4444",
                "DEAD": "#6b7280",
            }.get(state.zone_colour, "#6b7280"),
            "in_coverage_zone": state.in_coverage_zone,
            "hour_of_day": state.hour_of_day,
            "is_work_hours": state.is_work_hours,
            "route_progress_pct": state.route_progress_pct,
            "at_destination": state.at_destination,
            "current_geo_zone": _geo_tracker.current_zone,
            "deferred_queue_count": _deferred_queue.count,
        }

    def get_route_summary(self) -> list[dict[str, Any]]:
        """Return all waypoints for frontend GeoRouteMap rendering."""
        return _ctx_engine.route_summary()

    def get_queue_state(self) -> dict[str, Any]:
        """Return deferred queue state + stats."""
        return {
            "stats": _deferred_queue.stats(),
            "items": _deferred_queue.to_dict_list(),
            "zone_history": _geo_tracker.zone_history(limit=10),
        }

    def flush_queue_manually(self) -> dict[str, Any]:
        """Manually trigger a queue flush (for testing or manual override)."""
        result = _deferred_queue.flush(trigger_reason="manual_flush")
        immediate_ids = {m.message_id for m in result.immediate}
        for msg in self._messages:
            if msg.id in immediate_ids and msg.status == "deferred":
                msg.status = "delivered"
                msg.decision_reason = "Manually flushed by user."
        return {
            "flushed": result.total_flushed,
            "immediate_count": len(result.immediate),
            "digest_count": len(result.digest_batch),
            "immediate_items": [
                {"id": m.message_id, "sender": m.sender, "score": m.triage_score}
                for m in result.immediate
            ],
        }

