import type { Waypoint, VehicleContextState, ZoneColour } from "./types";

interface Props {
  waypoints: Waypoint[];
  vehicle: VehicleContextState | null;
}

const ZONE_FILL: Record<ZoneColour, string> = {
  GREEN:  "#22c55e",
  YELLOW: "#eab308",
  RED:    "#ef4444",
  DEAD:   "#6b7280",
};

// Normalize lat/lon to SVG coordinate space
function project(lat: number, lon: number, waypoints: Waypoint[]) {
  const lats = waypoints.map((w) => w.lat);
  const lons = waypoints.map((w) => w.lon);
  const minLat = Math.min(...lats), maxLat = Math.max(...lats);
  const minLon = Math.min(...lons), maxLon = Math.max(...lons);
  const padX = 40, padY = 40, W = 560, H = 280;
  const x = padX + ((lon - minLon) / (maxLon - minLon || 1)) * (W - padX * 2);
  const y = padY + (1 - (lat - minLat) / (maxLat - minLat || 1)) * (H - padY * 2);
  return { x: Math.round(x), y: Math.round(y) };
}

export default function GeoRouteMap({ waypoints, vehicle }: Props) {
  if (!waypoints || waypoints.length === 0) {
    return (
      <div className="map-placeholder">
        <p>Loading route...</p>
      </div>
    );
  }

  const pts = waypoints.map((w) => project(w.lat, w.lon, waypoints));
  const currentIdx = vehicle?.waypoint_index ?? 0;

  const polyline = pts.map((p, i) => `${p.x},${p.y}`).join(" ");

  return (
    <div className="geo-map-wrap">
      <div className="geo-map-header">
        <h3>Koramangala &#8594; Electronic City</h3>
        <span className="geo-map-subtitle">Bangalore Commute Route &mdash; {waypoints.length} waypoints</span>
      </div>

      <div className="geo-map-legend">
        {(["GREEN", "YELLOW", "RED", "DEAD"] as ZoneColour[]).map((z) => (
          <span key={z} className="legend-item">
            <span className="legend-dot" style={{ background: ZONE_FILL[z] }} />
            {z}
          </span>
        ))}
      </div>

      <svg viewBox="0 0 560 280" className="geo-svg" role="img" aria-label="Bangalore route map">
        {/* Route line segments colored by zone */}
        {waypoints.slice(0, -1).map((wp, i) => {
          const a = pts[i], b = pts[i + 1];
          return (
            <line
              key={i}
              x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              stroke={ZONE_FILL[wp.zone_colour]}
              strokeWidth={i === currentIdx ? 4 : 2.5}
              strokeLinecap="round"
              opacity={0.6}
            />
          );
        })}

        {/* Waypoint dots */}
        {waypoints.map((wp, i) => {
          const p = pts[i];
          const isCurrent = i === currentIdx;
          const isPast = i < currentIdx;
          return (
            <g key={i}>
              {isCurrent && (
                <circle cx={p.x} cy={p.y} r={14} fill={ZONE_FILL[wp.zone_colour]} opacity={0.2}>
                  <animate attributeName="r" values="10;16;10" dur="1.8s" repeatCount="indefinite" />
                </circle>
              )}
              <circle
                cx={p.x}
                cy={p.y}
                r={isCurrent ? 7 : 4}
                fill={isCurrent ? ZONE_FILL[wp.zone_colour] : isPast ? "rgba(255,255,255,0.3)" : ZONE_FILL[wp.zone_colour]}
                stroke={isCurrent ? "white" : "transparent"}
                strokeWidth={isCurrent ? 2 : 0}
              />
            </g>
          );
        })}

        {/* Current location label */}
        {(() => {
          const cp = pts[currentIdx];
          const label = waypoints[currentIdx]?.label ?? "";
          const isRight = cp.x < 300;
          return (
            <g>
              <rect
                x={isRight ? cp.x + 10 : cp.x - label.length * 5.5 - 14}
                y={cp.y - 14}
                width={label.length * 5.5 + 12}
                height={18}
                rx={4}
                fill="#1e1b4b"
                stroke={ZONE_FILL[waypoints[currentIdx]?.zone_colour ?? "GREEN"]}
                strokeWidth={1}
              />
              <text
                x={isRight ? cp.x + 16 : cp.x - label.length * 5.5 - 8}
                y={cp.y - 1}
                fontSize="9"
                fill="white"
                fontFamily="Inter, sans-serif"
              >
                {label}
              </text>
            </g>
          );
        })()}

        {/* Start / End markers */}
        <text x={pts[0].x - 6} y={pts[0].y - 10} fontSize="9" fill="#22c55e" fontFamily="Inter, sans-serif">START</text>
        <text x={pts[pts.length - 1].x - 6} y={pts[pts.length - 1].y - 10} fontSize="9" fill="#a78bfa" fontFamily="Inter, sans-serif">END</text>
      </svg>

      {/* Waypoint info table */}
      <div className="waypoint-table-wrap">
        <table className="waypoint-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Location</th>
              <th>Zone</th>
              <th>Network</th>
              <th>Speed</th>
            </tr>
          </thead>
          <tbody>
            {waypoints.map((wp, i) => (
              <tr
                key={i}
                className={i === currentIdx ? "wp-current" : i < currentIdx ? "wp-past" : ""}
              >
                <td>{i + 1}</td>
                <td>{wp.label}</td>
                <td>
                  <span className="zone-chip" style={{ background: `${ZONE_FILL[wp.zone_colour]}22`, color: ZONE_FILL[wp.zone_colour] }}>
                    {wp.zone_colour}
                  </span>
                </td>
                <td className="network-cell">{wp.network_type}</td>
                <td>{wp.speed_kmh} km/h</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
