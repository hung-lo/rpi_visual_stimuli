from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Union

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
    width = system_config.screen.width_px
    height = system_config.screen.height_px
    source_rgb_bytes = width * height * 3 * config.source_frame_count
    converted_bytes = width * height * 2 * config.source_frame_count
    final_sweep_bytes = len(config.enabled_directions) * converted_bytes
    gray_bytes = width * height * 2
    preview_bytes = len(config.enabled_directions) * width * height * 3
    existing_partial_bytes = _directory_bytes(cache_root_for_config(system_config, config))
    return final_sweep_bytes + source_rgb_bytes + converted_bytes + gray_bytes + preview_bytes + existing_partial_bytes


def _directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _manifest_matches_config(
    manifest: dict[str, Any],
    system_config: SystemConfig,
    config: RetinotopyConfig,
) -> bool:
    return (
        manifest.get("protocol_cache_version") == config.cache_version
        and manifest.get("render_config") == build_cache_hash_payload(system_config, config)
        and manifest.get("number_of_source_frames") == config.source_frame_count
        and manifest.get("refreshes_per_source_frame") == config.refreshes_per_movement_frame
        and math.isclose(
            float(manifest.get("planned_playback_duration_sec", -1.0)),
            config.sweep_duration_sec,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        and isinstance(manifest.get("expected_files"), dict)
    )


def _gray_stem(seconds: float) -> str:
    return f"gray_{seconds:g}s".replace(".", "p")


def _build_cache_contents(
    cache_dir: Path,
    cache_hash: str,
    system_config: SystemConfig,
    config: RetinotopyConfig,
    *,
    convert_raw_fn: ConvertRawFn,
    compute_sha256: bool,
) -> RetinotopyCache:
    cache_dir.mkdir(parents=True, exist_ok=True)
    sweep_paths: dict[str, Path] = {}
    for direction in config.enabled_directions:
        raw_path = cache_dir / f"{direction}.raw"
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

    inter_sweep_frames = max(1, int(round(config.inter_sweep_gray_sec * system_config.screen.refresh_rate_hz)))
    inter_sweep_result = get_timed_gray_raw(
        cache_dir,
        system_config,
        duration_frames=inter_sweep_frames,
        stem=_gray_stem(config.inter_sweep_gray_sec),
        convert_raw_fn=convert_raw_fn,
        compute_sha256=compute_sha256,
    )
    preview_paths, contact_sheet_path = ensure_preview_assets(
        system_config,
        config,
        cache_dir=cache_dir,
    )

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
        "cache_hash": cache_hash,
        "created_utc": utc_iso_now(),
        "render_config": build_cache_hash_payload(system_config, config),
        "expected_files": expected_files,
        "number_of_source_frames": config.source_frame_count,
        "refreshes_per_source_frame": config.refreshes_per_movement_frame,
        "planned_playback_duration_sec": config.sweep_duration_sec,
    }
    manifest_path = write_manifest(cache_dir, manifest)
    validation = validate_cache(cache_dir, require_checksums=False)
    if not validation.valid or validation.manifest is None or not _manifest_matches_config(
        validation.manifest,
        system_config,
        config,
    ):
        reason = validation.reason or "manifest contents do not match the current retinotopy render configuration"
        raise RuntimeError(f"retinotopy cache validation failed: {reason}")
    return RetinotopyCache(
        cache_hash=cache_hash,
        cache_dir=cache_dir,
        manifest_path=manifest_path,
        sweep_paths=sweep_paths,
        inter_sweep_gray_path=inter_sweep_result.path,
        preview_paths=preview_paths,
        contact_sheet_path=contact_sheet_path,
    )


def _replace_cache_directory(cache_dir: Path, staging_dir: Path) -> None:
    backup_dir = cache_dir.parent / f"{cache_dir.name}.backup"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    try:
        if cache_dir.exists():
            os.replace(cache_dir, backup_dir)
        os.replace(staging_dir, cache_dir)
    except Exception:
        if backup_dir.exists() and not cache_dir.exists():
            os.replace(backup_dir, cache_dir)
        raise
    else:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)


def ensure_preview_assets(
    system_config: SystemConfig,
    config: RetinotopyConfig,
    *,
    cache_dir: Union[str, Path, None] = None,
) -> tuple[list[Path], Path]:
    cache_dir = Path(cache_dir) if cache_dir is not None else cache_root_for_config(system_config, config)
    preview_dir = cache_dir / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_paths: list[Path] = []
    for direction in config.enabled_directions:
        preview_path = preview_dir / f"{direction}.png"
        if not preview_path.exists():
            save_direction_preview(preview_path, system_config, config, direction=direction)
        preview_paths.append(preview_path)
    contact_sheet_path = preview_dir / "contact_sheet.png"
    if preview_paths and not contact_sheet_path.exists():
        save_contact_sheet(preview_paths, contact_sheet_path)
    return preview_paths, contact_sheet_path


def ensure_cache(
    system_config: SystemConfig,
    config: RetinotopyConfig,
    *,
    convert_raw_fn: ConvertRawFn,
    compute_sha256: bool = False,
) -> RetinotopyCache:
    cache_dir = cache_root_for_config(system_config, config)
    validation = validate_cache(cache_dir, require_checksums=False)
    if validation.valid and validation.manifest is not None and _manifest_matches_config(
        validation.manifest,
        system_config,
        config,
    ):
        return RetinotopyCache(
            cache_hash=cache_dir.name,
            cache_dir=cache_dir,
            manifest_path=cache_dir / "manifest.json",
            sweep_paths={direction: cache_dir / f"{direction}.raw" for direction in config.enabled_directions},
            inter_sweep_gray_path=cache_dir / f"{_gray_stem(config.inter_sweep_gray_sec)}.raw",
            preview_paths=[cache_dir / "preview" / f"{direction}.png" for direction in config.enabled_directions],
            contact_sheet_path=cache_dir / "preview" / "contact_sheet.png",
        )
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=f"{cache_dir.name}.tmp-",
            dir=cache_dir.parent,
        )
    )
    built_cache = None
    try:
        built_cache = _build_cache_contents(
            staging_dir,
            cache_dir.name,
            system_config,
            config,
            convert_raw_fn=convert_raw_fn,
            compute_sha256=compute_sha256,
        )
        _replace_cache_directory(cache_dir, staging_dir)
        return RetinotopyCache(
            cache_hash=cache_dir.name,
            cache_dir=cache_dir,
            manifest_path=cache_dir / "manifest.json",
            sweep_paths={key: cache_dir / path.relative_to(staging_dir) for key, path in built_cache.sweep_paths.items()},
            inter_sweep_gray_path=cache_dir / built_cache.inter_sweep_gray_path.relative_to(staging_dir),
            preview_paths=[cache_dir / path.relative_to(staging_dir) for path in built_cache.preview_paths],
            contact_sheet_path=cache_dir / built_cache.contact_sheet_path.relative_to(staging_dir),
        )
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)


def copy_manifest(cache: RetinotopyCache, session_manifest_path: Union[str, Path]) -> Path:
    return copy_manifest_to_session(cache.cache_dir, session_manifest_path)
