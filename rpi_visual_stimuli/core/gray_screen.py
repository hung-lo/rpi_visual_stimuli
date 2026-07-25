from __future__ import annotations

from pathlib import Path

import numpy as np

from .config import SystemConfig
from .photodiode import apply_photodiode_patch
from .raw_conversion import ConvertRawFn, RawConversionResult, convert_rgb_frames_to_raw


def build_gray_frame(system_config: SystemConfig) -> np.ndarray:
    frame = np.full(
        (
            system_config.screen.height_px,
            system_config.screen.width_px,
            3,
        ),
        system_config.screen.background_gray_u8,
        dtype=np.uint8,
    )
    return apply_photodiode_patch(
        frame,
        system_config.screen,
        system_config.photodiode,
        on=False,
    )


def get_timed_gray_raw(
    cache_dir: str | Path,
    system_config: SystemConfig,
    *,
    duration_frames: int,
    convert_raw_fn: ConvertRawFn,
    stem: str | None = None,
    compute_sha256: bool = False,
) -> RawConversionResult:
    if duration_frames <= 0:
        raise ValueError("duration_frames must be positive")
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    stem = stem or f"gray_{duration_frames}frames"
    raw_path = cache_path / f"{stem}.raw"
    if raw_path.exists() and raw_path.stat().st_size > 0:
        return RawConversionResult(
            path=raw_path,
            file_size_bytes=raw_path.stat().st_size,
            sha256=None,
            source_frame_count=1,
            refreshes_per_source_frame=duration_frames,
        )
    frame = build_gray_frame(system_config)
    return convert_rgb_frames_to_raw(
        [frame],
        frame_count=1,
        width_px=system_config.screen.width_px,
        height_px=system_config.screen.height_px,
        refreshes_per_source_frame=duration_frames,
        colormode=system_config.screen.colormode,
        final_path=raw_path,
        convert_raw_fn=convert_raw_fn,
        compute_sha256=compute_sha256,
    )


def get_baseline_gray_raw(
    cache_dir: str | Path,
    system_config: SystemConfig,
    *,
    convert_raw_fn: ConvertRawFn,
    compute_sha256: bool = False,
) -> RawConversionResult:
    return get_timed_gray_raw(
        cache_dir,
        system_config,
        duration_frames=1,
        convert_raw_fn=convert_raw_fn,
        stem="baseline_gray_1frame",
        compute_sha256=compute_sha256,
    )
