import { useEffect, useState, useCallback, useRef } from "react";
import type {
  Message, ReplySuggestion, Snapshot,
  VehicleContextState, DecisionLogEntry, Waypoint, QueueItem, QueueStats,
} from "./types";
import HMIDisplay from "./HMIDisplay";
import GeoRouteMap from "./GeoRouteMap";
import DecisionLog from "./DecisionLog";
import PreferencesPanel from "./PreferencesPanel";

type LivePrefs = {
  defer_threshold: number;
  deliver_threshold: number;
  whitelist: string[];
  dnd_active_now: boolean;
  driving_speed_threshold_kmh: number;
};

const API = import.meta.env.VITE_API_ROOT ?? "http://127.0.0.1:8000";

// ── API helpers ──────────────────────────────────────────────────────────────
async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) throw new Error(`GET ${path} failed`);
  return r.json() as Promise<T>;
}
async function postJson<T = Snapshot>(path: string, body?: object): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`POST ${path} failed`);
  return r.json() as Promise<T>;
}

function displayStatus(s: Message["status"]): "pending" | "delivered" | "summarized" | "ignored" {
  if (["deferred", "received", "classified"].includes(s)) return "pending";
  if (s === "ignored") return "ignored";
  if (s === "summarized") return "summarized";
  return "delivered";
}
function signalTone(n: number) { return n < 40 ? "low" : n < 70 ? "medium" : "high"; }
function fmtTime(ts: string) {
  return new Date(ts).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
function priorityLabel(p: string) {
  return p === "urgent" ? "High" : p === "actionable" ? "Medium" : p === "informational" ? "Low" : "Ignore";
}

type Tab = "cockpit" | "route" | "log" | "messages" | "preferences";

// ── App ──────────────────────────────────────────────────────────────────────
export default function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [vehicle, setVehicle] = useState<VehicleContextState | null>(null);
  const [waypoints, setWaypoints] = useState<Waypoint[]>([]);
  const [decisionLog, setDecisionLog] = useState<DecisionLogEntry[]>([]);
  const [queueStats, setQueueStats] = useState<QueueStats | null>(null);
  const [queueItems, setQueueItems] = useState<QueueItem[]>([]);
  const [livePrefs, setLivePrefs] = useState<LivePrefs>({
    defer_threshold: 0.45,
    deliver_threshold: 0.65,
    whitelist: [],
    dnd_active_now: false,
    driving_speed_threshold_kmh: 15,
  });

  const [tab, setTab] = useState<Tab>("cockpit");
  const [busy, setBusy] = useState(false);
  const [stepping, setStepping] = useState(false);
  const [generatingSummary, setGeneratingSummary] = useState(false);
  const [logLoading, setLogLoading] = useState(false);
  const [error, setError] = useState("");

  const [liveSender, setLiveSender] = useState("");
  const [liveText, setLiveText] = useState("");
  const [suggestions, setSuggestions] = useState<Map<string, ReplySuggestion | "loading">>(new Map());
  const [sentReplies, setSentReplies] = useState<Map<string, string>>(new Map());
  const [voiceState, setVoiceState] = useState<"idle"|"loading"|"playing"|"error">("idle");
  const [autoDrive, setAutoDrive] = useState(false);
  const autoDriveRef = useRef(false);
  const stepCountRef = useRef(0);

  const refreshPrefs = useCallback(async () => {
    const p = await getJson<LivePrefs & Record<string, unknown>>("/api/preferences");
    setLivePrefs({
      defer_threshold: (p.defer_threshold as number) ?? 0.45,
      deliver_threshold: (p.deliver_threshold as number) ?? 0.65,
      whitelist: (p.whitelist as string[]) ?? [],
      dnd_active_now: (p.dnd_active_now as boolean) ?? false,
      driving_speed_threshold_kmh: (p.driving_speed_threshold_kmh as number) ?? 15,
    });
  }, []);

  const refreshAll = useCallback(async () => {
    const [snap, vc, route] = await Promise.all([
      getJson<Snapshot>("/api/state"),
      getJson<VehicleContextState>("/api/vehicle/context"),
      getJson<{ waypoints: Waypoint[] }>("/api/route"),
    ]);
    setSnapshot(snap);
    setVehicle(vc);
    setWaypoints(route.waypoints);
  }, []);

  const refreshLog = useCallback(async () => {
    setLogLoading(true);
    try {
      const { log } = await getJson<{ log: DecisionLogEntry[] }>("/api/decisions/log?limit=80");
      setDecisionLog(log);
    } finally {
      setLogLoading(false);
    }
  }, []);

  const refreshQueue = useCallback(async () => {
    const q = await getJson<{ stats: QueueStats; items: QueueItem[] }>("/api/queue");
    setQueueStats(q.stats);
    setQueueItems(q.items);
  }, []);

  // Initial load
  useEffect(() => { void refreshAll(); void refreshPrefs(); }, [refreshAll, refreshPrefs]);
  // Auto-refresh state every 3s
  useEffect(() => {
    const id = setInterval(() => { void getJson<Snapshot>("/api/state").then(setSnapshot); }, 3000);
    return () => clearInterval(id);
  }, []);

  // Load log when switching to log tab
  useEffect(() => {
    if (tab === "log") void refreshLog();
  }, [tab, refreshLog]);

  // Auto-drive loop
  useEffect(() => {
    autoDriveRef.current = autoDrive;
  }, [autoDrive]);

  useEffect(() => {
    if (!autoDrive) return;
    const id = setInterval(async () => {
      if (!autoDriveRef.current) return;
      try {
        const [snap, vc] = await Promise.all([
          postJson("/api/simulate/step"),
          getJson<VehicleContextState>("/api/vehicle/context"),
        ]);
        setSnapshot(snap);
        setVehicle(vc);
        stepCountRef.current += 1;
        // Refresh log every 4 steps
        if (stepCountRef.current % 4 === 0) void refreshLog();
      } catch { /* silently ignore step errors in auto mode */ }
    }, 2500);
    return () => clearInterval(id);
  }, [autoDrive, refreshLog]);

  async function simulateStep() {
    setStepping(true);
    try {
      setError("");
      const [snap, vc] = await Promise.all([
        postJson("/api/simulate/step"),
        getJson<VehicleContextState>("/api/vehicle/context"),
      ]);
      setSnapshot(snap);
      setVehicle(vc);
    } catch { setError("Step failed"); }
    finally { setStepping(false); }
  }

  async function runCommand(label: string, path: string, body?: object) {
    try {
      setBusy(true); setError("");
      await postJson(path, body);
      if (label === "Run demo") {
        for (let i = 0; i < 120; i++) {
          await new Promise((r) => setTimeout(r, 100));
          const s = await getJson<Snapshot>("/api/state");
          setSnapshot(s);
          if (!s.runtime?.scenario_running) break;
        }
        setLiveSender(""); setLiveText("");
      } else {
        setSnapshot(await getJson("/api/state"));
      }
      if (label === "Reset") {
        setSuggestions(new Map()); setSentReplies(new Map());
        setVoiceState("idle");
        setDecisionLog([]);
        setVehicle(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally { setBusy(false); }
  }

  async function generateSummary() {
    if (!snapshot || snapshot.queue.deferred_count === 0) return;
    try {
      setGeneratingSummary(true); setError("");
      const gen = await postJson("/api/digest/generate");
      setSnapshot(gen);
      if (!(gen as Snapshot).current_digest) return;
      setSnapshot(await postJson("/api/digest/release"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally { setGeneratingSummary(false); }
  }

  async function flushQueue() {
    try {
      setError("");
      await postJson("/api/queue/flush");
      await refreshAll();
    } catch { setError("Flush failed"); }
  }

  async function fetchSuggestion(id: string) {
    setSuggestions((p) => new Map(p).set(id, "loading"));
    try {
      const r = await postJson<Snapshot>("/api/reply/generate", { message_id: id });
      const reply = r.current_reply;
      if (reply) setSuggestions((p) => new Map(p).set(id, reply));
    } catch { setSuggestions((p) => { const n = new Map(p); n.delete(id); return n; }); }
  }

  async function playVoiceBrief() {
    if (voiceState !== "idle") return;
    setVoiceState("loading");
    try {
      const r = await fetch(`${API}/api/voice/brief`, { method: "POST" });
      const d = await r.json() as { audio?: string };
      if (!r.ok || !d.audio) throw new Error("no audio");
      const bytes = new Uint8Array(atob(d.audio).split("").map((c) => c.charCodeAt(0)));
      const ctx = new AudioContext();
      const buf = await ctx.decodeAudioData(bytes.buffer.slice(0) as ArrayBuffer);
      const src = ctx.createBufferSource();
      src.buffer = buf; src.connect(ctx.destination);
      setVoiceState("playing"); src.start(0);
      src.onended = () => { setVoiceState("idle"); void ctx.close(); };
    } catch { setVoiceState("error"); setTimeout(() => setVoiceState("idle"), 3000); }
  }

  // ── Loading state ──
  if (!snapshot) {
    return (
      <div className="shell loading-shell">
        <div className="loading-card">
          <div className="loading-spinner" />
          <p>Initialising SignalBrief...</p>
        </div>
      </div>
    );
  }

  const controlsDisabled = busy || generatingSummary;
  const tone = signalTone(snapshot.context.signal_strength);
  const visibleMessages = snapshot.messages
    .filter((m) => displayStatus(m.status) !== "ignored")
    .slice().reverse();

  // ── Render ──
  return (
    <div className="shell">
      {/* ── Top Header ── */}
      <header className="header">
        <div className="header-brand">
          <div className="brand-icon">SB</div>
          <div>
            <p className="eyebrow">Automotive Notification Triage</p>
            <h1>SignalBrief</h1>
          </div>
        </div>
        <div className="header-status">
          <span className={`network-badge net-${(vehicle?.network_type ?? "4G").replace("/", "")}`}>
            {vehicle?.network_type ?? "4G"}
          </span>
          <span className={`zone-status-badge zone-${vehicle?.zone_colour ?? "GREEN"}`}>
            {vehicle?.zone_colour ?? "GREEN"}
          </span>
          {livePrefs.dnd_active_now && (
            <span className="dnd-active-badge" title="Do Not Disturb window active — non-urgent messages held">
              🌙 DND
            </span>
          )}
          <button
            id="btn-auto-drive"
            className={`auto-drive-btn ${autoDrive ? "auto-drive-on" : ""}`}
            onClick={() => setAutoDrive((v) => !v)}
            title={autoDrive ? "Stop auto-drive simulation" : "Start auto-drive simulation"}
          >
            {autoDrive ? "⏹ Stop Drive" : "▶ Auto Drive"}
          </button>
          {snapshot.runtime?.scenario_running && (
            <span className="running-badge">DEMO RUNNING</span>
          )}
        </div>
        <div className="top-actions">
          <div className="live-message-input">
            <input id="live-sender" type="text" placeholder="Sender" value={liveSender}
              disabled={controlsDisabled} onChange={(e) => setLiveSender(e.target.value)} />
            <input id="live-text" type="text" placeholder="Type a message to triage live..."
              value={liveText} disabled={controlsDisabled} onChange={(e) => setLiveText(e.target.value)} />
          </div>
          <button id="btn-run-demo" disabled={controlsDisabled}
            onClick={() => void runCommand("Run demo", "/api/scenario/start",
              liveText.trim() ? { live_message: { sender: liveSender.trim() || "You", text: liveText.trim(), topic: "live" } } : undefined
            )}>
            {busy && !stepping ? "Running..." : "Run Demo"}
          </button>
          <button id="btn-reset" disabled={controlsDisabled}
            onClick={() => void runCommand("Reset", "/api/scenario/reset")}>
            Reset
          </button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      {/* ── Tab Navigation ── */}
      <nav className="tab-nav">
        {([
          { id: "cockpit",      label: "Cockpit",      icon: "🚗" },
          { id: "route",        label: "Route Map",     icon: "🗺️" },
          { id: "log",          label: "Decision Log",  icon: "📋" },
          { id: "messages",     label: "Messages",      icon: "💬" },
          { id: "preferences",  label: "Preferences",   icon: "⚙️" },
        ] as const).map((t) => (
          <button
            key={t.id}
            id={`tab-${t.id}`}
            className={`tab-btn ${tab === t.id ? "tab-active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            <span className="tab-icon">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </nav>

      {/* ── Tab Content ── */}
      <main className="tab-content">

        {/* COCKPIT TAB */}
        {tab === "cockpit" && (
          <HMIDisplay
            vehicle={vehicle}
            snapshot={snapshot}
            onStep={() => void simulateStep()}
            onGenerate={() => void generateSummary()}
            onFlush={() => void flushQueue()}
            busy={controlsDisabled}
            stepping={stepping}
            dndActive={livePrefs.dnd_active_now}
            deferThreshold={livePrefs.defer_threshold}
            deliverThreshold={livePrefs.deliver_threshold}
          />
        )}

        {/* ROUTE MAP TAB */}
        {tab === "route" && (
          <div className="route-tab-root">
            <GeoRouteMap waypoints={waypoints} vehicle={vehicle} />
          </div>
        )}

        {/* DECISION LOG TAB */}
        {tab === "log" && (
          <DecisionLog
            entries={decisionLog}
            onRefresh={() => void refreshLog()}
            loading={logLoading}
          />
        )}

        {/* PREFERENCES TAB */}
        {tab === "preferences" && (
          <PreferencesPanel
            onSaved={async () => {
              await Promise.all([refreshPrefs(), refreshAll()]);
            }}
          />
        )}

        {/* MESSAGES TAB */}
        {tab === "messages" && (
          <div className="messages-tab-root">
            {/* Signal strip */}
            <div className="signal-panel">
              <div className="signal-label-row">
                <span>Signal Quality</span>
                <strong>{snapshot.context.signal_strength}/100</strong>
              </div>
              <div className={`signal-track ${tone}`}>
                <div className={`signal-fill ${tone}`} style={{ width: `${snapshot.context.signal_strength}%` }} />
              </div>
              <p className="active-rule-text">{snapshot.runtime?.active_rule_text}</p>
            </div>

            {/* Demo signal presets */}
            <div className="demo-controls">
              {[
                { signal: 15, label: "Dead Zone" },
                { signal: 35, label: "Tunnel" },
                { signal: 55, label: "City" },
                { signal: 85, label: "Highway" },
              ].map(({ signal, label }) => (
                <button key={label} disabled={controlsDisabled}
                  onClick={() => void postJson("/api/demo/signal", { signal_strength: signal, location_name: label }).then(setSnapshot)}>
                  {label}
                </button>
              ))}
            </div>

            {/* Message list */}
            <div className="content-grid">
              <article className="messages-panel">
                <div className="panel-title-row">
                  <h2>Messages</h2>
                  <span>{visibleMessages.length}</span>
                </div>
                {visibleMessages.length === 0 ? (
                  <div className="empty-state">Run the demo to populate messages.</div>
                ) : (
                  <div className="message-list">
                    {visibleMessages.map((msg) => {
                      const st = displayStatus(msg.status);
                      const sug = suggestions.get(msg.id);
                      const sentText = sentReplies.get(msg.id);
                      return (
                        <div className="message-row" key={msg.id}>
                          <div className="message-main">
                            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginBottom: "0.3rem", flexWrap: "wrap" }}>
                              <strong>{msg.sender}</strong>
                              {msg.triage_score !== undefined && (
                                <span className="triage-score-inline">score {msg.triage_score.toFixed(3)}</span>
                              )}
                              {msg.triage_action && (
                                <span className="triage-action-inline">{msg.triage_action.replace(/_/g, " ")}</span>
                              )}
                            </div>
                            <p>{msg.text}</p>
                            {sug && sug !== "loading" && (
                              <div className="suggestion-card">
                                <div className="suggestion-header">
                                  <span className="suggestion-label">Suggestion</span>
                                  <span className={`suggestion-tone tone-${sug.tone}`}>{sug.tone}</span>
                                  <button className="suggestion-dismiss"
                                    onClick={() => setSuggestions((p) => { const n = new Map(p); n.delete(msg.id); return n; })}>x</button>
                                </div>
                                <p className="suggestion-text">{sug.text}</p>
                                <div className="suggestion-actions">
                                  <button className="suggestion-send-btn"
                                    onClick={() => { setSentReplies((p) => new Map(p).set(msg.id, sug.text)); setSuggestions((p) => { const n = new Map(p); n.delete(msg.id); return n; }); }}>
                                    Send
                                  </button>
                                </div>
                              </div>
                            )}
                            {sentText && (
                              <div className="sent-reply-preview">
                                <span className="sent-reply-label">Sent</span>
                                <span className="sent-reply-text">{sentText}</span>
                              </div>
                            )}
                          </div>
                          <div className="message-meta">
                            <span className={`status-badge ${st}`}>{st}</span>
                            <small>{fmtTime(msg.received_at)}</small>
                            {!sentText && msg.needs_reply && !sug && (
                              <button className="suggestion-btn" disabled={sug === "loading" || controlsDisabled}
                                onClick={() => void fetchSuggestion(msg.id)}>
                                {sug === "loading" ? "..." : "Suggest Reply"}
                              </button>
                            )}
                            {sentText && <span className="replied-badge">Replied</span>}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </article>

              <aside className="summary-panel">
                <button className="summary-button"
                  disabled={snapshot.queue.deferred_count === 0 || controlsDisabled || generatingSummary}
                  onClick={() => void generateSummary()}>
                  {generatingSummary ? "Generating..." : "Generate AI Brief"}
                </button>
                <div className="summary-card">
                  {snapshot.current_digest ? (
                    <>
                      <p className="summary-header">{snapshot.current_digest.summary}</p>
                      {snapshot.current_digest.message_summaries?.length > 0 && (
                        <div className="message-summaries">
                          {snapshot.current_digest.message_summaries.map((m) => (
                            <div key={m.id} className="message-summary-item">
                              <strong>{m.sender}:</strong> {m.summary}
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  ) : (
                    <p>Deferred messages will be bundled here when you generate the brief.</p>
                  )}
                </div>
                {visibleMessages.length > 0 && snapshot.runtime?.tts_enabled && (
                  <button
                    className={`play-brief-btn ${voiceState === "playing" ? "playing" : ""}`}
                    disabled={voiceState !== "idle" || controlsDisabled}
                    onClick={() => void playVoiceBrief()}>
                    {voiceState === "loading" ? "Preparing..." : voiceState === "playing" ? "Playing..." : voiceState === "error" ? "Voice unavailable" : "Play Brief"}
                  </button>
                )}
              </aside>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
