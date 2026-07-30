"""Constants for the in-process metrics registry: metric names, label
names, bucket boundaries, and the cardinality blocklist (spec §12: never
label by an identifier that grows without bound).
"""

# Labels that would make a metric's cardinality scale with live games or
# users. Registering a metric with any of these as a label name is a
# programmer error, not a runtime condition, so it raises.
FORBIDDEN_LABELS = frozenset({"game_id", "user_id", "session_id"})

# --- Bucket boundaries ---
# Seconds, for latency-shaped histograms (e.g. drain_loop_lag_seconds).
DEFAULT_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
# Bytes, for frame-size histograms.
BYTE_BUCKETS = (50, 100, 150, 250, 500, 1000, 1500, 2500, 5000, 10000)
# Plain counts, for events-per-frame / events-per-move.
COUNT_BUCKETS = (0, 1, 2, 3, 4, 5, 8, 13, 21)

# --- Metric names ---
DRAIN_LOOP_LAG_SECONDS = "drain_loop_lag_seconds"
GAME_FRAMES_TOTAL = "game_frames_total"
GAME_FRAME_BYTES = "game_frame_bytes"
GAME_EVENTS_PER_FRAME = "game_events_per_frame"
GAME_STATE_EVENTS_TOTAL = "game_state_events_total"
ARBITER_EVENTS_TOTAL = "arbiter_events_total"
ARBITER_MOVES_TOTAL = "arbiter_moves_total"

# --- Label names ---
LABEL_EVENT = "event"
LABEL_TYPE = "type"
