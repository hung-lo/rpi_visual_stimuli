from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional


@dataclass(frozen=True)
class ProtocolDurationSummary:
    trial_sequence_sec: float
    no_camera_protocol_sec: float
    camera_start_to_protocol_end_nominal_sec: Optional[float]

    def to_dict(self) -> dict[str, float | None]:
        return {
            "trial_sequence_sec": self.trial_sequence_sec,
            "no_camera_protocol_sec": self.no_camera_protocol_sec,
            "camera_start_to_protocol_end_nominal_sec": self.camera_start_to_protocol_end_nominal_sec,
        }


def format_duration(seconds: float) -> str:
    if seconds < 0:
        raise ValueError("seconds must be non-negative")
    total_seconds = int(round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} h {minutes} min {secs} sec"
    if minutes:
        return f"{minutes} min {secs} sec"
    return f"{secs} sec"


def summarize_protocol_duration(
    *,
    trial_epoch_durations_sec: Iterable[float],
    initial_gray_sec: float,
    final_gray_sec: float,
    camera_enabled: bool,
    baseline_minutes: Optional[float],
) -> ProtocolDurationSummary:
    trial_sequence_sec = sum(float(value) for value in trial_epoch_durations_sec)
    no_camera_protocol_sec = float(initial_gray_sec) + trial_sequence_sec + float(final_gray_sec)
    camera_duration = None
    if camera_enabled:
        requested_baseline_sec = float(baseline_minutes or 0.0) * 60.0
        camera_duration = requested_baseline_sec + trial_sequence_sec + float(final_gray_sec)
    return ProtocolDurationSummary(
        trial_sequence_sec=trial_sequence_sec,
        no_camera_protocol_sec=no_camera_protocol_sec,
        camera_start_to_protocol_end_nominal_sec=camera_duration,
    )


def estimated_local_completion(
    remaining_seconds: float,
    *,
    now: datetime | None = None,
) -> datetime:
    current = now or datetime.now().astimezone()
    return current + timedelta(seconds=max(0.0, remaining_seconds))
