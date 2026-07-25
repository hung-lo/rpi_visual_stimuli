from __future__ import annotations

import random
import time

from ...core.config import SystemConfig
from .config import RetinotopyConfig
from .directions import get_direction


def _resolved_seed(seed: int | None) -> int:
    if seed is not None:
        return int(seed)
    return int(time.time_ns() % (2**32))


def build_trial_sequence(
    system_config: SystemConfig,
    config: RetinotopyConfig,
) -> tuple[list[dict[str, object]], int]:
    resolved_seed = _resolved_seed(config.sequence_seed)
    rng = random.Random(resolved_seed)
    direction_cycles: list[str] = []
    for _repeat in range(config.repeats_per_direction):
        if config.sequence_order_mode == "fixed":
            direction_cycles.extend(config.enabled_directions)
        else:
            directions = list(config.enabled_directions)
            rng.shuffle(directions)
            direction_cycles.extend(directions)
    trials: list[dict[str, object]] = []
    for trial_index, direction_name in enumerate(direction_cycles):
        definition = get_direction(direction_name)
        trials.append(
            {
                "trial_index": trial_index,
                "repeat_number": (trial_index // len(config.enabled_directions)) + 1,
                "direction": definition.direction,
                "direction_code": definition.direction_code,
                "axis": definition.axis,
                "start_edge": definition.start_edge,
                "end_edge": definition.end_edge,
                "planned_sweep_duration_sec": config.source_frame_count
                * config.refreshes_per_movement_frame
                / system_config.screen.refresh_rate_hz,
                "planned_gray_duration_sec": config.inter_sweep_gray_sec,
                "raw_key": definition.direction,
            }
        )
    return trials, resolved_seed
