from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic import Field

from .ai_service import AIService
from .controller import SignalBriefController


class MessageRequest(BaseModel):
    sender: str
    text: str
    topic: str


class LiveMessageRequest(BaseModel):
    sender: str = ""
    text: str = ""
    topic: str = "live"


class StartScenarioRequest(BaseModel):
    live_message: LiveMessageRequest | None = None


class ContextRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_meters: float = Field(gt=0)
    captured_at: str


class ReplyRequest(BaseModel):
    message_id: str


def load_runtime_settings() -> dict[str, str]:
    settings = dict(os.environ)
    secret_path = Path(
        settings.get(
            "SIGNALBRIEF_SECRET_FILE",
            str(Path(__file__).resolve().parent.parent / ".env"),
        )
    )
    if not secret_path.exists():
        return settings

    for line in secret_path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        settings.setdefault(key, value)
    return settings


settings = load_runtime_settings()
ai_service = AIService(
    mode=settings.get("AI_PROVIDER_MODE", "fallback"),
    api_key=settings.get("SARVAM_API_KEY"),
    model=settings.get("SARVAM_MODEL", "sarvam-105b"),
    groq_api_key=settings.get("GROQ_API_KEY"),
    groq_model=settings.get("GROQ_MODEL", "openai/gpt-oss-120b"),
)
controller = SignalBriefController(ai_service)

app = FastAPI(title="SignalBrief API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/state")
async def get_state() -> dict:
    return await controller.snapshot()


@app.post("/api/scenario/start")
async def start_scenario(request: StartScenarioRequest | None = None) -> dict:
    live_msg = None
    if request and request.live_message and request.live_message.text.strip():
        lm = request.live_message
        live_msg = {
            "sender": lm.sender.strip() or "You",
            "text": lm.text.strip(),
            "topic": lm.topic or "live",
        }
    return await controller.start_scenario(live_message=live_msg)


@app.post("/api/scenario/pause")
async def pause_scenario() -> dict:
    return await controller.pause_scenario()


@app.post("/api/scenario/reset")
async def reset_scenario() -> dict:
    return await controller.reset()


@app.post("/api/messages")
async def create_message(request: MessageRequest) -> dict:
    return await controller.ingest_message(
        sender=request.sender,
        text=request.text,
        topic=request.topic,
    )


@app.post("/api/context")
async def update_context(request: ContextRequest) -> dict:
    return await controller.update_location(
        latitude=request.latitude,
        longitude=request.longitude,
        accuracy_meters=request.accuracy_meters,
    )


class DemoSignalRequest(BaseModel):
    signal_strength: int = Field(ge=5, le=95)
    location_name: str


@app.post("/api/demo/signal")
async def set_demo_signal(request: DemoSignalRequest) -> dict:
    return await controller.set_demo_signal(
        signal_strength=request.signal_strength,
        location_name=request.location_name,
    )


@app.post("/api/digest/generate")
async def generate_digest() -> dict:
    return await controller.generate_digest()


@app.post("/api/digest/release")
async def release_digest() -> dict:
    return await controller.release_digest()


@app.post("/api/voice/brief")
async def voice_brief() -> JSONResponse:
    # Pull urgent messages directly — voice brief is independent of the digest
    urgent_messages = [
        msg for msg in controller._messages if msg.priority == "urgent"
    ]
    if not urgent_messages and controller._current_digest is None:
        return JSONResponse(
            status_code=400,
            content={"error": "No messages available. Run the demo first."},
        )
    try:
        audio_b64 = ai_service.generate_voice_brief(urgent_messages)
        return JSONResponse(content={"audio": audio_b64, "format": "wav"})
    except RuntimeError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})


@app.post("/api/reply/generate")
async def generate_reply(request: ReplyRequest) -> dict:
    return await controller.generate_reply(request.message_id)


# ── Automotive Triage Endpoints ─────────────────────────────────────────────

@app.get("/api/decisions/log")
async def get_decision_log(limit: int = 50) -> dict:
    """
    Returns the last `limit` triage decisions with scores, actions, and reasons.
    Used by the DecisionLog panel in the frontend.
    """
    return {"log": controller.get_decision_log(limit=limit)}


@app.get("/api/preferences")
async def get_preferences() -> dict:
    """
    Return current user preferences (whitelist, sender weights, DND windows).
    Includes live status: dnd_active_now, current_hour_utc.
    """
    return controller.get_preferences()


@app.post("/api/preferences")
async def update_preferences(body: dict) -> dict:
    """
    Save user preferences. Full update — send the complete state you want.
    Accepted keys:
      sender_weights           dict[str, float]  -- merged with existing
      sender_weights_replace   dict[str, float]  -- full replacement
      whitelist                list[str]          -- full replacement
      whitelist_add            list[str]
      whitelist_remove         list[str]
      dnd_windows              list[[start_hour, end_hour]]
      defer_threshold          float
      deliver_threshold        float
      driving_speed_threshold_kmh  float
    Returns the full updated prefs dict + dnd_active_now.
    """
    return controller.update_preferences(body)


@app.post("/api/preferences/reset")
async def reset_preferences() -> dict:
    """Reset all preferences to protocol defaults."""
    from .personalization import preferences as _p
    _p.reset_to_defaults()
    return _p.to_dict()


@app.post("/api/preferences/retriage")
async def retriage_queue() -> dict:
    """
    Re-evaluate all deferred/held messages against the CURRENT preferences.
    Call this immediately after saving preferences to apply them to the queue.
    - Newly whitelisted senders → promoted to delivered
    - Lower deliver_threshold → some held messages now score above the gate
    """
    return controller.retriage_deferred_queue()


@app.get("/api/preferences/retriage/preview")
async def preview_retriage() -> dict:
    """
    Dry-run: returns how many held messages WOULD be promoted
    if current prefs were applied, without changing any state.
    """
    return controller.preview_retriage_impact()


@app.get("/api/preferences/history")
async def get_preference_history() -> dict:
    """
    Return the preference change changelog (newest first).
    Each entry has: timestamp, summary, changed_fields.
    """
    from .personalization import preferences as _p
    return {"history": _p.get_history(limit=50)}


# ---- Simulation & Route Endpoints -------------------------------------------

@app.post("/api/simulate/step")
async def simulate_step() -> dict:
    """
    Advance the Bangalore drive simulation one waypoint.
    Updates signal quality, zone, speed, and triggers queue flushes.
    """
    return await controller.simulate_step()


@app.get("/api/vehicle/context")
async def get_vehicle_context() -> dict:
    """Full VehicleContextState: speed, zone, signal, network type, latency."""
    return controller.get_vehicle_context()


@app.get("/api/route")
async def get_route() -> dict:
    """All 18 Bangalore route waypoints for GeoRouteMap rendering."""
    return {"waypoints": controller.get_route_summary()}


@app.get("/api/queue")
async def get_queue() -> dict:
    """Deferred message queue state: stats, items, and zone history."""
    return controller.get_queue_state()


@app.post("/api/queue/flush")
async def flush_queue() -> dict:
    """Manually flush the deferred queue (override for testing/demo)."""
    return controller.flush_queue_manually()
