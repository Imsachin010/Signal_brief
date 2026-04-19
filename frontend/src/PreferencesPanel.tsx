import { useEffect, useState, useCallback } from "react";

const API = import.meta.env.VITE_API_ROOT ?? "http://127.0.0.1:8000";

type Prefs = {
  sender_weights: Record<string, number>;
  whitelist: string[];
  dnd_windows: [number, number][];
  driving_speed_threshold_kmh: number;
  defer_threshold: number;
  deliver_threshold: number;
  dnd_active_now?: boolean;
};

type HistoryEntry = {
  timestamp: string;
  summary: string;
  changed_fields: string[];
};

type RetriegeResult = {
  evaluated: number;
  promoted_count: number;
  still_held_count: number;
  promoted: { sender: string; preview: string; old_action: string; new_action: string; triage_score: number; reason: string }[];
};

type PreviewResult = { total_deferred: number; would_promote: number; would_hold: number };

interface Props {
  onSaved?: () => Promise<void>;
}

// ── API Helpers ───────────────────────────────────────────────────────────────
async function getPrefs(): Promise<Prefs> {
  const r = await fetch(`${API}/api/preferences`);
  return r.json() as Promise<Prefs>;
}
async function savePrefs(body: object): Promise<Prefs> {
  const r = await fetch(`${API}/api/preferences`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  return r.json() as Promise<Prefs>;
}
async function resetPrefs(): Promise<Prefs> {
  const r = await fetch(`${API}/api/preferences/reset`, { method: "POST" });
  return r.json() as Promise<Prefs>;
}
async function doRetriage(): Promise<RetriegeResult> {
  const r = await fetch(`${API}/api/preferences/retriage`, { method: "POST" });
  return r.json() as Promise<RetriegeResult>;
}
async function getHistory(): Promise<HistoryEntry[]> {
  const r = await fetch(`${API}/api/preferences/history`);
  const d = await r.json() as { history: HistoryEntry[] };
  return d.history;
}
async function getPreview(): Promise<PreviewResult> {
  const r = await fetch(`${API}/api/preferences/retriage/preview`);
  return r.json() as Promise<PreviewResult>;
}

// ── Slider Component ──────────────────────────────────────────────────────────
function Slider({ label, value, onChange, min = 0, max = 1, step = 0.05 }:
  { label: string; value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number }
) {
  const pct = ((value - min) / (max - min)) * 100;
  const color = value >= 0.75 ? "#22c55e" : value >= 0.45 ? "#eab308" : "#ef4444";
  return (
    <div className="pref-slider-row">
      <span className="pref-slider-label">{label}</span>
      <div className="pref-slider-wrap">
        <input type="range" min={min} max={max} step={step} value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="pref-slider"
          style={{ "--fill-pct": `${pct}%`, "--fill-color": color } as React.CSSProperties}
        />
        <span className="pref-slider-val" style={{ color }}>{value.toFixed(2)}</span>
      </div>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return "just now";
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffMin < 1440) return `${Math.floor(diffMin / 60)}h ago`;
    return d.toLocaleDateString();
  } catch { return iso; }
}

function fieldBadgeColor(field: string): string {
  if (field === "whitelist") return "#fde047";
  if (field === "sender_weights") return "#a78bfa";
  if (field === "dnd_windows") return "#60a5fa";
  if (field.includes("threshold")) return "#4ade80";
  if (field === "all") return "#f87171";
  return "#94a3b8";
}

// ── Main Component ────────────────────────────────────────────────────────────
export default function PreferencesPanel({ onSaved }: Props) {
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  // Editable state
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [whitelist, setWhitelist] = useState<string[]>([]);
  const [newWhitelistEntry, setNewWhitelistEntry] = useState("");
  const [dndStart, setDndStart] = useState(22);
  const [dndEnd, setDndEnd] = useState(7);
  const [drivingThreshold, setDrivingThreshold] = useState(15.0);
  const [deferThreshold, setDeferThreshold] = useState(0.45);
  const [deliverThreshold, setDeliverThreshold] = useState(0.65);
  const [newSender, setNewSender] = useState("");
  const [newWeight, setNewWeight] = useState(0.5);

  // Impact preview + history + retriage result
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [retriageResult, setRetrieageResult] = useState<RetriegeResult | null>(null);
  const [retriaging, setRetriaging] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  // Load initial data
  const loadAll = useCallback(() => {
    void getPrefs().then((p) => {
      setPrefs(p);
      setWeights({ ...p.sender_weights });
      setWhitelist([...p.whitelist]);
      setDrivingThreshold(p.driving_speed_threshold_kmh);
      setDeferThreshold(p.defer_threshold);
      setDeliverThreshold(p.deliver_threshold);
      if (p.dnd_windows.length > 0) {
        setDndStart(p.dnd_windows[0][0]);
        setDndEnd(p.dnd_windows[0][1]);
      }
    }).catch(() => setError("Failed to load preferences"));

    void getHistory().then(setHistory).catch(() => setHistory([]));
    void getPreview().then(setPreview).catch(() => setPreview(null));
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  // ── Save ─────────────────────────────────────────────────────────────────────
  async function handleSave() {
    setSaving(true); setSaved(false); setError(""); setRetrieageResult(null);
    try {
      const updated = await savePrefs({
        sender_weights_replace: weights,
        whitelist,
        dnd_windows: [[dndStart, dndEnd]],
        driving_speed_threshold_kmh: drivingThreshold,
        defer_threshold: deferThreshold,
        deliver_threshold: deliverThreshold,
      });
      setPrefs(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);

      // Auto retriage — apply to deferred queue immediately
      setRetriaging(true);
      const result = await doRetriage();
      setRetrieageResult(result);
      setRetriaging(false);

      // Refresh history + preview after save
      const [newHistory, newPreview] = await Promise.all([getHistory(), getPreview()]);
      setHistory(newHistory);
      setPreview(newPreview);

      // Notify parent (refresh cockpit/messages)
      await onSaved?.();
    } catch { setError("Failed to save preferences"); }
    finally { setSaving(false); setRetriaging(false); }
  }

  async function handleReset() {
    setSaving(true); setError(""); setRetrieageResult(null);
    try {
      const defaults = await resetPrefs();
      setPrefs(defaults);
      setWeights({ ...defaults.sender_weights });
      setWhitelist([...defaults.whitelist]);
      if (defaults.dnd_windows.length > 0) {
        setDndStart(defaults.dnd_windows[0][0]);
        setDndEnd(defaults.dnd_windows[0][1]);
      }
      setDrivingThreshold(defaults.driving_speed_threshold_kmh);
      setDeferThreshold(defaults.defer_threshold);
      setDeliverThreshold(defaults.deliver_threshold);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      const [newHistory] = await Promise.all([getHistory(), onSaved?.()]);
      setHistory(newHistory);
    } catch { setError("Failed to reset preferences"); }
    finally { setSaving(false); }
  }

  function addToWhitelist() {
    const name = newWhitelistEntry.trim();
    if (!name || whitelist.map(w => w.toLowerCase()).includes(name.toLowerCase())) return;
    setWhitelist((prev) => [...prev, name]);
    setNewWhitelistEntry("");
  }

  function addSenderWeight() {
    const name = newSender.trim();
    if (!name) return;
    setWeights((prev) => ({ ...prev, [name.toLowerCase()]: newWeight }));
    setNewSender(""); setNewWeight(0.5);
  }

  if (!prefs) {
    return (
      <div className="pref-loading">
        {error ? <p className="pref-error">{error}</p> : <p>Loading preferences...</p>}
      </div>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────────────
  return (
    <div className="pref-root">

      {/* HEADER */}
      <div className="pref-header">
        <div>
          <h3>User Preferences</h3>
          <p className="pref-subtitle">Personalise triage rules, sender priorities, and delivery windows</p>
        </div>
        <div className="pref-header-actions">
          {preview && preview.total_deferred > 0 && (
            <div className="pref-impact-badge" title="Messages in queue that would be promoted by current settings">
              <span className="pref-impact-icon">⚡</span>
              {preview.would_promote} / {preview.total_deferred} in queue would unlock
            </div>
          )}
          <button className="hmi-btn hmi-btn-ghost pref-reset-btn"
            onClick={() => void handleReset()} disabled={saving} id="btn-reset-prefs">
            Reset Defaults
          </button>
          <button
            className={`hmi-btn hmi-btn-primary pref-save-btn ${saved ? "pref-saved" : ""}`}
            onClick={() => void handleSave()} disabled={saving || retriaging} id="btn-save-prefs">
            {retriaging ? "Applying..." : saving ? "Saving..." : saved ? "✓ Saved & Applied" : "Save & Apply"}
          </button>
        </div>
      </div>

      {error && <div className="pref-error-banner">{error}</div>}

      {/* RETRIAGE RESULT BANNER */}
      {retriageResult && !retriaging && (
        <div className={`retriage-banner ${retriageResult.promoted_count > 0 ? "retriage-promoted" : "retriage-none"}`}>
          <span className="retriage-icon">{retriageResult.promoted_count > 0 ? "🚀" : "✓"}</span>
          <div className="retriage-text">
            {retriageResult.promoted_count > 0 ? (
              <>
                <strong>{retriageResult.promoted_count} message{retriageResult.promoted_count !== 1 ? "s" : ""} promoted</strong>
                {" "}from the queue — they'll now appear in Messages as delivered.
                {retriageResult.promoted.length > 0 && (
                  <div className="retriage-list">
                    {retriageResult.promoted.map((m) => (
                      <span key={m.sender + m.preview} className="retriage-item">
                        <strong>{m.sender}</strong>: "{m.preview.substring(0, 40)}…"
                        <span className="retriage-action">{m.new_action.replace(/_/g, " ")}</span>
                      </span>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <span>Preferences saved. {retriageResult.evaluated} message{retriageResult.evaluated !== 1 ? "s" : ""} evaluated — all remain held under current context.</span>
            )}
          </div>
          <button className="retriage-dismiss" onClick={() => setRetrieageResult(null)}>✕</button>
        </div>
      )}

      {/* SETTINGS GRID */}
      <div className="pref-grid">

        {/* Triage Thresholds */}
        <section className="pref-card">
          <div className="pref-card-title">
            <span className="pref-card-icon">⚖️</span>
            Triage Score Thresholds
          </div>
          <p className="pref-card-desc">
            Messages scoring above <strong>Deliver</strong> are delivered immediately.
            Between <strong>Defer</strong> and <strong>Deliver</strong> they go to digest.
            Below <strong>Defer</strong> they are held.
          </p>
          <div className="threshold-visual">
            <div className="threshold-track">
              <div className="threshold-zone-hold" style={{ width: `${deferThreshold * 100}%` }} />
              <div className="threshold-zone-defer"
                style={{ width: `${(deliverThreshold - deferThreshold) * 100}%`, left: `${deferThreshold * 100}%` }} />
              <div className="threshold-zone-deliver"
                style={{ width: `${(1 - deliverThreshold) * 100}%`, left: `${deliverThreshold * 100}%` }} />
              <div className="threshold-marker" style={{ left: `${deferThreshold * 100}%` }}>
                <div className="threshold-marker-line" /><span>Defer</span>
              </div>
              <div className="threshold-marker" style={{ left: `${deliverThreshold * 100}%` }}>
                <div className="threshold-marker-line" /><span>Deliver</span>
              </div>
            </div>
            <div className="threshold-legend">
              <span className="tl-hold">Hold (&lt;{deferThreshold.toFixed(2)})</span>
              <span className="tl-defer">Digest</span>
              <span className="tl-deliver">Deliver (&gt;{deliverThreshold.toFixed(2)})</span>
            </div>
          </div>
          <Slider label="Defer threshold" value={deferThreshold}
            onChange={(v) => { if (v < deliverThreshold) setDeferThreshold(v); }} />
          <Slider label="Deliver threshold" value={deliverThreshold}
            onChange={(v) => { if (v > deferThreshold) setDeliverThreshold(v); }} />
        </section>

        {/* Sender Weights */}
        <section className="pref-card">
          <div className="pref-card-title">
            <span className="pref-card-icon">👤</span>
            Sender Priority Weights
          </div>
          <p className="pref-card-desc">Higher weight = more likely to be delivered immediately (0.0–1.0). Weight ≥ 0.85 promotes to Tier 3 automatically.</p>
          <div className="pref-sender-list">
            {Object.entries(weights).map(([sender, weight]) => (
              <div key={sender} className="pref-sender-row">
                <Slider label={sender} value={weight}
                  onChange={(v) => setWeights((prev) => ({ ...prev, [sender]: v }))} />
                <button className="pref-remove-btn"
                  onClick={() => setWeights((prev) => { const n = { ...prev }; delete n[sender]; return n; })} title="Remove">✕</button>
              </div>
            ))}
          </div>
          <div className="pref-add-row">
            <input type="text" placeholder="Sender name" value={newSender}
              onChange={(e) => setNewSender(e.target.value)} className="pref-input"
              onKeyDown={(e) => e.key === "Enter" && addSenderWeight()} />
            <Slider label="Weight" value={newWeight} onChange={setNewWeight} />
            <button className="hmi-btn hmi-btn-ghost pref-add-btn" onClick={addSenderWeight}>Add</button>
          </div>
        </section>

        {/* Whitelist */}
        <section className="pref-card">
          <div className="pref-card-title">
            <span className="pref-card-icon">⭐</span>
            Whitelist (Always Deliver)
          </div>
          <p className="pref-card-desc">
            These senders always bypass DND and score thresholds — immediate delivery every time.
            {" "}<strong>Pro tip:</strong> Add a sender's name and hit Save & Apply to unlock their held messages immediately.
          </p>
          <div className="whitelist-tags">
            {whitelist.map((name) => (
              <span key={name} className="whitelist-tag">
                {name}
                <button className="whitelist-remove"
                  onClick={() => setWhitelist((prev) => prev.filter((n) => n !== name))}>✕</button>
              </span>
            ))}
            {whitelist.length === 0 && <span className="pref-empty">No whitelisted senders</span>}
          </div>
          <div className="pref-add-row">
            <input type="text" placeholder="Add sender name" value={newWhitelistEntry}
              onChange={(e) => setNewWhitelistEntry(e.target.value)} className="pref-input"
              onKeyDown={(e) => e.key === "Enter" && addToWhitelist()} />
            <button className="hmi-btn hmi-btn-ghost pref-add-btn" onClick={addToWhitelist}>Add</button>
          </div>
        </section>

        {/* DND + Driving */}
        <section className="pref-card">
          <div className="pref-card-title">
            <span className="pref-card-icon">🌙</span>
            Do Not Disturb Window
          </div>
          <p className="pref-card-desc">Non-urgent messages are held during these hours (24h clock)</p>
          <div className="dnd-row">
            <div className="dnd-field">
              <label>Start hour</label>
              <input type="number" min={0} max={23} value={dndStart}
                onChange={(e) => setDndStart(parseInt(e.target.value))}
                className="pref-input dnd-input" />
            </div>
            <div className="dnd-arrow">→</div>
            <div className="dnd-field">
              <label>End hour</label>
              <input type="number" min={0} max={23} value={dndEnd}
                onChange={(e) => setDndEnd(parseInt(e.target.value))}
                className="pref-input dnd-input" />
            </div>
          </div>
          <p className="dnd-preview">
            DND active: <strong>{String(dndStart).padStart(2, "0")}:00</strong> → <strong>{String(dndEnd).padStart(2, "0")}:00</strong>
          </p>

          <div className="pref-divider" />

          <div className="pref-card-title" style={{ marginTop: "0.75rem" }}>
            <span className="pref-card-icon">🏎️</span>
            Driving Mode Threshold
          </div>
          <p className="pref-card-desc">Speed above which driving restrictions apply (audio-only delivery)</p>
          <Slider label="Speed threshold" value={drivingThreshold}
            onChange={setDrivingThreshold} min={0} max={80} step={5} />
          <p className="dnd-preview">
            Driving mode at: <strong>&gt; {drivingThreshold} km/h</strong>
          </p>
        </section>
      </div>

      {/* CHANGE HISTORY TIMELINE */}
      <div className="pref-history-section">
        <button className="pref-history-toggle" onClick={() => setShowHistory(!showHistory)}
          id="btn-toggle-history">
          <span>📋 Change History</span>
          <span className="pref-history-count">{history.length} entries</span>
          <span className="pref-history-chevron">{showHistory ? "▲" : "▼"}</span>
        </button>

        {showHistory && (
          <div className="pref-history-list">
            {history.length === 0 ? (
              <p className="pref-empty" style={{ padding: "1rem" }}>No preference changes recorded yet. Make a change and hit Save & Apply.</p>
            ) : (
              history.map((entry, i) => (
                <div key={i} className="pref-history-entry">
                  <div className="phe-time">{formatTime(entry.timestamp)}</div>
                  <div className="phe-body">
                    <div className="phe-summary">{entry.summary}</div>
                    <div className="phe-fields">
                      {entry.changed_fields.map((f) => (
                        <span key={f} className="phe-field-badge"
                          style={{ borderColor: fieldBadgeColor(f), color: fieldBadgeColor(f) }}>
                          {f.replace(/_/g, " ")}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>

    </div>
  );
}
