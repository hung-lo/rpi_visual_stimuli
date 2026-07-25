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
from .config import DriftingGratingConfig
from .sequence import format_orientation_stem
from .stimulus import iter_stimulus_frames, save_contact_sheet, save_preview_png


@dataclass(frozen=True)
class DriftingGratingCache:
    cache_hash: str
    cache_dir: Path
    manifest_path: Path
    stimulus_paths: dict[str, Path]
    gray_paths: dict[int, Path]
    preview_paths: list[Path]
    contact_sheet_path: Path


def build_cache_hash_payload(system_config: SystemConfig, config: DriftingGratingConfig) -> dict[str, Any]:
    return {
        "cache_version": config.cache_version,
        "screen": {
            "width_px": system_config.screen.width_px,
            "height_px": system_config.screen.height_px,
            "refresh_rate_hz": system_config.screen.refresh_rate_hz,
            "colormode": system_config.screen.colormode,
            "background_gray_u8": system_config.screen.background_gray_u8,
            "visible_width_cm": system_config.screen.visible_width_cm,
            "visible_height_cm": system_config.screen.visible_height_cm,
        },
        "orientations_deg": list(config.orientations_deg),
        "temporal_frequency_hz": config.temporal_frequency_hz,
        "spatial_frequency_cycles_per_cm": config.spatial_frequency_cycles_per_cm,
        "stimulus_frame_count": config.stimulus_frame_count,
        "mean_luminance": config.mean_luminance,
        "contrast": config.contrast,
        "starting_phase_deg": config.starting_phase_deg,
        "grating_mode": config.grating_mode,
        "rectangular_patch_geometry": None if config.rectangular_patch_geometry is None else config.rectangular_patch_geometry.to_dict(),
        "photodiode": system_config.photodiode.to_dict(),
    }


def cache_root_for_config(system_config: SystemConfig, config: DriftingGratingConfig) -> Path:
    return Path(system_config.cache_root) / "drifting_gratings" / stable_hash(
        build_cache_hash_payload(system_config, config)
    )


def approximate_stimulus_bytes(system_config: SystemConfig, config: DriftingGratingConfig) -> int:
    bytes_per_frame = system_config.screen.width_px * system_config.screen.height_px * 2
    return len(config.orientations_deg) * config.stimulus_frame_count * bytes_per_frame


def _directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def estimate_peak_build_bytes(
    system_config: SystemConfig,
    config: DriftingGratingConfig,
    *,
    iti_frame_counts: set[int],
) -> int:
    width = system_config.screen.width_px
    height = system_config.screen.height_px
    stimulus_movie_rgb_bytes = width * height * 3 * config.stimulus_frame_count
    stimulus_movie_raw_bytes = width * height * 2 * config.stimulus_frame_count
    final_stimulus_bytes = approximate_stimulus_bytes(system_config, config)
    gray_frame_count = len(iti_frame_counts) + 3
    final_gray_bytes = gray_frame_count * width * height * 2
    preview_bytes = len(config.orientations_deg) * width * height * 3
    existing_partial_bytes = _directory_bytes(cache_root_for_config(system_config, config))
    return (
        final_stimulus_bytes
        + final_gray_bytes
        + preview_bytes
        + stimulus_movie_rgb_bytes
        + stimulus_movie_raw_bytes
        + existing_partial_bytes
    )


def _manifest_matches_config(
    manifest: dict[str, Any],
    system_config: SystemConfig,
    config: DriftingGratingConfig,
) -> bool:
    return (
        manifest.get("protocol_cache_version") == config.cache_version
        and manifest.get("render_config") == build_cache_hash_payload(system_config, config)
        and manifest.get("number_of_source_frames") == config.stimulus_frame_count
        and manifest.get("refreshes_per_source_frame") == 1
        and math.isclose(
            float(manifest.get("planned_playback_duration_sec", -1.0)),
            config.stimulus_frame_count / system_config.screen.refresh_rate_hz,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        and isinstance(manifest.get("expected_files"), dict)
    )


def _build_cache_contents(
    cache_dir: Path,
    cache_hash: str,
    system_config: SystemConfig,
    config: DriftingGratingConfig,
    *,
    iti_frame_counts: set[int],
    convert_raw_fn: ConvertRawFn,
    compute_sha256: bool,
) -> DriftingGratingCache:
    stimulus_dir = cache_dir / "stimulus"
    gray_dir = cache_dir / "gray"
    stimulus_dir.mkdir(parents=True, exist_ok=True)
    gray_dir.mkdir(parents=True, exist_ok=True)

    stimulus_paths: dict[str, Path] = {}
    gray_paths: dict[int, Path] = {}

    for orientation_id, angle in enumerate(config.orientations_deg, start=1):
        stem = format_orientation_stem(orientation_id, angle)
        raw_path = stimulus_dir / f"{stem}.raw"
        convert_rgb_frames_to_raw(
            iter_stimulus_frames(system_config, config, bar_orientation_deg=angle),
            frame_count=config.stimulus_frame_count,
            width_px=system_config.screen.width_px,
            height_px=system_config.screen.height_px,
            refreshes_per_source_frame=1,
            colormode=system_config.screen.colormode,
            final_path=raw_path,
            convert_raw_fn=convert_raw_fn,
            compute_sha256=compute_sha256,
        )
        stimulus_paths[stem] = raw_path

    for iti_frames in sorted(iti_frame_counts):
        result = get_timed_gray_raw(
            gray_dir,
            system_config,
            duration_frames=iti_frames,
            stem=f"gray_{iti_frames}frames",
            convert_raw_fn=convert_raw_fn,
            compute_sha256=compute_sha256,
        )
        gray_paths[iti_frames] = result.path

    preview_paths, contact_sheet_path = ensure_preview_assets(
        system_config,
        config,
        cache_dir=cache_dir,
    )

    expected_files: dict[str, dict[str, Any]] = {}
    for path in stimulus_paths.values():
        expected_files[str(path.relative_to(cache_dir))] = expected_file_entry(path)
    for path in gray_paths.values():
        expected_files[str(path.relative_to(cache_dir))] = expected_file_entry(path)
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
        "gray_frame_counts": sorted(iti_frame_counts),
        "expected_files": expected_files,
        "number_of_source_frames": config.stimulus_frame_count,
        "refreshes_per_source_frame": 1,
        "planned_playback_duration_sec": config.stimulus_frame_count / system_config.screen.refresh_rate_hz,
    }
    manifest_path = write_manifest(cache_dir, manifest)
    validation = validate_cache(cache_dir, require_checksums=False)
    if not validation.valid or validation.manifest is None or not _manifest_matches_config(
        validation.manifest,
        system_config,
        config,
    ):
        reason = validation.reason or "manifest contents do not match the current drifting-grating render configuration"
        raise RuntimeError(f"drifting-grating cache validation failed: {reason}")
    return DriftingGratingCache(
        cache_hash=cache_hash,
        cache_dir=cache_dir,
        manifest_path=manifest_path,
        stimulus_paths=stimulus_paths,
        gray_paths=gray_paths,
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
    config: DriftingGratingConfig,
    *,
    cache_dir: Union[str, Path, None] = None,
) -> tuple[list[Path], Path]:
    cache_dir = Path(cache_dir) if cache_dir is not None else cache_root_for_config(system_config, config)
    preview_dir = cache_dir / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_paths: list[Path] = []
    for orientation_id, angle in enumerate(config.orientations_deg, start=1):
        stem = format_orientation_stem(orientation_id, angle)
        preview_path = preview_dir / f"{stem}.png"
        if not preview_path.exists():
            save_preview_png(preview_path, system_config, config, bar_orientation_deg=angle)
        preview_paths.append(preview_path)
    contact_sheet_path = preview_dir / "contact_sheet.png"
    if preview_paths and not contact_sheet_path.exists():
        save_contact_sheet(preview_paths, contact_sheet_path)
    return preview_paths, contact_sheet_path


def ensure_cache(
    system_config: SystemConfig,
    config: DriftingGratingConfig,
    *,
    iti_frame_counts: set[int],
    convert_raw_fn: ConvertRawFn,
    compute_sha256: bool = False,
) -> DriftingGratingCache:
    cache_dir = cache_root_for_config(system_config, config)
    validation = validate_cache(cache_dir, require_checksums=False)
    if validation.valid and validation.manifest is not None and _manifest_matches_config(
        validation.manifest,
        system_config,
        config,
    ):
        stimulus_paths = {
            format_orientation_stem(orientation_id, angle): cache_dir / "stimulus" / f"{format_orientation_stem(orientation_id, angle)}.raw"
            for orientation_id, angle in enumerate(config.orientations_deg, start=1)
        }
        gray_paths = {
            iti_frames: cache_dir / "gray" / f"gray_{iti_frames}frames.raw"
            for iti_frames in sorted(iti_frame_counts)
        }
        preview_paths = [
            cache_dir / "preview" / f"{format_orientation_stem(orientation_id, angle)}.png"
            for orientation_id, angle in enumerate(config.orientations_deg, start=1)
        ]
        return DriftingGratingCache(
            cache_hash=cache_dir.name,
            cache_dir=cache_dir,
            manifest_path=cache_dir / "manifest.json",
            stimulus_paths=stimulus_paths,
            gray_paths=gray_paths,
            preview_paths=preview_paths,
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
            iti_frame_counts=iti_frame_counts,
            convert_raw_fn=convert_raw_fn,
            compute_sha256=compute_sha256,
        )
        _replace_cache_directory(cache_dir, staging_dir)
        return DriftingGratingCache(
            cache_hash=cache_dir.name,
            cache_dir=cache_dir,
            manifest_path=cache_dir / "manifest.json",
            stimulus_paths={key: cache_dir / path.relative_to(staging_dir) for key, path in built_cache.stimulus_paths.items()},
            gray_paths={key: cache_dir / path.relative_to(staging_dir) for key, path in built_cache.gray_paths.items()},
            preview_paths=[cache_dir / path.relative_to(staging_dir) for path in built_cache.preview_paths],
            contact_sheet_path=cache_dir / built_cache.contact_sheet_path.relative_to(staging_dir),
        )
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)


def copy_manifest(cache: DriftingGratingCache, session_manifest_path: Union[str, Path]) -> Path:
    return copy_manifest_to_session(cache.cache_dir, session_manifest_path)
