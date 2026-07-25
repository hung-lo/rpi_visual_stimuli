from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, Optional

from ...core import baseline as baseline_core
from ...core import camera as camera_core
from ...core.cli import build_common_parser, prompt_float, prompt_int, prompt_text, prompt_yes_no, resolve_camera_enabled
from ...core.config import SystemConfig, load_system_config
from ...core.event_logging import append_csv_row, write_csv
from ...core.gray_screen import get_baseline_gray_raw, get_timed_gray_raw
from ...core.metadata import get_git_commit, read_source_provenance, update_session_metadata
from ...core.preflight import check_disk_space_before_build, check_memory_before_loading
from ...core.progress import render_progress_line
from ...core.raw_cache import copy_manifest_to_session
from ...core.rpg_display import display_raw_with_timing, import_rpg_or_raise, load_raws, open_screen
from ...core.session import build_session_context, create_session_directories
from ...core.timestamps import utc_iso_now
from ..drifting_gratings.cache import approximate_stimulus_bytes, cache_root_for_config, ensure_cache
from ..drifting_gratings.config import (
    DEFAULT_CONTRAST,
    DEFAULT_FINAL_GRAY_SEC,
    DEFAULT_INITIAL_GRAY_SEC,
    DEFAULT_ITI_BASE_SEC,
    DEFAULT_ITI_JITTER_MAX_SEC,
    DEFAULT_MEAN_LUMINANCE,
    DEFAULT_SPATIAL_FREQUENCY_CYCLES_PER_CM,
    DEFAULT_TEMPORAL_FREQUENCY_HZ,
    DEFAULT_TRIALS_PER_ORIENTATION,
    build_config,
    build_test_config,
)
from ..drifting_gratings.events import EVENT_FIELDS
from ..drifting_gratings.sequence import build_trial_sequence


PROTOCOL_NAME = "drifting_gratings"
CAMERA_SETTLING_SEC = 2.0
RAW_CACHE_SCREEN_COMPATIBILITY_FALLBACK = True


def build_parser() -> argparse.ArgumentParser:
    return build_common_parser("Run the orientation drifting gratings protocol.")


def _prompt_protocol_config(system_config: SystemConfig, *, test_mode: bool) -> tuple[Any, int]:
    if test_mode:
        config = build_test_config(system_config)
        return config, config.trials_per_orientation
    trials_per_orientation = prompt_int("Trials per orientation", default=DEFAULT_TRIALS_PER_ORIENTATION)
    stim_duration_sec = prompt_float("Stimulus duration (sec)", default=0.5)
    iti_base_sec = prompt_float("ITI base duration (sec)", default=DEFAULT_ITI_BASE_SEC)
    iti_jitter_max_sec = prompt_float("ITI jitter max (sec)", default=DEFAULT_ITI_JITTER_MAX_SEC)
    temporal_frequency_hz = prompt_float("Temporal frequency (Hz)", default=DEFAULT_TEMPORAL_FREQUENCY_HZ)
    spatial_frequency_cpcm = prompt_float(
        "Spatial frequency (cycles/cm)",
        default=DEFAULT_SPATIAL_FREQUENCY_CYCLES_PER_CM,
    )
    contrast = prompt_float("Michelson contrast", default=DEFAULT_CONTRAST)
    mean_luminance = prompt_float("Mean luminance (0..1)", default=DEFAULT_MEAN_LUMINANCE)
    initial_gray_sec = prompt_float("Initial gray duration (sec)", default=DEFAULT_INITIAL_GRAY_SEC)
    final_gray_sec = prompt_float("Final gray duration (sec)", default=DEFAULT_FINAL_GRAY_SEC)
    config = build_config(
        system_config,
        trials_per_orientation=trials_per_orientation,
        stim_duration_sec=stim_duration_sec,
        iti_base_sec=iti_base_sec,
        iti_jitter_max_sec=iti_jitter_max_sec,
        temporal_frequency_hz=temporal_frequency_hz,
        spatial_frequency_cycles_per_cm=spatial_frequency_cpcm,
        contrast=contrast,
        mean_luminance=mean_luminance,
        initial_gray_sec=initial_gray_sec,
        final_gray_sec=final_gray_sec,
    )
    return config, trials_per_orientation


def _print_summary(
    system_config: SystemConfig,
    config,
    trials: list[dict[str, object]],
    camera_enabled: bool,
    baseline_minutes: Optional[float],
) -> None:
    print()
    print("Drifting gratings setup summary:")
    print(f"  Camera enabled: {camera_enabled}")
    if baseline_minutes is not None:
        print(f"  Camera baseline minutes: {baseline_minutes}")
    print(f"  Orientations: {len(config.orientations_deg)}")
    print(f"  Trials per orientation: {config.trials_per_orientation}")
    print(f"  Total trials: {len(trials)}")
    print(f"  Stimulus frames per trial: {config.stimulus_frame_count}")
    print(f"  Temporal frequency: {config.temporal_frequency_hz} Hz")
    print(f"  Spatial frequency: {config.spatial_frequency_cycles_per_cm} cycles/cm")
    print(f"  Mean luminance: {config.mean_luminance}")
    print(f"  Michelson contrast: {config.contrast}")
    print(
        "  Screen calibration: "
        f"{system_config.screen.visible_width_cm} cm x "
        f"{system_config.screen.visible_height_cm} cm"
    )
    print(f"  Cache root: {cache_root_for_config(system_config, config)}")


def _planned_sequence_rows(trials: list[dict[str, object]], cache_hash: str) -> list[dict[str, object]]:
    rows = []
    for trial in trials:
        rows.append(
            {
                "trial_index": trial["trial_index"],
                "orientation_id": trial["orientation_id"],
                "bar_orientation_deg": trial["bar_orientation_deg"],
                "drift_direction_deg": trial["drift_direction_deg"],
                "repeat_number": trial["repeat_number"],
                "starting_phase_deg": trial["starting_phase_deg"],
                "stim_frames": trial["stim_frames"],
                "planned_stim_duration_sec": trial["planned_stim_duration_sec"],
                "jitter_requested_sec": trial["jitter_requested_sec"],
                "iti_frames": trial["iti_frames"],
                "planned_iti_duration_sec": trial["planned_iti_duration_sec"],
                "grating_raw_key": trial["grating_raw_key"],
                "iti_raw_key": trial["iti_raw_key"],
                "cache_hash": cache_hash,
            }
        )
    return rows


def _initial_metadata(
    repo_root: Path,
    session,
    system_config: SystemConfig,
    config,
    *,
    camera_enabled: bool,
    baseline_minutes: Optional[float],
    resolved_seed: int,
    cache,
    preflight: dict[str, object],
) -> dict[str, object]:
    provenance = read_source_provenance(repo_root / "docs" / "SOURCE_PROVENANCE.md")
    return {
        "session_id": session.session_id,
        "protocol_name": PROTOCOL_NAME,
        "session_identifiers": session.to_dict(),
        "system_configuration": system_config.to_dict(),
        "protocol_configuration": config.to_dict(),
        "camera_state": {
            "enabled": camera_enabled,
            "requested_baseline_minutes": baseline_minutes,
            "stop_fetch_outcome": None,
            "manual_command_if_left_running": camera_core.manual_stop_fetch_command(repo_root),
        },
        "cache": {
            "cache_hash": cache.cache_hash,
            "cache_dir": str(cache.cache_dir),
            "manifest_path": str(cache.manifest_path),
            "stimulus_paths": {key: str(path) for key, path in cache.stimulus_paths.items()},
            "gray_paths": {str(key): str(path) for key, path in cache.gray_paths.items()},
        },
        "preflight_results": preflight,
        "sequence_seed": resolved_seed,
        "session_stage": "initialized",
        "session_completed": False,
        "failure_stage": None,
        "failure_summary": None,
        "start_utc": utc_iso_now(),
        "end_utc": None,
        "repository_commit": get_git_commit(repo_root),
        "source_provenance_commit": provenance.get("vstim_natural_commit"),
        "rpg_source_reference": provenance.get("rpg_package_version"),
        "raw_cache_screen_compatibility_fallback": RAW_CACHE_SCREEN_COMPATIBILITY_FALLBACK,
        "timing_note": (
            "The request timestamp is the Raspberry Pi software request immediately before "
            "screen.display_raw(). It is not measured monitor onset. The photodiode is the "
            "physical timing ground truth."
        ),
    }


def _playback_trials(
    screen,
    session,
    trials: list[dict[str, object]],
    cache,
    loaded_stimuli,
    loaded_gray,
    *,
    event_log_path: Path,
) -> None:
    start_monotonic = time.monotonic()
    total_trials = len(trials)
    for index, trial in enumerate(trials, start=1):
        stim_raw = loaded_stimuli[trial["grating_raw_key"]]
        stim_timing = display_raw_with_timing(screen, stim_raw)
        append_csv_row(
            event_log_path,
            {
                "event_type": "stim_on",
                "planned_duration_sec": trial["planned_stim_duration_sec"],
                "raw_path": str(cache.stimulus_paths[trial["grating_raw_key"]]),
                "trial_index": trial["trial_index"],
                "orientation_id": trial["orientation_id"],
                "bar_orientation_deg": trial["bar_orientation_deg"],
                "drift_direction_deg": trial["drift_direction_deg"],
                "repeat_number": trial["repeat_number"],
                "starting_phase_deg": trial["starting_phase_deg"],
                "stim_frames": trial["stim_frames"],
                "iti_frames": trial["iti_frames"],
                "jitter_requested_sec": trial["jitter_requested_sec"],
                "cache_hash": cache.cache_hash,
                **stim_timing.to_event_fields(),
            },
            EVENT_FIELDS,
        )
        iti_raw = loaded_gray[int(trial["iti_frames"])]
        iti_timing = display_raw_with_timing(screen, iti_raw)
        append_csv_row(
            event_log_path,
            {
                "event_type": "iti_on",
                "planned_duration_sec": trial["planned_iti_duration_sec"],
                "raw_path": str(cache.gray_paths[int(trial["iti_frames"])]),
                "trial_index": trial["trial_index"],
                "orientation_id": trial["orientation_id"],
                "bar_orientation_deg": trial["bar_orientation_deg"],
                "drift_direction_deg": trial["drift_direction_deg"],
                "repeat_number": trial["repeat_number"],
                "starting_phase_deg": trial["starting_phase_deg"],
                "stim_frames": trial["stim_frames"],
                "iti_frames": trial["iti_frames"],
                "jitter_requested_sec": trial["jitter_requested_sec"],
                "cache_hash": cache.cache_hash,
                **iti_timing.to_event_fields(),
            },
            EVENT_FIELDS,
        )
        elapsed = time.monotonic() - start_monotonic
        remaining = [float(item["planned_stim_duration_sec"]) + float(item["planned_iti_duration_sec"]) for item in trials[index:]]
        print(
            render_progress_line(
                current_index=index,
                total_count=total_trials,
                current_condition=f"orientation={trial['bar_orientation_deg']}",
                elapsed_seconds=elapsed,
                remaining_durations_seconds=remaining,
            )
        )


def run(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[3]
    system_config = load_system_config(args.system_config)
    mouse_id_raw = prompt_text("Mouse ID: ")
    session_notes = prompt_text("Session notes, optional: ")
    camera_enabled = False if args.preview_only or args.build_cache_only else resolve_camera_enabled(args)
    baseline_minutes = None
    if camera_enabled:
        baseline_minutes = prompt_float(
            "Camera baseline minutes",
            default=system_config.camera.default_prestim_baseline_minutes,
        )
    config, _ = _prompt_protocol_config(system_config, test_mode=args.test)
    trials, resolved_seed = build_trial_sequence(system_config, config)
    iti_frame_counts = {int(trial["iti_frames"]) for trial in trials}
    _print_summary(system_config, config, trials, camera_enabled, baseline_minutes)
    if not args.preview_only and not args.build_cache_only:
        if not prompt_yes_no("Start this session", default_yes=True):
            print("Session aborted before starting. No files were changed.")
            return 0

    estimated_disk_bytes = approximate_stimulus_bytes(system_config, config)
    if args.preview_only:
        print()
        print("Preview-only mode:")
        print(f"  Planned cache directory: {cache_root_for_config(system_config, config)}")
        print(f"  Estimated converted stimulus bytes: {estimated_disk_bytes}")
        print(f"  Planned trials: {len(trials)}")
        return 0

    if args.dry_run:
        print()
        print("Dry-run mode:")
        print(f"  Would build cache at: {cache_root_for_config(system_config, config)}")
        print(f"  Would run {len(trials)} drifting-grating trials")
        if camera_enabled:
            print(f"  Would start synchronous camera recording with baseline {baseline_minutes} minutes")
        return 0

    rpg = import_rpg_or_raise()
    cache = ensure_cache(
        system_config,
        config,
        iti_frame_counts=iti_frame_counts,
        convert_raw_fn=rpg.convert_raw,
    )
    if args.build_cache_only:
        print(f"Cache built: {cache.cache_dir}")
        print(f"Manifest: {cache.manifest_path}")
        return 0

    raw_files = list(cache.stimulus_paths.values()) + list(cache.gray_paths.values())
    memory_check = check_memory_before_loading(
        raw_files,
        overhead_factor=1.15,
        safety_margin_bytes=512 * 1024 * 1024,
        suggestion="Reduce orientations, shorten stimulus duration, or preload fewer raw files.",
    )
    check_disk_space_before_build(cache.cache_dir, required_bytes=estimated_disk_bytes, margin_bytes=1024 * 1024 * 1024)
    session = build_session_context(PROTOCOL_NAME, mouse_id_raw, session_notes, system_config.output_root)
    create_session_directories(session)
    planned_rows = _planned_sequence_rows(trials, cache.cache_hash)
    write_csv(
        session.planned_sequence_path,
        planned_rows,
        list(planned_rows[0].keys()) if planned_rows else ["trial_index"],
    )
    copy_manifest_to_session(cache.cache_dir, session.session_manifest_path)
    initial_metadata = _initial_metadata(
        repo_root,
        session,
        system_config,
        config,
        camera_enabled=camera_enabled,
        baseline_minutes=baseline_minutes,
        resolved_seed=resolved_seed,
        cache=cache,
        preflight={"memory": memory_check.to_dict()},
    )
    update_session_metadata(session.metadata_path, initial_metadata)

    loaded_screen = None
    camera_started = False
    baseline_monitor = None
    current_stage = "initializing"
    session_completed = False
    try:
        baseline_gray = get_baseline_gray_raw(
            cache.cache_dir / "gray",
            system_config,
            convert_raw_fn=rpg.convert_raw,
        )
        initial_gray_frames = max(1, int(round(config.initial_gray_sec * system_config.screen.refresh_rate_hz)))
        final_gray_frames = max(1, int(round(config.final_gray_sec * system_config.screen.refresh_rate_hz)))
        initial_gray = get_timed_gray_raw(
            cache.cache_dir / "gray",
            system_config,
            duration_frames=initial_gray_frames,
            stem=f"gray_{initial_gray_frames}frames",
            convert_raw_fn=rpg.convert_raw,
        )
        final_gray = get_timed_gray_raw(
            cache.cache_dir / "gray",
            system_config,
            duration_frames=final_gray_frames,
            stem=f"gray_{final_gray_frames}frames",
            convert_raw_fn=rpg.convert_raw,
        )
        with open_screen(system_config) as screen:
            loaded_screen = screen
            current_stage = "loading_raws"
            loaded_stimuli = load_raws(screen, cache.stimulus_paths)
            loaded_gray = load_raws(screen, {str(key): path for key, path in cache.gray_paths.items()})
            loaded_gray[int(initial_gray_frames)] = screen.load_raw(str(initial_gray.path))
            loaded_gray[int(final_gray_frames)] = screen.load_raw(str(final_gray.path))
            loaded_baseline = screen.load_raw(str(baseline_gray.path))
            current_stage = "displaying_prestim_gray"
            if camera_enabled:
                prestim_timing = display_raw_with_timing(screen, loaded_baseline)
                gray_start_monotonic = time.monotonic()
                append_csv_row(
                    session.event_log_path,
                    {
                        "event_type": "prestim_gray_on",
                        "planned_duration_sec": 0.0,
                        "raw_path": str(baseline_gray.path),
                        "cache_hash": cache.cache_hash,
                        **prestim_timing.to_event_fields(),
                    },
                    EVENT_FIELDS,
                )
                append_csv_row(session.event_log_path, {"event_type": "camera_start_requested", "cache_hash": cache.cache_hash}, EVENT_FIELDS)
                current_stage = "starting_camera"
                camera_core.start_camera(session.mouse_id, session.session_id)
                camera_started = True
                baseline_start_monotonic = time.monotonic()
                append_csv_row(session.event_log_path, {"event_type": "camera_start_returned", "cache_hash": cache.cache_hash}, EVENT_FIELDS)
                append_csv_row(session.event_log_path, {"event_type": "prestim_baseline_start", "cache_hash": cache.cache_hash}, EVENT_FIELDS)
                baseline_monitor = baseline_core.start_early_start_monitor(enabled=True)
                current_stage = "waiting_for_baseline"
                baseline_result = baseline_core.wait_for_prestimulus_gate(
                    requested_baseline_seconds=float(baseline_minutes or 0.0) * 60.0,
                    minimum_gray_seconds=config.initial_gray_sec,
                    baseline_start_monotonic=baseline_start_monotonic,
                    gray_start_monotonic=gray_start_monotonic,
                    override_event=baseline_monitor.override_event,
                )
                append_csv_row(
                    session.event_log_path,
                    {
                        "event_type": "prestim_baseline_end",
                        "cache_hash": cache.cache_hash,
                        "notes": json.dumps(baseline_result.to_dict(), sort_keys=True),
                    },
                    EVENT_FIELDS,
                )
            else:
                prestim_timing = display_raw_with_timing(screen, loaded_gray[int(initial_gray_frames)])
                append_csv_row(
                    session.event_log_path,
                    {
                        "event_type": "prestim_gray_on",
                        "planned_duration_sec": config.initial_gray_sec,
                        "raw_path": str(initial_gray.path),
                        "cache_hash": cache.cache_hash,
                        **prestim_timing.to_event_fields(),
                    },
                    EVENT_FIELDS,
                )
            append_csv_row(session.event_log_path, {"event_type": "raw_cache_ready", "cache_hash": cache.cache_hash}, EVENT_FIELDS)
            append_csv_row(session.event_log_path, {"event_type": "session_start", "cache_hash": cache.cache_hash}, EVENT_FIELDS)
            current_stage = "playback"
            _playback_trials(
                screen,
                session,
                trials,
                cache,
                loaded_stimuli,
                {int(key): value for key, value in loaded_gray.items()},
                event_log_path=session.event_log_path,
            )
            current_stage = "final_gray"
            final_timing = display_raw_with_timing(screen, loaded_gray[int(final_gray_frames)])
            append_csv_row(
                session.event_log_path,
                {
                    "event_type": "final_gray",
                    "planned_duration_sec": config.final_gray_sec,
                    "raw_path": str(final_gray.path),
                    "cache_hash": cache.cache_hash,
                    **final_timing.to_event_fields(),
                },
                EVENT_FIELDS,
            )
            append_csv_row(session.event_log_path, {"event_type": "session_end", "cache_hash": cache.cache_hash}, EVENT_FIELDS)
            session_completed = True
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        if session.event_log_path.exists():
            append_csv_row(
                session.event_log_path,
                {"event_type": "session_end", "notes": f"{type(exc).__name__}: {exc}"},
                EVENT_FIELDS,
            )
        update_session_metadata(
            session.metadata_path,
            session_completed=False,
            failure_stage=current_stage,
            failure_summary=f"{type(exc).__name__}: {exc}",
            session_stage=current_stage,
            end_utc=utc_iso_now(),
        )
        raise
    finally:
        baseline_core.stop_early_start_monitor(baseline_monitor)
        current_stage = "camera_cleanup"
        camera_cleanup = None
        if camera_started:
            if prompt_yes_no("Stop camera recording and fetch files now?", default_yes=False):
                time.sleep(CAMERA_SETTLING_SEC)
                camera_cleanup = camera_core.stop_and_fetch_camera()
            else:
                print("Camera left running. Manual cleanup:")
                print(camera_core.manual_stop_fetch_command(repo_root))
        update_session_metadata(
            session.metadata_path,
            session_completed=session_completed,
            session_stage="complete" if session_completed else current_stage,
            failure_stage=None if session_completed else current_stage,
            end_utc=utc_iso_now(),
            camera_state={
                **initial_metadata["camera_state"],
                "enabled": camera_enabled,
                "stop_fetch_outcome": None
                if camera_cleanup is None
                else {
                    "returncode": camera_cleanup.returncode,
                    "stdout": camera_cleanup.stdout,
                    "stderr": camera_cleanup.stderr,
                },
            },
        )
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
