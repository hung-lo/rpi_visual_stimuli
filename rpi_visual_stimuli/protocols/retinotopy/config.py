from __future__ import annotations

from dataclasses import dataclass
import warnings

from ...core.config import SystemConfig


SWEEP_DURATION_SEC = 20.0
INTER_SWEEP_GRAY_SEC = 5.0
INITIAL_GRAY_SEC = 3.0
FINAL_GRAY_SEC = 3.0
MOVEMENT_FRAME_RATE_HZ = 15
BAR_WIDTH_FRACTION = 0.10
DEFAULT_DIRECTIONS = (
    "left_to_right",
    "top_to_bottom",
)
FOUR_DIRECTION_MODE = (
    "left_to_right",
    "right_to_left",
    "top_to_bottom",
    "bottom_to_top",
)
DEFAULT_REPEATS_PER_DIRECTION = 20
DEFAULT_SEQUENCE_ORDER_MODE = "fixed"
DEFAULT_CACHE_VERSION = "v1"


@dataclass(frozen=True)
class RetinotopyConfig:
    sweep_duration_sec: float
    inter_sweep_gray_sec: float
    initial_gray_sec: float
    final_gray_sec: float
    movement_frame_rate_hz: int
    bar_width_fraction: float
    enabled_directions: tuple[str, ...]
    repeats_per_direction: int
    sequence_order_mode: str
    sequence_seed: int | None
    cache_version: str
    source_frame_count: int
    refreshes_per_movement_frame: int

    def to_dict(self) -> dict[str, object]:
        return {
            "sweep_duration_sec": self.sweep_duration_sec,
            "inter_sweep_gray_sec": self.inter_sweep_gray_sec,
            "initial_gray_sec": self.initial_gray_sec,
            "final_gray_sec": self.final_gray_sec,
            "movement_frame_rate_hz": self.movement_frame_rate_hz,
            "bar_width_fraction": self.bar_width_fraction,
            "enabled_directions": list(self.enabled_directions),
            "repeats_per_direction": self.repeats_per_direction,
            "sequence_order_mode": self.sequence_order_mode,
            "sequence_seed": self.sequence_seed,
            "cache_version": self.cache_version,
            "source_frame_count": self.source_frame_count,
            "refreshes_per_movement_frame": self.refreshes_per_movement_frame,
        }


def build_config(
    system_config: SystemConfig,
    *,
    sweep_duration_sec: float = SWEEP_DURATION_SEC,
    inter_sweep_gray_sec: float = INTER_SWEEP_GRAY_SEC,
    initial_gray_sec: float = INITIAL_GRAY_SEC,
    final_gray_sec: float = FINAL_GRAY_SEC,
    movement_frame_rate_hz: int = MOVEMENT_FRAME_RATE_HZ,
    bar_width_fraction: float = BAR_WIDTH_FRACTION,
    enabled_directions: tuple[str, ...] = DEFAULT_DIRECTIONS,
    repeats_per_direction: int = DEFAULT_REPEATS_PER_DIRECTION,
    sequence_order_mode: str = DEFAULT_SEQUENCE_ORDER_MODE,
    sequence_seed: int | None = None,
    cache_version: str = DEFAULT_CACHE_VERSION,
) -> RetinotopyConfig:
    if sweep_duration_sec <= 0 or inter_sweep_gray_sec <= 0 or initial_gray_sec <= 0 or final_gray_sec <= 0:
        raise ValueError("all durations must be positive")
    if movement_frame_rate_hz <= 0:
        raise ValueError("movement_frame_rate_hz must be positive")
    if system_config.screen.refresh_rate_hz % movement_frame_rate_hz != 0:
        raise ValueError("refresh_rate_hz must be divisible by movement_frame_rate_hz")
    frame_target = sweep_duration_sec * movement_frame_rate_hz
    rounded_frames = int(round(frame_target))
    if rounded_frames <= 0:
        raise ValueError("sweep duration must produce at least one source frame")
    if abs(frame_target - rounded_frames) > 1e-6:
        warnings.warn(
            "sweep duration does not map exactly to an integer number of movement frames; rounding to the nearest frame",
            stacklevel=2,
        )
    if not 0 < bar_width_fraction < 0.5:
        raise ValueError("bar_width_fraction must be between 0 and 0.5")
    recognized = {"left_to_right", "right_to_left", "top_to_bottom", "bottom_to_top"}
    if not enabled_directions or len(set(enabled_directions)) != len(enabled_directions):
        raise ValueError("enabled_directions must be unique and non-empty")
    if any(direction not in recognized for direction in enabled_directions):
        raise ValueError("enabled_directions contains an unrecognized direction")
    if repeats_per_direction <= 0:
        raise ValueError("repeats_per_direction must be positive")
    if sequence_order_mode not in {"fixed", "shuffled"}:
        raise ValueError("sequence_order_mode must be 'fixed' or 'shuffled'")
    return RetinotopyConfig(
        sweep_duration_sec=float(sweep_duration_sec),
        inter_sweep_gray_sec=float(inter_sweep_gray_sec),
        initial_gray_sec=float(initial_gray_sec),
        final_gray_sec=float(final_gray_sec),
        movement_frame_rate_hz=int(movement_frame_rate_hz),
        bar_width_fraction=float(bar_width_fraction),
        enabled_directions=tuple(enabled_directions),
        repeats_per_direction=int(repeats_per_direction),
        sequence_order_mode=sequence_order_mode,
        sequence_seed=sequence_seed,
        cache_version=cache_version,
        source_frame_count=rounded_frames,
        refreshes_per_movement_frame=system_config.screen.refresh_rate_hz // movement_frame_rate_hz,
    )


def build_test_config(system_config: SystemConfig) -> RetinotopyConfig:
    return build_config(
        system_config,
        sweep_duration_sec=2.0,
        inter_sweep_gray_sec=1.0,
        initial_gray_sec=1.0,
        final_gray_sec=1.0,
        repeats_per_direction=1,
        movement_frame_rate_hz=MOVEMENT_FRAME_RATE_HZ,
    )
