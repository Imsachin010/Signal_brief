import type { VehicleContextState, Snapshot } from "./types";

interface Props {
  vehicle: VehicleContextState | null;
  snapshot: Snapshot;
  onStep: () => void;
  onGenerate: () => void;
  onFlush: () => void;
  busy: boolean;
  stepping: boolean;
  dndActive?: boolean;
  deferThreshold?: number;
  deliverThreshold?: number;
}

const ZONE_COLORS: Record<string, string> = {
  GREEN: "#22c55e",
  YELLOW: "#eab308",
  RED: "#ef4444",
  DEAD: "#6b7280",
};

const ZONE_LABELS: Record<string, string> = {
  GREEN: "FULL COVERAGE",
  YELLOW: "PARTIAL",
  RED: "CRITICAL ONLY",
  DEAD: "NO SIGNAL",
};

function ScoreBar({ value, max = 1, color }: { value: number; max?: number; color: string }) {
  const pct = Math.min(100, (value / max) * 100);
  return (
    <div className="score-bar-track">
      <div className="score-bar-fill" style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

function SignalBars({ quality }: { quality: number }) {
  const filled = quality >= 0.75 ? 4 : quality >= 0.50 ? 3 : quality >= 0.25 ? 2 : quality > 0.05 ? 1 : 0;
  const color = quality >= 0.70 ? "#22c55e" : quality >= 0.40 ? "#eab308" : "#ef4444";
  return (
    <div className="signal-bars">
      {[1, 2, 3, 4].map((n) => (
        <div
          key={n}
          className="signal-bar"
          style={{
            height: `${n * 6 + 4}px`,
            background: n <= filled ? color : "rgba(255,255,255,0.12)",
          }}
        />
      ))}
    </div>
  );
}

export default function HMIDisplay({ vehicle, snapshot, onStep, onGenerate, onFlush, busy, stepping, dndActive, deferThreshold = 0.45, deliverThreshold = 0.65 }: Props) {
  const zone = vehicle?.zone_colour ?? "GREEN";
  const zoneColor = ZONE_COLORS[zone] ?? "#6b7280";
  const signalQ = vehicle?.signal_quality ?? (snapshot.context.signal_strength / 100);
  const speed = vehicle?.speed_kmh ?? 0;
  const network = vehicle?.network_type ?? "4G";
  const latency = vehicle?.latency_ms ?? 50;
  const progress = vehicle?.route_progress_pct ?? 0;
  const queueCount = vehicle?.deferred_queue_count ?? snapshot.queue.deferred_count;

  const urgentCount = snapshot.queue.urgent_count;
  const locationLabel = vehicle?.location_label ?? snapshot.context.location_name ?? "Koramangala";

  // Derived — which messages are being held right now?
  const holdReason = dndActive
    ? "DND window active — all non-whitelisted messages held"
    : zone === "DEAD"
    ? "No signal — messages queued until coverage returns"
    : zone === "RED"
    ? "Critical zone — only urgent messages delivered"
    : null;

  return (
    <div className="hmi-root">
      {/* ── Zone Status Bar ── */}
      <div className="zone-bar" style={{ background: `${zoneColor}22`, borderColor: zoneColor }}>
        <div className="zone-dot" style={{ background: zoneColor }} />
        <span className="zone-label" style={{ color: zoneColor }}>{ZONE_LABELS[zone]}</span>
        <span className="zone-location">{locationLabel}</span>
        {dndActive && <span className="zone-dnd-chip">🌙 DND</span>}
        <div className="zone-network-badge">{network}</div>
      </div>

      {/* ── Hold Reason Banner ── */}
      {holdReason && (
        <div className="hmi-hold-banner">
          <span className="hmi-hold-icon">⏸</span>
          {holdReason}
        </div>
      )}

      {/* ── Main Cockpit Grid ── */}
      <div className="cockpit-grid">

        {/* Speed Gauge */}
        <div className="cockpit-card speed-card">
          <div className="cockpit-card-label">SPEED</div>
          <div className="speedometer">
            <svg viewBox="0 0 120 80" width="120" height="80">
              <path d="M10 70 A 50 50 0 0 1 110 70" fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="8" strokeLinecap="round" />
              <path
                d="M10 70 A 50 50 0 0 1 110 70"
                fill="none"
                stroke={speed > 80 ? "#ef4444" : speed > 40 ? "#eab308" : "#22c55e"}
                strokeWidth="8"
                strokeLinecap="round"
                strokeDasharray={`${(speed / 120) * 157} 157`}
              />
              <text x="60" y="62" textAnchor="middle" fill="white" fontSize="22" fontWeight="bold">{Math.round(speed)}</text>
              <text x="60" y="75" textAnchor="middle" fill="rgba(255,255,255,0.5)" fontSize="9">km/h</text>
            </svg>
          </div>
          <div className="cockpit-sub">{vehicle?.is_driving ? "DRIVING" : "PARKED"}</div>
        </div>

        {/* Signal Panel */}
        <div className="cockpit-card signal-card">
          <div className="cockpit-card-label">SIGNAL</div>
          <div className="signal-big">
            <SignalBars quality={signalQ} />
            <span className="signal-pct">{Math.round(signalQ * 100)}%</span>
          </div>
          <ScoreBar value={signalQ} color={zoneColor} />
          <div className="cockpit-sub latency-row">
            <span>Latency</span>
            <span style={{ color: latency > 500 ? "#ef4444" : latency > 200 ? "#eab308" : "#22c55e" }}>
              {latency > 999 ? "OFFLINE" : `${Math.round(latency)}ms`}
            </span>
          </div>
        </div>

        {/* Queue Counter */}
        <div className="cockpit-card queue-card">
          <div className="cockpit-card-label">QUEUE</div>
          <div className="queue-count" style={{ color: queueCount > 5 ? "#eab308" : queueCount > 0 ? "#a78bfa" : "#22c55e" }}>
            {queueCount}
          </div>
          <div className="cockpit-sub">messages held</div>
          {urgentCount > 0 && (
            <div className="urgent-badge-row">
              <span className="urgent-dot" />
              {urgentCount} urgent
            </div>
          )}
        </div>

        {/* Route Progress */}
        <div className="cockpit-card route-card">
          <div className="cockpit-card-label">ROUTE PROGRESS</div>
          <div className="progress-ring-wrap">
            <svg viewBox="0 0 80 80" width="80" height="80">
              <circle cx="40" cy="40" r="32" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="7" />
              <circle
                cx="40" cy="40" r="32"
                fill="none"
                stroke="#6366f1"
                strokeWidth="7"
                strokeLinecap="round"
                strokeDasharray={`${(progress / 100) * 201} 201`}
                transform="rotate(-90 40 40)"
              />
              <text x="40" y="45" textAnchor="middle" fill="white" fontSize="13" fontWeight="bold">
                {Math.round(progress)}%
              </text>
            </svg>
          </div>
          {vehicle?.at_destination && <div className="cockpit-sub" style={{ color: "#22c55e" }}>ARRIVED</div>}
        </div>
      </div>

      {/* ── Triage Summary Strip ── */}
      <div className="triage-strip">
        <div className="triage-stat">
          <span className="triage-stat-val" style={{ color: "#22c55e" }}>{snapshot.queue.delivered_count}</span>
          <span className="triage-stat-label">Delivered</span>
        </div>
        <div className="triage-stat">
          <span className="triage-stat-val" style={{ color: "#a78bfa" }}>{queueCount}</span>
          <span className="triage-stat-label">Queued</span>
        </div>
        <div className="triage-stat">
          <span className="triage-stat-val" style={{ color: "#ef4444" }}>{urgentCount}</span>
          <span className="triage-stat-label">Urgent</span>
        </div>
        <div className="triage-stat">
          <span className="triage-stat-val" style={{ color: "#6b7280" }}>{snapshot.queue.ignored_count}</span>
          <span className="triage-stat-label">Ignored</span>
        </div>
      </div>

      {/* ── Live Threshold Bar ── */}
      <div className="threshold-bar-row">
        <span className="threshold-bar-label">TRIAGE GATES</span>
        <div className="threshold-bar-track">
          <div className="threshold-bar-hold" style={{ width: `${deferThreshold * 100}%` }} />
          <div className="threshold-bar-defer"
            style={{ width: `${(deliverThreshold - deferThreshold) * 100}%`, left: `${deferThreshold * 100}%` }} />
          <div className="threshold-bar-deliver"
            style={{ width: `${(1 - deliverThreshold) * 100}%`, left: `${deliverThreshold * 100}%` }} />
        </div>
        <div className="threshold-bar-labels">
          <span className="tbhl-hold">Hold &lt;{deferThreshold.toFixed(2)}</span>
          <span className="tbhl-defer">Digest</span>
          <span className="tbhl-deliver">&gt;{deliverThreshold.toFixed(2)} Deliver</span>
        </div>
      </div>

      {/* ── Action Bar ── */}
      <div className="hmi-action-bar">
        <button
          className="hmi-btn hmi-btn-primary"
          onClick={onStep}
          disabled={busy || stepping}
          id="btn-simulate-step"
        >
          {stepping ? "Advancing..." : "Advance Route"}
        </button>
        <button
          className="hmi-btn hmi-btn-secondary"
          onClick={onGenerate}
          disabled={busy || snapshot.queue.deferred_count === 0}
          id="btn-generate-digest"
        >
          Generate AI Brief
        </button>
        <button
          className="hmi-btn hmi-btn-ghost"
          onClick={onFlush}
          disabled={busy || queueCount === 0}
          id="btn-flush-queue"
        >
          Flush Queue
        </button>
      </div>
    </div>
  );
}
