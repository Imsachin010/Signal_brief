import { useEffect, useState } from "react";

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

interface Props {
  onSaved?: () => Promise<void>;
}

async function getPrefs(): Promise<Prefs> {
  const r = await fetch(`${API}/api/preferences`);
  return r.json() as Promise<Prefs>;
}
async function savePrefs(body: object): Promise<Prefs> {
  const r = await fetch(`${API}/api/preferences`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json() as Promise<Prefs>;
}
async function resetPrefs(): Promise<Prefs> {
  const r = await fetch(`${API}/api/preferences/reset`, { method: "POST" });
  return r.json() as Promise<Prefs>;
}

function Slider({ label, value, onChange, min = 0, max = 1, step = 0.05 }:
  { label: string; value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number }
) {
  const pct = ((value - min) / (max - min)) * 100;
  const color = value >= 0.75 ? "#22c55e" : value >= 0.45 ? "#eab308" : "#ef4444";
  return (
    <div className="pref-slider-row">
      <span className="pref-slider-label">{label}</span>
      <div className="pref-slider-wrap">
        <input
          type="range" min={min} max={max} step={step} value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="pref-slider"
          style={{ "--fill-pct": `${pct}%`, "--fill-color": color } as React.CSSProperties}
        />
        <span className="pref-slider-val" style={{ color }}>{value.toFixed(2)}</span>
      </div>
    </div>
  );
}

export default function PreferencesPanel({ onSaved }: Props) {
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  // Editable weights
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

  useEffect(() => {
    getPrefs().then((p) => {
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
  }, []);

  async function handleSave() {
    setSaving(true); setSaved(false); setError("");
    try {
      const updated = await savePrefs({
        // Send sender_weights_replace for full sync
        sender_weights_replace: weights,
        whitelist,
        dnd_windows: [[dndStart, dndEnd]],
        driving_speed_threshold_kmh: drivingThreshold,
        defer_threshold: deferThreshold,
        deliver_threshold: deliverThreshold,
      });
      setPrefs(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
      // Notify parent so cockpit + messages re-read triage state
      await onSaved?.();
    } catch { setError("Failed to save preferences"); }
    finally { setSaving(false); }
  }

  async function handleReset() {
    setSaving(true); setError("");
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
      await onSaved?.();
    } catch { setError("Failed to reset preferences"); }
    finally { setSaving(false); }
  }

  function addToWhitelist() {
    const name = newWhitelistEntry.trim();
    if (!name || whitelist.includes(name)) return;
    setWhitelist((prev) => [...prev, name]);
    setNewWhitelistEntry("");
  }

  function removeFromWhitelist(name: string) {
    setWhitelist((prev) => prev.filter((n) => n !== name));
  }

  function addSenderWeight() {
    const name = newSender.trim();
    if (!name) return;
    setWeights((prev) => ({ ...prev, [name.toLowerCase()]: newWeight }));
    setNewSender("");
    setNewWeight(0.5);
  }

  function removeSenderWeight(key: string) {
    setWeights((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }

  if (!prefs) {
    return (
      <div className="pref-loading">
        {error ? <p className="pref-error">{error}</p> : <p>Loading preferences...</p>}
      </div>
    );
  }

  return (
    <div className="pref-root">
      <div className="pref-header">
        <div>
          <h3>User Preferences</h3>
          <p className="pref-subtitle">Personalise triage rules, sender priorities, and delivery windows</p>
        </div>
        <div className="pref-header-actions">
          <button
            className="hmi-btn hmi-btn-ghost pref-reset-btn"
            onClick={() => void handleReset()}
            disabled={saving}
            id="btn-reset-prefs"
          >
            Reset Defaults
          </button>
          <button
            className={`hmi-btn hmi-btn-primary pref-save-btn ${saved ? "pref-saved" : ""}`}
            onClick={() => void handleSave()}
            disabled={saving}
            id="btn-save-prefs"
          >
            {saving ? "Saving..." : saved ? "✓ Saved" : "Save Changes"}
          </button>
        </div>
      </div>

      {error && <div className="pref-error-banner">{error}</div>}

      <div className="pref-grid">

        {/* ── Triage Thresholds ── */}
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
                <div className="threshold-marker-line" />
                <span>Defer</span>
              </div>
              <div className="threshold-marker" style={{ left: `${deliverThreshold * 100}%` }}>
                <div className="threshold-marker-line" />
                <span>Deliver</span>
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

        {/* ── Sender Weights ── */}
        <section className="pref-card">
          <div className="pref-card-title">
            <span className="pref-card-icon">👤</span>
            Sender Priority Weights
          </div>
          <p className="pref-card-desc">Higher weight = more likely to be delivered immediately (0.0–1.0)</p>
          <div className="pref-sender-list">
            {Object.entries(weights).map(([sender, weight]) => (
              <div key={sender} className="pref-sender-row">
                <Slider
                  label={sender}
                  value={weight}
                  onChange={(v) => setWeights((prev) => ({ ...prev, [sender]: v }))}
                />
                <button className="pref-remove-btn"
                  onClick={() => removeSenderWeight(sender)} title="Remove">✕</button>
              </div>
            ))}
          </div>
          <div className="pref-add-row">
            <input
              type="text" placeholder="Sender name"
              value={newSender} onChange={(e) => setNewSender(e.target.value)}
              className="pref-input"
              onKeyDown={(e) => e.key === "Enter" && addSenderWeight()}
            />
            <Slider label="Weight" value={newWeight} onChange={setNewWeight} />
            <button className="hmi-btn hmi-btn-ghost pref-add-btn" onClick={addSenderWeight}>Add</button>
          </div>
        </section>

        {/* ── Whitelist ── */}
        <section className="pref-card">
          <div className="pref-card-title">
            <span className="pref-card-icon">⭐</span>
            Whitelist (Always Deliver)
          </div>
          <p className="pref-card-desc">These senders always bypass DND and score thresholds</p>
          <div className="whitelist-tags">
            {whitelist.map((name) => (
              <span key={name} className="whitelist-tag">
                {name}
                <button className="whitelist-remove" onClick={() => removeFromWhitelist(name)}>✕</button>
              </span>
            ))}
            {whitelist.length === 0 && <span className="pref-empty">No whitelisted senders</span>}
          </div>
          <div className="pref-add-row">
            <input
              type="text" placeholder="Add sender name"
              value={newWhitelistEntry} onChange={(e) => setNewWhitelistEntry(e.target.value)}
              className="pref-input"
              onKeyDown={(e) => e.key === "Enter" && addToWhitelist()}
            />
            <button className="hmi-btn hmi-btn-ghost pref-add-btn" onClick={addToWhitelist}>Add</button>
          </div>
        </section>

        {/* ── DND Window ── */}
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
          <Slider
            label="Speed threshold"
            value={drivingThreshold}
            onChange={setDrivingThreshold}
            min={0} max={80} step={5}
          />
          <p className="dnd-preview">
            Driving mode at: <strong>&gt; {drivingThreshold} km/h</strong>
          </p>
        </section>
      </div>
    </div>
  );
}
