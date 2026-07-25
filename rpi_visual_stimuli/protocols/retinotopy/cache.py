from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...core.config import SystemConfig
from ...core.gray_screen import get_timed_gray_raw
from ...core.raw_cache import copy_manifest_to_session, expected_file_entry, stable_hash, validate_cache, write_manifest
from ...core.raw_conversion import ConvertRawFn, convert_rgb_frames_to_raw
from ...core.timestamps import utc_iso_now
from .config import RetinotopyConfig
from .stimulus import iter_direction_frames, save_contact_sheet, save_direction_preview


@dataclass(frozen=True)
class RetinotopyCache:
    cache_hash: str
    cache_dir: Path
    manifest_path: Path
    sweep_paths: dict[str, Path]
    inter_sweep_gray_path: Path
    preview_paths: list[Path]
    contact_sheet_path: Path


def build_cache_hash_payload(system_config: SystemConfig, config: RetinotopyConfig) -> dict[str, Any]:
    return {
        "cache_version": config.cache_version,
        "screen_resolution": [system_config.screen.width_px, system_config.screen.height_px],
        "screen_refresh_rate_hz": system_config.screen.refresh_rate_hz,
        "screen_colormode": system_config.screen.colormode,
        "movement_frame_rate_hz": config.movement_frame_rate_hz,
        "sweep_duration_sec": config.sweep_duration_sec,
        "bar_width_fraction": config.bar_width_fraction,
        "background_gray_u8": system_config.screen.background_gray_u8,
        "black_value_u8": 0,
        "white_value_u8": 255,
        "photodiode": system_config.photodiode.to_dict(),
        "requested_directions": list(config.enabled_directions),
    }


def cache_root_for_config(system_config: SystemConfig, config: RetinotopyConfig) -> Path:
    return Path(system_config.cache_root) / "retinotopy" / stable_hash(
        build_cache_hash_payload(system_config, config)
    )


def approximate_loaded_bytes(system_config: SystemConfig, config: RetinotopyConfig) -> int:
    bytes_per_frame = system_config.screen.width_px * system_config.screen.height_px * 2
    return len(config.enabled_directions) * config.source_frame_count * bytes_per_frame


def approximate_build_peak_bytes(system_config: SystemConfig, config: RetinotopyConfig) -> int:
    source_rgb_bytes = system_config.screen.width_px * system_config.screen.height_px * 3 * config.source_frame_count
    converted_bytes = system_config.screen.width_px * system_config.screen.height_px * 2 * config.source_frame_count
    return source_rgb_bytes + converted_bytes


def _gray_stem(seconds: float) -> str:
    return f"gray_{seconds:g}s".replace(".", "p")


def ensure_cache(
    system_config: SystemConfig,
    config: RetinotopyConfig,
    *,
    convert_raw_fn: ConvertRawFn,
    compute_sha256: bool = False,
) -> RetinotopyCache:
    cache_dir = cache_root_for_config(system_config, config)
    preview_dir = cache_dir / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    sweep_paths: dict[str, Path] = {}
    preview_paths: list[Path] = []
    for direction in config.enabled_directions:
        raw_path = cache_dir / f"{direction}.raw"
        if not raw_path.exists() or raw_path.stat().st_size <= 0:
            convert_rgb_frames_to_raw(
                iter_direction_frames(system_config, config, direction=direction),
                frame_count=config.source_frame_count,
                width_px=system_config.screen.width_px,
                height_px=system_config.screen.height_px,
                refreshes_per_source_frame=config.refreshes_per_movement_frame,
                colormode=system_config.screen.colormode,
                final_path=raw_path,
                convert_raw_fn=convert_raw_fn,
                compute_sha256=compute_sha256,
            )
        sweep_paths[direction] = raw_path
        preview_path = preview_dir / f"{direction}.png"
        if not preview_path.exists():
            save_direction_preview(preview_path, system_config, config, direction=direction)
        preview_paths.append(preview_path)

    inter_sweep_frames = max(1, int(round(config.inter_sweep_gray_sec * system_config.screen.refresh_rate_hz)))
    inter_sweep_result = get_timed_gray_raw(
        cache_dir,
        system_config,
        duration_frames=inter_sweep_frames,
        stem=_gray_stem(config.inter_sweep_gray_sec),
        convert_raw_fn=convert_raw_fn,
        compute_sha256=compute_sha256,
    )
    contact_sheet_path = preview_dir / "contact_sheet.png"
    if preview_paths and not contact_sheet_path.exists():
        save_contact_sheet(preview_paths, contact_sheet_path)

    expected_files: dict[str, dict[str, Any]] = {}
    for path in sweep_paths.values():
        expected_files[str(path.relative_to(cache_dir))] = expected_file_entry(path)
    expected_files[str(inter_sweep_result.path.relative_to(cache_dir))] = expected_file_entry(inter_sweep_result.path)
    for path in preview_paths:
        expected_files[str(path.relative_to(cache_dir))] = expected_file_entry(path)
    if contact_sheet_path.exists():
        expected_files[str(contact_sheet_path.relative_to(cache_dir))] = expected_file_entry(contact_sheet_path)

    manifest = {
        "schema_version": 1,
        "protocol_cache_version": config.cache_version,
        "cache_hash": cache_dir.name,
        "created_utc": utc_iso_now(),
        "render_config": build_cache_hash_payload(system_config, config),
        "expected_files": expected_files,
        "number_of_source_frames": config.source_frame_count,
        "refreshes_per_source_frame": config.refreshes_per_movement_frame,
        "planned_playback_duration_sec": config.sweep_duration_sec,
    }
    manifest_path = write_manifest(cache_dir, manifest)
    validation = validate_cache(cache_dir, require_checksums=False)
    if not validation.valid:
        raise RuntimeError(f"retinotopy cache validation failed: {validation.reason}")
    return RetinotopyCache(
        cache_hash=cache_dir.name,
        cache_dir=cache_dir,
        manifest_path=manifest_path,
        sweep_paths=sweep_paths,
        inter_sweep_gray_path=inter_sweep_result.path,
        preview_paths=preview_paths,
        contact_sheet_path=contact_sheet_path,
    )


def copy_manifest(cache: RetinotopyCache, session_manifest_path: str | Path) -> Path:
    return copy_manifest_to_session(cache.cache_dir, session_manifest_path)
