from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import warnings

from ...core.config import SystemConfig


DEFAULT_ORIENTATIONS_DEG = (
    0.0,
    22.5,
    45.0,
    67.5,
    90.0,
    112.5,
    135.0,
    157.5,
)

DEFAULT_TRIALS_PER_ORIENTATION = 80
DEFAULT_STIM_DURATION_SEC = 0.5
DEFAULT_ITI_BASE_SEC = 0.7
DEFAULT_ITI_JITTER_MAX_SEC = 0.5
DEFAULT_INITIAL_GRAY_SEC = 3.0
DEFAULT_FINAL_GRAY_SEC = 3.0
DEFAULT_TEMPORAL_FREQUENCY_HZ = 2.0
DEFAULT_SPATIAL_FREQUENCY_CYCLES_PER_CM = 0.2
DEFAULT_CONTRAST = 1.0
DEFAULT_MEAN_LUMINANCE = 0.5
DEFAULT_STARTING_PHASE_DEG = 0.0
DEFAULT_GRATING_MODE = "fullscreen"
DEFAULT_CACHE_VERSION = "v1"


@dataclass(frozen=True)
class RectangularPatchGeometry:
    center_x_cm: float
    center_y_cm: float
    width_cm: float
    height_cm: float

    def to_dict(self) -> dict[str, float]:
        return {
            "center_x_cm": self.center_x_cm,
            "center_y_cm": self.center_y_cm,
            "width_cm": self.width_cm,
            "height_cm": self.height_cm,
        }


@dataclass(frozen=True)
class DriftingGratingConfig:
    orientations_deg: tuple[float, ...]
    trials_per_orientation: int
    stim_duration_sec: float
    iti_base_sec: float
    iti_jitter_max_sec: float
    temporal_frequency_hz: float
    spatial_frequency_cycles_per_cm: float
    contrast: float
    mean_luminance: float
    starting_phase_deg: float
    grating_mode: str
    rectangular_patch_geometry: Optional[RectangularPatchGeometry]
    initial_gray_sec: float
    final_gray_sec: float
    sequence_seed: Optional[int]
    cache_version: str
    stimulus_frame_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "orientations_deg": list(self.orientations_deg),
            "trials_per_orientation": self.trials_per_orientation,
            "stim_duration_sec": self.stim_duration_sec,
            "iti_base_sec": self.iti_base_sec,
            "iti_jitter_max_sec": self.iti_jitter_max_sec,
            "temporal_frequency_hz": self.temporal_frequency_hz,
            "spatial_frequency_cycles_per_cm": self.spatial_frequency_cycles_per_cm,
            "contrast": self.contrast,
            "mean_luminance": self.mean_luminance,
            "starting_phase_deg": self.starting_phase_deg,
            "grating_mode": self.grating_mode,
            "rectangular_patch_geometry": None if self.rectangular_patch_geometry is None else self.rectangular_patch_geometry.to_dict(),
            "initial_gray_sec": self.initial_gray_sec,
            "final_gray_sec": self.final_gray_sec,
            "sequence_seed": self.sequence_seed,
            "cache_version": self.cache_version,
            "stimulus_frame_count": self.stimulus_frame_count,
        }


def normalize_orientation_deg(value: float) -> float:
    normalized = float(value) % 180.0
    return 0.0 if abs(normalized - 180.0) < 1e-9 else normalized


def build_config(
    system_config: SystemConfig,
    *,
    orientations_deg: tuple[float, ...] = DEFAULT_ORIENTATIONS_DEG,
    trials_per_orientation: int = DEFAULT_TRIALS_PER_ORIENTATION,
    stim_duration_sec: float = DEFAULT_STIM_DURATION_SEC,
    iti_base_sec: float = DEFAULT_ITI_BASE_SEC,
    iti_jitter_max_sec: float = DEFAULT_ITI_JITTER_MAX_SEC,
    temporal_frequency_hz: float = DEFAULT_TEMPORAL_FREQUENCY_HZ,
    spatial_frequency_cycles_per_cm: float = DEFAULT_SPATIAL_FREQUENCY_CYCLES_PER_CM,
    contrast: float = DEFAULT_CONTRAST,
    mean_luminance: float = DEFAULT_MEAN_LUMINANCE,
    starting_phase_deg: float = DEFAULT_STARTING_PHASE_DEG,
    grating_mode: str = DEFAULT_GRATING_MODE,
    rectangular_patch_geometry: Optional[RectangularPatchGeometry] = None,
    initial_gray_sec: float = DEFAULT_INITIAL_GRAY_SEC,
    final_gray_sec: float = DEFAULT_FINAL_GRAY_SEC,
    sequence_seed: Optional[int] = None,
    cache_version: str = DEFAULT_CACHE_VERSION,
) -> DriftingGratingConfig:
    normalized_orientations = tuple(normalize_orientation_deg(value) for value in orientations_deg)
    if len(set(normalized_orientations)) != len(normalized_orientations):
        raise ValueError("orientations must be unique after normalization to [0, 180)")
    if not normalized_orientations:
        raise ValueError("at least one orientation is required")
    if trials_per_orientation <= 0:
        raise ValueError("trials_per_orientation must be positive")
    if stim_duration_sec <= 0:
        raise ValueError("stim_duration_sec must be positive")
    if iti_base_sec < 0 or iti_jitter_max_sec < 0:
        raise ValueError("ITI values must be non-negative")
    if temporal_frequency_hz <= 0 or spatial_frequency_cycles_per_cm <= 0:
        raise ValueError("temporal and spatial frequencies must be positive")
    if not 0 <= contrast <= 1:
        raise ValueError("contrast must be within [0, 1]")
    if not 0 < mean_luminance < 1:
        raise ValueError("mean_luminance must be within (0, 1)")
    minimum = mean_luminance * (1.0 - contrast)
    maximum = mean_luminance * (1.0 + contrast)
    if minimum < 0 or maximum > 1:
        raise ValueError("mean_luminance and contrast require clipping; choose a valid Michelson combination")
    if grating_mode not in {"fullscreen", "rectangular_patch"}:
        raise ValueError("grating_mode must be 'fullscreen' or 'rectangular_patch'")
    if grating_mode == "rectangular_patch":
        if rectangular_patch_geometry is None:
            raise ValueError("rectangular_patch_geometry is required for grating_mode='rectangular_patch'")
        if rectangular_patch_geometry.width_cm <= 0 or rectangular_patch_geometry.height_cm <= 0:
            raise ValueError("rectangular patch dimensions must be positive")
        half_width = rectangular_patch_geometry.width_cm / 2.0
        half_height = rectangular_patch_geometry.height_cm / 2.0
        if abs(rectangular_patch_geometry.center_x_cm) + half_width > system_config.screen.visible_width_cm / 2.0:
            raise ValueError("rectangular patch exceeds the visible screen width")
        if abs(rectangular_patch_geometry.center_y_cm) + half_height > system_config.screen.visible_height_cm / 2.0:
            raise ValueError("rectangular patch exceeds the visible screen height")
    if initial_gray_sec <= 0 or final_gray_sec <= 0:
        raise ValueError("initial and final gray durations must be positive")
    frame_target = stim_duration_sec * system_config.screen.refresh_rate_hz
    rounded_frames = int(round(frame_target))
    if rounded_frames <= 0:
        raise ValueError("stimulus duration must produce at least one source frame")
    if abs(frame_target - rounded_frames) > 1e-6:
        warnings.warn(
            "stimulus duration does not map exactly to an integer number of frames; rounding to the nearest frame",
            stacklevel=2,
        )
    return DriftingGratingConfig(
        orientations_deg=normalized_orientations,
        trials_per_orientation=trials_per_orientation,
        stim_duration_sec=float(stim_duration_sec),
        iti_base_sec=float(iti_base_sec),
        iti_jitter_max_sec=float(iti_jitter_max_sec),
        temporal_frequency_hz=float(temporal_frequency_hz),
        spatial_frequency_cycles_per_cm=float(spatial_frequency_cycles_per_cm),
        contrast=float(contrast),
        mean_luminance=float(mean_luminance),
        starting_phase_deg=float(starting_phase_deg),
        grating_mode=grating_mode,
        rectangular_patch_geometry=rectangular_patch_geometry,
        initial_gray_sec=float(initial_gray_sec),
        final_gray_sec=float(final_gray_sec),
        sequence_seed=sequence_seed,
        cache_version=cache_version,
        stimulus_frame_count=rounded_frames,
    )


def build_test_config(system_config: SystemConfig) -> DriftingGratingConfig:
    return build_config(
        system_config,
        trials_per_orientation=2,
        initial_gray_sec=1.0,
        final_gray_sec=1.0,
    )
