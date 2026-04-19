export type LocationStatus = "live" | "unavailable";
export type SignalBand = "low" | "medium" | "high";
export type Priority = "urgent" | "actionable" | "informational" | "ignore";
export type ZoneColour = "GREEN" | "YELLOW" | "RED" | "DEAD";
export type NetworkType = "4G" | "3G" | "2G" | "OFFLINE";
export type MessageStatus =
  | "received"
  | "classified"
  | "deferred"
  | "delivered"
  | "summarized"
  | "ignored";

export type Message = {
  id: string;
  sender: string;
  text: string;
  topic: string;
  received_at: string;
  priority: Priority;
  needs_reply: boolean;
  deadline_hint: string;
  action_items: string[];
  status: MessageStatus;
  decision_reason: string;
  triage_score?: number;
  urgency_score?: number;
  triage_action?: string;
};

export type Digest = {
  id: string;
  created_at: string;
  summary: string;
  digest_type: string;
  urgent_count: number;
  actionable_count: number;
  informational_count: number;
  ignored_count: number;
  action_items: string[];
  highlighted_message_ids: string[];
  message_summaries: { id: string; sender: string; summary: string }[];
};

export type ReplySuggestion = {
  message_id: string;
  text: string;
  tone: string;
};

export type PhoneCard = {
  id: string;
  kind: "urgent_delivery" | "digest_release";
  title: string;
  body: string;
  accent: string;
  created_at: string;
};

export type ContextState = {
  location_name: string;
  latitude: number | null;
  longitude: number | null;
  accuracy_meters: number | null;
  signal_strength: number;
  signal_band: SignalBand;
  release_window_open: boolean;
  location_status: LocationStatus;
};

export type EventItem = {
  id: string;
  type: string;
  timestamp: string;
  payload: Record<string, unknown>;
};

export type UiStage =
  | "idle"
  | "holding"
  | "urgent_bypass"
  | "brief_ready"
  | "brief_generated"
  | "released";

export type UiState = {
  stage: UiStage;
  headline: string;
  supporting_text: string;
  primary_action: "start_demo" | "generate_digest" | "release_digest" | "reset" | "none";
  primary_action_label: string;
  primary_action_reason: string;
  secondary_hint: string;
  show_phone_preview: boolean;
};

export type Snapshot = {
  context: ContextState;
  messages: Message[];
  queue: {
    deferred_count: number;
    delivered_count: number;
    summarized_count: number;
    ignored_count: number;
    urgent_count: number;
    actionable_count: number;
    informational_count: number;
  };
  current_digest: Digest | null;
  current_reply: ReplySuggestion | null;
  phone_cards: PhoneCard[];
  recent_events: EventItem[];
  ui: UiState;
  runtime: {
    scenario_running: boolean;
    ai_mode: "sarvam" | "fallback";
    sarvam_configured: boolean;
    tts_enabled: boolean;
    fallback_count: number;
    active_rule_text: string;
  };
};

// ---- Automotive Types -------------------------------------------------------

export type VehicleContextState = {
  waypoint_index: number;
  latitude: number;
  longitude: number;
  location_label: string;
  speed_kmh: number;
  is_driving: boolean;
  signal_quality: number;
  network_type: NetworkType;
  latency_ms: number;
  signal_band: SignalBand;
  zone_colour: ZoneColour;
  zone_colour_hex: string;
  in_coverage_zone: boolean;
  hour_of_day: number;
  is_work_hours: boolean;
  route_progress_pct: number;
  at_destination: boolean;
  current_geo_zone: ZoneColour;
  deferred_queue_count: number;
};

export type DecisionLogEntry = {
  message_id: string;
  timestamp: string;
  sender: string;
  message_preview: string;
  urgency_score: number;
  sender_tier: number;
  triage_score: number;
  action: string;
  reason: string;
  override_applied: boolean;
};

export type Waypoint = {
  index: number;
  lat: number;
  lon: number;
  label: string;
  base_signal: number;
  speed_kmh: number;
  zone_colour: ZoneColour;
  network_type: NetworkType;
  notes: string;
};

export type QueueItem = {
  message_id: string;
  sender: string;
  text_preview: string;
  triage_score: number;
  urgency_score: number;
  triage_action: string;
  queued_at: string;
};

export type QueueStats = {
  count: number;
  avg_score: number;
  max_score: number;
  min_score: number;
};

export type ZoneEvent = {
  from_zone: ZoneColour;
  to_zone: ZoneColour;
  location_label: string;
  signal_quality: number;
  should_flush_queue: boolean;
  should_hold_messages: boolean;
  flush_reason: string;
};
