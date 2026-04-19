import type { DecisionLogEntry } from "./types";

interface Props {
  entries: DecisionLogEntry[];
  onRefresh: () => void;
  loading: boolean;
}

const ACTION_COLORS: Record<string, string> = {
  DELIVER_IMMEDIATE:  "#22c55e",
  DELIVER_AUDIO_ONLY: "#06b6d4",
  DEFER_TO_ZONE:      "#a78bfa",
  HOLD_FOR_DIGEST:    "#6b7280",
  WHITELIST_OVERRIDE: "#f59e0b",
  FALLBACK_VIBRATE:   "#f97316",
  FLUSH_DIGEST:       "#3b82f6",
};

const TIER_LABELS: Record<number, string> = {
  0: "Unknown",
  1: "Peer",
  2: "Family",
  3: "Manager",
  4: "Whitelist",
};

function ScorePill({ value, size = "sm" }: { value: number; size?: "sm" | "lg" }) {
  const color = value >= 0.65 ? "#22c55e" : value >= 0.45 ? "#eab308" : "#6b7280";
  return (
    <span
      className={`score-pill score-pill-${size}`}
      style={{ background: `${color}22`, color, border: `1px solid ${color}44` }}
    >
      {value.toFixed(3)}
    </span>
  );
}

function formatTs(ts: string) {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts;
  }
}

export default function DecisionLog({ entries, onRefresh, loading }: Props) {
  return (
    <div className="decision-log-root">
      <div className="decision-log-header">
        <div>
          <h3>Triage Decision Log</h3>
          <p className="decision-log-subtitle">{entries.length} decisions recorded — newest first</p>
        </div>
        <button
          className="hmi-btn hmi-btn-ghost"
          onClick={onRefresh}
          disabled={loading}
          id="btn-refresh-log"
        >
          {loading ? "..." : "Refresh"}
        </button>
      </div>

      {entries.length === 0 ? (
        <div className="decision-log-empty">
          <p>No decisions yet. Send a message or run the demo scenario.</p>
        </div>
      ) : (
        <div className="decision-log-table-wrap">
          <table className="decision-log-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Sender</th>
                <th>Preview</th>
                <th>Urgency</th>
                <th>Tier</th>
                <th>Score</th>
                <th>Action</th>
                <th>Override</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e, idx) => (
                <tr key={`${e.message_id}-${idx}`} className="decision-log-row">
                  <td className="dl-time">{formatTs(e.timestamp)}</td>
                  <td className="dl-sender">{e.sender}</td>
                  <td className="dl-preview" title={e.reason}>
                    {e.message_preview.slice(0, 55)}{e.message_preview.length > 55 ? "..." : ""}
                  </td>
                  <td><ScorePill value={e.urgency_score} /></td>
                  <td className="dl-tier">
                    <span className="tier-chip">{TIER_LABELS[e.sender_tier] ?? e.sender_tier}</span>
                  </td>
                  <td><ScorePill value={e.triage_score} /></td>
                  <td>
                    <span
                      className="action-chip"
                      style={{
                        background: `${ACTION_COLORS[e.action] ?? "#6b7280"}22`,
                        color: ACTION_COLORS[e.action] ?? "#6b7280",
                        border: `1px solid ${ACTION_COLORS[e.action] ?? "#6b7280"}44`,
                      }}
                    >
                      {e.action.replace(/_/g, " ")}
                    </span>
                  </td>
                  <td className="dl-override">
                    {e.override_applied ? (
                      <span className="override-yes">RULE</span>
                    ) : (
                      <span className="override-no">SCORE</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Action distribution summary */}
      {entries.length > 0 && (() => {
        const counts: Record<string, number> = {};
        entries.forEach((e) => { counts[e.action] = (counts[e.action] ?? 0) + 1; });
        return (
          <div className="action-distribution">
            {Object.entries(counts).map(([action, count]) => (
              <div key={action} className="dist-chip">
                <span style={{ color: ACTION_COLORS[action] ?? "#6b7280" }}>
                  {action.replace(/_/g, " ")}
                </span>
                <strong>{count}</strong>
              </div>
            ))}
          </div>
        );
      })()}
    </div>
  );
}
