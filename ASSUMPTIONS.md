# SignalBrief — Assumptions Log

> This document records every assumption made during the design and implementation of the SignalBrief Automotive Notification Triage System. Assumptions are grouped by domain and graded by confidence level and risk if the assumption turns out to be wrong.

---

## Grading Key

| Grade | Meaning |
|---|---|
| 🟢 **Safe** | Well-established norm, low risk if wrong |
| 🟡 **Moderate** | Reasonable but not validated, medium risk |
| 🔴 **High-Risk** | Significant design dependency, must be validated in production |

---

## 1. Automotive & Driving Context

| # | Assumption | Grade | Notes |
|---|---|---|---|
| A1 | A vehicle is considered "driving" when speed exceeds **15 km/h** | 🟡 | Configurable in Preferences, but 15 km/h was chosen arbitrarily. Slow urban traffic at 10 km/h may also require distraction limits. |
| A2 | The driver is the sole recipient of notifications | 🟡 | Passengers may also want to receive messages. A multi-profile system is not modelled. |
| A3 | Audio-only delivery is sufficient and safe above the driving speed threshold | 🟡 | TTS quality and cabin noise are not modelled. Assumes a working in-vehicle speaker system. |
| A4 | Signal zones (GREEN / YELLOW / RED / DEAD) map linearly to network reliability | 🟡 | Real networks are non-deterministic — a GREEN zone can still have packet loss. |
| A5 | Zone boundaries are geographic and static | 🔴 | In reality, tunnel entry, weather, and network load change zones dynamically. Our simulator uses fixed zone colours per waypoint. |
| A6 | A single Bangalore route (18 waypoints) is representative enough for simulation | 🟡 | The route demonstrates all four zone types, which is the design goal. Not meant to represent all real road conditions. |
| A7 | The vehicle always moves forward along the route (no U-turns, no detours) | 🟢 | Acceptable for a demo simulation. Real navigation would require bidirectional traversal. |
| A8 | The driver is aware of notifications being held and trusts the system to release them | 🔴 | User trust in automated deferral has not been user-tested. A visible queue count in the cockpit partially addresses this. |

---

## 2. Triage Score Formula

| # | Assumption | Grade | Notes |
|---|---|---|---|
| B1 | The four protocol weights (urgency 40%, sender 25%, signal 15%, context 10%, keyword 10%) are the correct relative importance | 🔴 | These weights were derived from the protocol spec, not from user studies or A/B tests. Real-world calibration is needed. |
| B2 | A message's urgency is independent of delivery order | 🟡 | A follow-up message ("It's serious, call me") is scored independently of its predecessor. Context chaining is not implemented. |
| B3 | `urgency_score` from the ML model is a reliable proxy for actual urgency | 🟡 | The model is trained on curated examples. Real messages may use sarcasm, abbreviations, or slang the model hasn't seen. |
| B4 | Dividing `sender_tier` by 4 (max tier) creates a meaningful linear normalisation | 🟡 | Tiers 1–4 are not equidistant in real social importance. A non-linear mapping (e.g. tier 4 = 1.0, tier 3 = 0.7) may be more accurate. |
| B5 | Signal quality in [0, 1] is a valid proxy for delivery reliability | 🟡 | Latency, packet loss, and server availability are not modelled. Signal ≠ deliverability. |
| B6 | Work-hours boost (+0.15 context) applies uniformly to all users | 🟡 | Shift workers, freelancers, and time zones are not accounted for. Work hours are hardcoded as 09:00–18:00. |
| B7 | The score is time-invariant within a single route step | 🟡 | A message that entered the queue 30 minutes ago has the same score as one that just arrived. No staleness decay is implemented. |
| B8 | A single threshold pair (defer, deliver) is sufficient for all message categories | 🟡 | It may make sense to have category-specific thresholds (e.g., medical alerts vs promotional messages). |

---

## 3. Machine Learning Model

| # | Assumption | Grade | Notes |
|---|---|---|---|
| C1 | TF-IDF + Logistic Regression is sufficient for urgency classification at this stage | 🟢 | Appropriate for a PoC. Real deployment would benefit from a fine-tuned transformer (BERT, MobileBERT). |
| C2 | The `urgency_dataset.csv` (~500 samples) is representative of real-world message diversity | 🔴 | Dataset is hand-curated. It does not cover all Indian-English colloquialisms, code-switching, or regional languages. |
| C3 | A binary-ish classification (urgent / actionable / informational / ignore) captures the meaningful decision space | 🟡 | Edge cases exist: "call me when you can" is informational but time-sensitive. The model may assign incorrect priority. |
| C4 | The ML model's output is stable across re-training runs given the same dataset | 🟢 | Logistic Regression is deterministic with a fixed random seed. |
| C5 | Inference latency of the local model is acceptable for real-time use | 🟢 | TF-IDF + LogReg inference is < 5ms. No latency concern for the PoC. |
| C6 | Users will not attempt to game the triage system by crafting messages with urgency keywords | 🟡 | A sender who writes "URGENT - lunch order?" would score high on keywords. The sender weight and tier partially mitigate this. |
| C7 | The training and inference text encoding (UTF-8, lowercase, English) matches real usage | 🟡 | Emojis, mixed-script text (Hindi + English), and voice-to-text transcriptions are not handled by the current vectoriser. |

---

## 4. Personalization & Sender Trust

| # | Assumption | Grade | Notes |
|---|---|---|---|
| D1 | Sender names are consistent across messages (exact or substring match) | 🟡 | "Mom", "Mummy", "Ma" and "मम्मी" are all the same person but would not match the same whitelist entry. |
| D2 | A whitelist bypass is always the right action for whitelisted senders, regardless of message content | 🟡 | A whitelisted sender could also send spam or irrelevant content. The user is responsible for curation. |
| D3 | Default DND window is 22:00–07:00 (local time) for all users | 🟡 | Shift workers or users in different time zones may need a different default. Time zone handling uses UTC server time. |
| D4 | The UTC clock on the server represents the user's local time for DND calculations | 🔴 | This is incorrect for non-UTC deployments. A production system must use the vehicle's local timezone. |
| D5 | Sender tier pattern matching (substring on name) is sufficient for tier classification | 🟡 | "Manish Shrivastav Boss" would be tier 3, but so would "Bossanova Records". False positives are possible. |
| D6 | A single preference profile applies to all contexts (work, personal, travel) | 🟡 | Real users may want "work mode" vs "personal mode" preferences that switch based on calendar or time. |
| D7 | Preference changes should take immediate effect on the existing message queue | 🟢 | This was a deliberate design choice (re-triage engine). The assumption is that users expect their changes to apply retroactively. |

---

## 5. Notification Delivery

| # | Assumption | Grade | Notes |
|---|---|---|---|
| E1 | A "delivered" message has been successfully shown to the user (visual or audio) | 🟡 | The system marks a message `delivered` after the triage decision — it has no feedback loop confirming the user actually consumed it. |
| E2 | Messages that are held do not expire | 🟡 | A "call me now" message held for 45 minutes is no longer actionable. No TTL (time-to-live) is implemented on queued messages. |
| E3 | Digest messages (bundled queue flush) are as effective as individual delivery for informational content | 🟡 | Users may miss important context if 10 messages are collapsed into one digest. |
| E4 | At most 3 messages should be delivered immediately on a queue flush | 🟡 | This threshold was set in the protocol spec. High-queue scenarios (15+ messages flushing at once) may need a different cap. |
| E5 | FALLBACK_VIBRATE is a meaningful delivery mechanism when signal is absent | 🟡 | The system only marks the decision — no actual vibration API call is implemented in the PoC. |
| E6 | The user reads messages in the Messages tab after receiving a "Suggest Reply" | 🟡 | The reply suggestion UX assumes the driver pulls over or a passenger interacts. Not safe for in-motion use. |

---

## 6. System & Infrastructure

| # | Assumption | Grade | Notes |
|---|---|---|---|
| F1 | The backend and frontend run on the same machine (localhost) | 🟢 | Confirmed for PoC. `VITE_API_ROOT` must be set for remote/cloud deployment. |
| F2 | The system handles one user's messages only (single-tenant) | 🟢 | Multi-user support would require auth, per-user preference stores, and message isolation. |
| F3 | File-based storage (`prefs.json`, `pref_history.json`) is sufficient for a local-first application | 🟢 | Appropriate for PoC and personal use. A production fleet deployment would need a database. |
| F4 | The Python venv and Node environment are already set up on the machine | 🟡 | The `start_backend.bat` and `start_frontend.bat` scripts assume both environments. First-run setup is not automated. |
| F5 | In-memory message storage is acceptable (messages are lost on server restart) | 🟡 | Acceptable for simulation. All messages must be re-ingested after restart. Preferences survive (file-backed). |
| F6 | A 3-second polling interval is frequent enough for real-time feel without overloading the server | 🟢 | At 3s, the UI is responsive enough for demonstration. WebSockets would be needed for sub-second updates in production. |
| F7 | CORS is fully open (allow all origins) in development | 🟢 | Intentional for local development. Must be locked down to specific origins for any deployed version. |
| F8 | The FastAPI server handles all requests synchronously without concurrency issues | 🟡 | An asyncio lock protects the controller state. However, rapid concurrent ingestion under stress has not been tested. |

---

## 7. User Behaviour & UX

| # | Assumption | Grade | Notes |
|---|---|---|---|
| G1 | The driver understands what "triage score" means without prior training | 🔴 | "score 0.339" is meaningful to an engineer, not necessarily to a general consumer. A more intuitive label (e.g., a coloured dot or priority stars) may be needed. |
| G2 | Users will configure the Preferences panel before use | 🟡 | Protocol defaults (Mom/Dad whitelisted, DND 22:00–07:00) are reasonable starting points, but require personalisation to be valuable. |
| G3 | The 5-tab dashboard layout is intuitive for in-vehicle use | 🔴 | UX testing in a real vehicle or simulator has not been done. Tab navigation while driving is unsafe; the cockpit tab only should be accessible while moving. |
| G4 | The "Auto Drive" simulation button is only used in demo/test contexts, not while actually driving | 🟢 | The simulation is clearly presented as a demo feature. |
| G5 | Users trust an AI system to decide which notifications to withhold from them | 🔴 | Trust in automated gatekeeping varies significantly by user. A "show all overridden decisions" feature exists (Decision Log) to build this trust. |
| G6 | The "Suggest Reply" feature will generate replies that match the user's voice and style | 🟡 | Reply suggestions are generic AI-generated text. The model has no knowledge of the user's writing style or relationship with the sender. |

---

## 8. Data & Privacy

| # | Assumption | Grade | Notes |
|---|---|---|---|
| H1 | Message content can be sent to an external LLM API (Sarvam AI) for classification | 🔴 | In production, message content is private. Users must explicitly consent to cloud processing. Local model mode avoids this. |
| H2 | Sender names and message text can be stored in server memory and preference files | 🟡 | For local deployment this is acceptable. Any cloud deployment must implement encryption at rest. |
| H3 | The preference history log (`pref_history.json`) does not expose sensitive information | 🟢 | History only stores field names and threshold values — no message content or sender names in preference change entries. |
| H4 | The training dataset (`urgency_dataset.csv`) contains no personal or sensitive data | 🟢 | Dataset is synthetic and curated for diversity of scenarios, not drawn from real user messages. |

---

## Summary of Highest-Risk Assumptions

These assumptions represent the biggest gaps between the current PoC and a production-ready system:

| ID | Assumption | What would change it |
|---|---|---|
| **A5** | Zone boundaries are static per waypoint | Real-time network quality API (e.g., HERE, Mapbox traffic layer) |
| **A8** | Users trust automated deferral | UX research, trust-building features (always-visible queue count, one-tap override) |
| **B1** | Triage formula weights are correct | A/B testing with real users driving test routes |
| **C2** | Training dataset is representative | Data collection from real anonymised message traffic |
| **D4** | Server UTC ≈ user local time | Vehicle timezone injection into the preference engine |
| **G1** | Users understand "triage score" | UX research and relabelling (e.g. stars / colour confidence ring) |
| **G3** | 5-tab dashboard is driveable UX | Automotive UX lab testing, NHTSA distraction guidelines compliance |
| **G5** | Users trust AI notification gatekeeping | Longitudinal trust study, transparent override mechanism |
| **H1** | Message content can leave the device | Explicit consent flow + local-only mode as default |

---

*Last updated: April 2026. This document should be revisited at every major milestone before pilot or production deployment.*
