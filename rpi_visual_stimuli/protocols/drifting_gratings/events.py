from __future__ import annotations

from ...core.event_logging import SHARED_EVENT_FIELDS


PROTOCOL_EVENT_FIELDS = [
    "trial_index",
    "orientation_id",
    "bar_orientation_deg",
    "drift_direction_deg",
    "repeat_number",
    "starting_phase_deg",
    "stim_frames",
    "iti_frames",
    "jitter_requested_sec",
    "cache_hash",
]


EVENT_FIELDS = SHARED_EVENT_FIELDS + PROTOCOL_EVENT_FIELDS


EVENT_TYPES = (
    "prestim_gray_on",
    "camera_start_requested",
    "camera_start_returned",
    "raw_cache_ready",
    "prestim_baseline_start",
    "prestim_baseline_end",
    "session_start",
    "stim_on",
    "iti_on",
    "final_gray",
    "session_end",
)
