"""
SignalBrief -- Context Engine
==============================
Protocol Section 3 -- Dynamic signal simulation along a Bangalore commute route.

Simulates:
  - Vehicle speed (varies by route segment)
  - Signal quality (degrades in tunnels/underpasses, recovers in open roads)
  - Network type (4G / 3G / 2G / OFFLINE)
  - Estimated latency

Route: Koramangala -> Silk Board -> Electronic City (Bangalore, India)
       18 waypoints, ~14 km, typical peak-hour commute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import math


# ---- Route Waypoints --------------------------------------------------------
# Each waypoint: (lat, lon, label, base_signal [0-1], speed_kmh, notes)

@dataclass(frozen=True)
class Waypoint:
    lat: float
    lon: float
    label: str
    base_signal: float      # 0.0=no coverage  1.0=full coverage
    speed_kmh: float        # typical speed at this point
    notes: str = ""


BANGALORE_ROUTE: list[Waypoint] = [
    Waypoint(12.9352, 77.6245, "Koramangala 4th Block",    0.90, 25, "residential, good 4G"),
    Waypoint(12.9347, 77.6270, "Koramangala 6th Block",    0.85, 20, "market area, moderate"),
    Waypoint(12.9302, 77.6260, "Dairy Circle",             0.75, 15, "heavy traffic junction"),
    Waypoint(12.9260, 77.6220, "BTM Layout Flyover",       0.80, 40, "elevated road, decent signal"),
    Waypoint(12.9190, 77.6210, "Silk Board Junction",      0.30, 5,  "DEAD ZONE - highest congestion in asia"),
    Waypoint(12.9150, 77.6250, "Silk Board Exit",          0.45, 20, "signal recovering"),
    Waypoint(12.9100, 77.6270, "HSR Layout Sector 2",      0.72, 35, "residential recovery"),
    Waypoint(12.9050, 77.6290, "HSR Flyover",              0.80, 55, "elevated, good signal"),
    Waypoint(12.8980, 77.6310, "Bommanahalli Junction",    0.55, 20, "underpass ahead"),
    Waypoint(12.8920, 77.6330, "Bommanahalli Underpass",   0.15, 30, "tunnel -- near dead zone"),
    Waypoint(12.8860, 77.6350, "Electronic City Flyover",  0.85, 60, "elevated expressway"),
    Waypoint(12.8800, 77.6370, "Electronic City Phase 1",  0.92, 45, "tech park, excellent 4G"),
    Waypoint(12.8750, 77.6390, "Infosys Gate",             0.95, 20, "strong indoor signal bleed"),
    Waypoint(12.8700, 77.6410, "Electronic City Phase 2",  0.88, 30, "good coverage"),
    Waypoint(12.8650, 77.6430, "Helix Bridge Area",        0.70, 50, "slight dip near water"),
    Waypoint(12.8600, 77.6450, "Singasandra Junction",     0.60, 25, "moderate, evening busy"),
    Waypoint(12.8560, 77.6470, "JP Nagar Entry",           0.82, 40, "recovering"),
    Waypoint(12.8520, 77.6490, "JP Nagar 5th Phase",       0.90, 30, "destination area"),
]

# Zone colour thresholds (signal_quality)
ZONE_GREEN  = 0.70   # deliver immediately
ZONE_YELLOW = 0.40   # deliver actionable only
ZONE_RED    = 0.15   # critical only
ZONE_DEAD   = 0.05   # nothing -- queue everything

NetworkType = str   # "4G" | "3G" | "2G" | "OFFLINE"


# ---- Vehicle Context State --------------------------------------------------

@dataclass
class VehicleContextState:
    """
    Full automotive context snapshot -- assembles from ContextEngine.step().
    This is the vehicle-grade extension of the legacy ContextState.
    """
    # Position
    waypoint_index: int
    latitude: float
    longitude: float
    location_label: str

    # Motion
    speed_kmh: float
    is_driving: bool

    # Signal
    signal_quality: float       # [0, 1]
    network_type: NetworkType
    latency_ms: float
    signal_band: str            # "low" | "medium" | "high"

    # Zone
    zone_colour: str            # "GREEN" | "YELLOW" | "RED" | "DEAD"
    in_coverage_zone: bool

    # Time
    hour_of_day: int
    is_work_hours: bool

    # Progress
    route_progress_pct: float   # 0.0 -> 100.0
    at_destination: bool


# ---- Helpers ----------------------------------------------------------------

def _network_type(signal: float) -> NetworkType:
    if signal >= 0.70:
        return "4G"
    if signal >= 0.40:
        return "3G"
    if signal >= 0.10:
        return "2G"
    return "OFFLINE"


def _signal_band(signal: float) -> str:
    if signal < 0.40:
        return "low"
    if signal < 0.70:
        return "medium"
    return "high"


def _zone_colour(signal: float) -> str:
    if signal >= ZONE_GREEN:
        return "GREEN"
    if signal >= ZONE_YELLOW:
        return "YELLOW"
    if signal >= ZONE_RED:
        return "RED"
    return "DEAD"


def _latency(signal: float) -> float:
    """Estimate network latency from signal quality."""
    if signal <= 0.05:
        return 9999.0   # offline
    # Exponential decay: 4G=50ms, 3G=200ms, 2G=700ms
    return round(max(40.0, 800.0 * math.exp(-3.5 * signal)), 1)


def _add_noise(base: float, noise_factor: float = 0.08) -> float:
    """Add small variability to simulate real-world signal fluctuation."""
    import random
    delta = (random.random() - 0.5) * 2 * noise_factor
    return max(0.0, min(1.0, base + delta))


def _hour_of_day() -> int:
    from datetime import datetime, timezone, timedelta
    india_tz = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(india_tz).hour


# ---- Context Engine ---------------------------------------------------------

class ContextEngine:
    """
    Steps through BANGALORE_ROUTE one waypoint at a time.
    Each call to step() advances position and recomputes all vehicle signals.

    Usage
    -----
        engine = ContextEngine()
        state = engine.current()      # start state
        state = engine.step()         # advance one waypoint
        state = engine.reset()        # back to start
    """

    def __init__(self) -> None:
        self._index: int = 0
        self._route = BANGALORE_ROUTE
        self._prev_signal: float = self._route[0].base_signal
        self._loop: bool = True         # wrap around when reaching end

    def _build_state(self) -> VehicleContextState:
        idx = self._index
        wp = self._route[idx]
        hour = _hour_of_day()

        # Smooth signal: 70% previous, 30% new target + noise
        raw_signal = _add_noise(wp.base_signal)
        smoothed = 0.70 * self._prev_signal + 0.30 * raw_signal
        smoothed = max(0.0, min(1.0, smoothed))
        self._prev_signal = smoothed

        # Peak-hour penalty: 8-10am and 5-8pm reduce signal by 15%
        if 8 <= hour < 10 or 17 <= hour < 20:
            smoothed = max(0.0, smoothed * 0.85)

        zone = _zone_colour(smoothed)
        n_type = _network_type(smoothed)
        lat_ms = _latency(smoothed)
        s_band = _signal_band(smoothed)
        is_driving = wp.speed_kmh > 5.0
        is_work_hours = 9 <= hour < 18
        progress = (idx / max(1, len(self._route) - 1)) * 100.0

        return VehicleContextState(
            waypoint_index=idx,
            latitude=wp.lat,
            longitude=wp.lon,
            location_label=wp.label,
            speed_kmh=wp.speed_kmh,
            is_driving=is_driving,
            signal_quality=round(smoothed, 3),
            network_type=n_type,
            latency_ms=lat_ms,
            signal_band=s_band,
            zone_colour=zone,
            in_coverage_zone=zone not in ("DEAD",),
            hour_of_day=hour,
            is_work_hours=is_work_hours,
            route_progress_pct=round(progress, 1),
            at_destination=idx == len(self._route) - 1,
        )

    def current(self) -> VehicleContextState:
        """Return current state without advancing."""
        return self._build_state()

    def step(self) -> VehicleContextState:
        """Advance one waypoint and return new state."""
        if self._index < len(self._route) - 1:
            self._index += 1
        elif self._loop:
            self._index = 0
            self._prev_signal = self._route[0].base_signal
        return self._build_state()

    def reset(self) -> VehicleContextState:
        """Jump back to route start."""
        self._index = 0
        self._prev_signal = self._route[0].base_signal
        return self._build_state()

    def jump_to(self, index: int) -> VehicleContextState:
        """Jump to specific waypoint index."""
        self._index = max(0, min(index, len(self._route) - 1))
        return self._build_state()

    @property
    def waypoint_count(self) -> int:
        return len(self._route)

    def route_summary(self) -> list[dict]:
        """Return all waypoints for frontend map rendering."""
        return [
            {
                "index": i,
                "lat": wp.lat,
                "lon": wp.lon,
                "label": wp.label,
                "base_signal": wp.base_signal,
                "speed_kmh": wp.speed_kmh,
                "zone_colour": _zone_colour(wp.base_signal),
                "network_type": _network_type(wp.base_signal),
                "notes": wp.notes,
            }
            for i, wp in enumerate(self._route)
        ]


# Module singleton
context_engine = ContextEngine()
