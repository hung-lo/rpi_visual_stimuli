from __future__ import annotations

from ...core.event_logging import SHARED_EVENT_FIELDS


PROTOCOL_EVENT_FIELDS = [
    "trial_index",
    "repeat_number",
    "direction",
    "direction_code",
    "axis",
    "start_edge",
    "end_edge",
    "movement_frame_rate_hz",
    "refreshes_per_movement_frame",
    "bar_width_fraction",
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
    "sweep_display",
    "inter_sweep_gray",
    "final_gray",
    "session_end",
)
