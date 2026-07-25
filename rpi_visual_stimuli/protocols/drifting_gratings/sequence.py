from __future__ import annotations

import random
import time
from typing import Optional

from ...core.config import SystemConfig
from .config import DriftingGratingConfig, normalize_orientation_deg


def _resolved_seed(seed: Optional[int]) -> int:
    if seed is not None:
        return int(seed)
    return int(time.time_ns() % (2**32))


def drift_direction_deg(bar_orientation_deg: float) -> float:
    return (normalize_orientation_deg(bar_orientation_deg) - 90.0) % 360.0


def format_orientation_stem(orientation_id: int, bar_orientation_deg: float) -> str:
    label = f"{bar_orientation_deg:05.1f}".replace(".", "p")
    return f"orientation_{orientation_id:02d}_{label}deg"


def build_trial_sequence(
    system_config: SystemConfig,
    config: DriftingGratingConfig,
) -> tuple[list[dict[str, object]], int]:
    resolved_seed = _resolved_seed(config.sequence_seed)
    rng = random.Random(resolved_seed)
    base_trials: list[dict[str, object]] = []
    for orientation_id, angle in enumerate(config.orientations_deg, start=1):
        raw_key = format_orientation_stem(orientation_id, angle)
        for repeat_number in range(1, config.trials_per_orientation + 1):
            base_trials.append(
                {
                    "orientation_id": orientation_id,
                    "bar_orientation_deg": angle,
                    "drift_direction_deg": drift_direction_deg(angle),
                    "repeat_number": repeat_number,
                    "starting_phase_deg": config.starting_phase_deg,
                    "stim_frames": config.stimulus_frame_count,
                    "planned_stim_duration_sec": config.stimulus_frame_count / system_config.screen.refresh_rate_hz,
                    "grating_raw_key": raw_key,
                }
            )
    rng.shuffle(base_trials)
    trials: list[dict[str, object]] = []
    for trial_index, trial in enumerate(base_trials):
        jitter_requested_sec = rng.random() * config.iti_jitter_max_sec
        requested_iti_sec = config.iti_base_sec + jitter_requested_sec
        iti_frames = max(1, int(round(requested_iti_sec * system_config.screen.refresh_rate_hz)))
        planned_iti_sec = iti_frames / system_config.screen.refresh_rate_hz
        trials.append(
            {
                "trial_index": trial_index,
                **trial,
                "jitter_requested_sec": jitter_requested_sec,
                "iti_frames": iti_frames,
                "planned_iti_duration_sec": planned_iti_sec,
                "iti_raw_key": f"gray_{iti_frames}frames",
            }
        )
    return trials, resolved_seed


def trial_epoch_durations_sec(
    trials: list[dict[str, object]],
) -> list[float]:
    return [
        float(trial["planned_stim_duration_sec"]) + float(trial["planned_iti_duration_sec"])
        for trial in trials
    ]
