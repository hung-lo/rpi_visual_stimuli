from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import sys
import time
from typing import Any, Optional

from ...core import baseline as baseline_core
from ...core import camera as camera_core
from ...core.duration import (
    ProtocolDurationSummary,
    estimated_local_completion,
    format_duration,
    summarize_protocol_duration,
)
from ...core.cli import (
    build_common_parser,
    prompt_choice,
    prompt_float,
    prompt_int,
    prompt_text,
    prompt_yes_no,
    resolve_camera_enabled,
)
from ...core.config import SystemConfig, load_system_config
from ...core.event_logging import append_csv_row, write_csv
from ...core.gpio import setup_gpio
from ...core.gray_screen import get_baseline_gray_raw, get_timed_gray_raw
from ...core.metadata import (
    collect_runtime_environment,
    get_git_commit,
    read_source_provenance,
    update_session_metadata,
)
from ...core.preflight import (
    check_disk_space_before_build,
    check_memory_before_loading,
    require_expected_mount,
)
from ...core.progress import ProgressReporter
from ...core.raw_cache import copy_manifest_to_session
from ...core.rpg_display import display_raw_with_timing, import_rpg_or_raise, load_raws, open_screen
from ...core.session import build_session_context, create_session_directories
from ...core.timestamps import utc_iso_now
from ..drifting_gratings.cache import (
    approximate_stimulus_bytes,
    cache_root_for_config,
    ensure_cache,
    ensure_preview_assets,
    estimate_peak_build_bytes,
)
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
from ..drifting_gratings.sequence import build_trial_sequence, trial_epoch_durations_sec


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
    duration_summary: ProtocolDurationSummary,
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
    print(
        "  Exact planned trial-sequence duration: "
        f"{_format_duration_with_seconds(duration_summary.trial_sequence_sec)}"
    )
    if camera_enabled:
        print(
            "  Visual protocol duration without camera baseline: "
            f"{_format_duration_with_seconds(duration_summary.no_camera_protocol_sec)}"
        )
        print(
            "  Nominal camera-start-to-protocol-end duration: "
            f"{_format_duration_with_seconds(duration_summary.camera_start_to_protocol_end_nominal_sec or 0.0)}"
        )
        print(
            "  Timing note: camera cleanup and file transfer are excluded; "
            "raw loading can extend the baseline."
        )
    else:
        print(
            "  Exact planned visual protocol duration: "
            f"{_format_duration_with_seconds(duration_summary.no_camera_protocol_sec)}"
        )


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


def _write_preview_plan(cache_dir: Path, rows: list[dict[str, object]]) -> Path:
    preview_dir = cache_dir / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_plan_path = preview_dir / "planned_sequence_preview.csv"
    fieldnames = list(rows[0].keys()) if rows else ["trial_index"]
    write_csv(preview_plan_path, rows, fieldnames)
    return preview_plan_path


def _format_command(command: tuple[str, ...]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _format_duration_with_seconds(seconds: float) -> str:
    return f"{format_duration(seconds)} ({seconds:.1f} sec)"


def _remaining_suffix_sums(epoch_durations_sec: list[float]) -> list[float]:
    remaining_after_index = [0.0] * (len(epoch_durations_sec) + 1)
    for index in range(len(epoch_durations_sec) - 1, -1, -1):
        remaining_after_index[index] = remaining_after_index[index + 1] + epoch_durations_sec[index]
    return remaining_after_index


def _print_playback_start_message(
    *,
    trial_sequence_sec: float,
    final_gray_sec: float,
) -> None:
    remaining_seconds = trial_sequence_sec + final_gray_sec
    completion = estimated_local_completion(remaining_seconds)
    print("Starting drifting-grating stimulation.")
    print(f"  Planned stimulation + ITI duration: {format_duration(trial_sequence_sec)}")
    print(f"  Final gray: {format_duration(final_gray_sec)}")
    print(f"  Expected time until protocol completion: {format_duration(remaining_seconds)}")
    print(f"  Estimated completion: {completion.strftime('%Y-%m-%d %H:%M:%S %Z')}")


def _resolve_preview_cache_dir(repo_root: Path, cache_dir: Path) -> tuple[Path, bool]:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir, False
    except OSError:
        fallback_dir = repo_root / ".preview_cache" / PROTOCOL_NAME / cache_dir.name
        fallback_dir.mkdir(parents=True, exist_ok=True)
        return fallback_dir, True


def _resolve_camera_preflight(
    system_config: SystemConfig,
    camera_enabled: bool,
) -> tuple[bool, Optional[camera_core.CameraCommandResult], Optional[str]]:
    if not camera_enabled:
        return False, None, None
    result = camera_core.preflight_camera(system_config.camera, system_config.output_root)
    if result.returncode == 0:
        return True, result, None
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode == 3:
        choice = prompt_choice(
            "Camera acquisition already appears to be running on Box 152. Choose abort, stop, or no-camera",
            choices=("abort", "stop", "no-camera"),
            default="abort",
        )
        if choice == "abort":
            raise RuntimeError("Camera preflight aborted because Box 152 is already recording.")
        if choice == "no-camera":
            return False, result, "continued_without_camera_after_existing_acquisition"
        camera_core.stop_camera(system_config.camera, system_config.output_root)
        retry = camera_core.preflight_camera(system_config.camera, system_config.output_root)
        if retry.returncode != 0:
            raise RuntimeError(retry.stderr or retry.stdout or "Camera preflight still failed after stopping the existing acquisition.")
        return True, retry, "stopped_existing_acquisition_before_start"
    if prompt_yes_no("Camera preflight failed. Continue without camera?", default_yes=False):
        return False, result, "continued_without_camera_after_preflight_failure"
    raise RuntimeError("Camera preflight failed.")


def _initial_metadata(
    repo_root: Path,
    system_config_path: Path,
    session,
    system_config: SystemConfig,
    config,
    *,
    camera_requested: bool,
    camera_enabled: bool,
    baseline_minutes: Optional[float],
    resolved_seed: int,
    cache,
    preflight: dict[str, object],
    runtime_environment: dict[str, object],
    duration_summary: ProtocolDurationSummary,
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
            "requested_enabled": camera_requested,
            "preflight_passed": bool(camera_enabled and preflight.get("camera_preflight", {}).get("returncode") == 0),
            "start_requested_utc": None,
            "start_returned_utc": None,
            "start_verified": False,
            "remote_host": system_config.camera.host,
            "remote_session_path": f"{system_config.camera.remote_video_root.rstrip('/')}/{session.session_id}",
            "local_video_path": str(session.video_directory),
            "requested_baseline_minutes": baseline_minutes,
            "stop_requested": False,
            "stopped": False,
            "settle_seconds": None,
            "fetch_requested": False,
            "fetched": False,
            "convert_requested": False,
            "conversion_attempted": False,
            "conversion_succeeded": False,
            "cleanup_error": None,
            "left_running": False,
            "manual_command_if_left_running": camera_core.manual_stop_fetch_command(repo_root),
        },
        "prestim": {
            "requested_camera_baseline_sec": None if baseline_minutes is None else float(baseline_minutes) * 60.0,
            "actual_camera_baseline_sec": None,
            "minimum_gray_sec": config.initial_gray_sec,
            "actual_gray_sec": None,
            "override_used": False,
            "end_reason": None,
            "raw_loading_duration_sec": None,
            "gray_retention_validated": False,
        },
        "gpio": {
            "enabled": system_config.gpio.enabled,
            "ttl_pin_bcm": system_config.gpio.ttl_pin_bcm,
            "pulse_sec": system_config.gpio.pulse_sec,
            "pulse_semantics": "one pulse immediately before each grating stimulus request",
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
        "runtime_environment": {
            **runtime_environment,
            "system_config_path": str(system_config_path.resolve()),
        },
        "planned_duration": {
            **duration_summary.to_dict(),
            "camera_duration_note": (
                "Nominal value excludes camera cleanup, transfer, conversion, and baseline "
                "extension caused by raw loading."
            ),
        },
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
    progress_reporter: ProgressReporter,
    playback_start_monotonic: float,
    remaining_after_index: list[float],
    final_gray_sec: float,
    gpio_controller=None,
) -> None:
    for index, trial in enumerate(trials, start=1):
        stim_raw = loaded_stimuli[trial["grating_raw_key"]]
        if gpio_controller is not None:
            gpio_controller.pulse()
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
        progress_reporter.update(
            current_index=index,
            current_condition=f"orientation={trial['bar_orientation_deg']}",
            elapsed_seconds=time.monotonic() - playback_start_monotonic,
            remaining_seconds=remaining_after_index[index] + final_gray_sec,
        )


def _serialize_camera_command_result(result: Optional[camera_core.CameraCommandResult]) -> Optional[dict[str, object]]:
    if result is None:
        return None
    return {
        "command": list(result.command),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _serialize_camera_cleanup_result(result: Optional[camera_core.CameraCleanupResult]) -> Optional[dict[str, object]]:
    if result is None:
        return None
    return {
        "stop_requested": result.stop_result is not None,
        "stop_succeeded": bool(result.stop_result and result.stop_result.succeeded),
        "settle_seconds": result.settle_seconds,
        "fetch_requested": result.fetch_result is not None,
        "fetch_succeeded": bool(result.fetch_result and result.fetch_result.succeeded),
        "convert_requested": result.convert_result is not None,
        "conversion_attempted": result.convert_result is not None,
        "conversion_succeeded": bool(result.convert_result and result.convert_result.succeeded),
        "left_running": result.left_running,
        "cleanup_error": result.cleanup_error,
        "stop_result": _serialize_camera_command_result(result.stop_result),
        "fetch_result": _serialize_camera_command_result(result.fetch_result),
        "convert_result": _serialize_camera_command_result(result.convert_result),
    }


def run(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[3]
    system_config_path = Path(args.system_config)
    system_config = load_system_config(system_config_path)
    mouse_id_raw = prompt_text("Mouse ID: ")
    session_notes = prompt_text("Session notes, optional: ")
    camera_requested = False if args.preview_only or args.build_cache_only else resolve_camera_enabled(args)
    camera_enabled = camera_requested
    baseline_minutes = None
    if camera_enabled:
        baseline_minutes = prompt_float(
            "Camera baseline minutes",
            default=system_config.camera.default_prestim_baseline_minutes,
        )
    config, _ = _prompt_protocol_config(system_config, test_mode=args.test)
    trials, resolved_seed = build_trial_sequence(system_config, config)
    trial_epoch_seconds = trial_epoch_durations_sec(trials)
    duration_summary = summarize_protocol_duration(
        trial_epoch_durations_sec=trial_epoch_seconds,
        initial_gray_sec=config.initial_gray_sec,
        final_gray_sec=config.final_gray_sec,
        camera_enabled=camera_enabled,
        baseline_minutes=baseline_minutes,
    )
    iti_frame_counts = {int(trial["iti_frames"]) for trial in trials}
    planned_cache_dir = cache_root_for_config(system_config, config)
    planned_rows = _planned_sequence_rows(trials, planned_cache_dir.name)
    _print_summary(system_config, config, trials, camera_enabled, baseline_minutes, duration_summary)

    estimated_disk_bytes = approximate_stimulus_bytes(system_config, config)
    if args.preview_only:
        preview_cache_dir, using_fallback = _resolve_preview_cache_dir(repo_root, planned_cache_dir)
        preview_paths, contact_sheet_path = ensure_preview_assets(
            system_config,
            config,
            cache_dir=preview_cache_dir,
        )
        preview_plan_path = _write_preview_plan(preview_cache_dir, planned_rows)
        print()
        print("Preview-only mode:")
        print(f"  Planned cache directory: {planned_cache_dir}")
        if using_fallback:
            print(f"  Preview cache directory: {preview_cache_dir}")
        print(f"  Preview plan: {preview_plan_path}")
        print(f"  Contact sheet: {contact_sheet_path}")
        print(f"  Preview images: {len(preview_paths)}")
        print(f"  Estimated converted stimulus bytes: {estimated_disk_bytes}")
        print(f"  Planned trials: {len(trials)}")
        return 0

    if args.dry_run:
        print()
        print("Dry-run mode:")
        print(f"  Would build cache at: {planned_cache_dir}")
        print(f"  Would run {len(trials)} drifting-grating trials")
        if camera_enabled:
            preview_session = build_session_context(
                PROTOCOL_NAME,
                mouse_id_raw,
                session_notes,
                system_config.output_root,
            )
            preflight_command = camera_core.preflight_camera(
                system_config.camera,
                system_config.output_root,
                dry_run=True,
            )
            start_command = camera_core.start_camera(
                preview_session.mouse_id,
                preview_session.session_id,
                system_config.camera,
                system_config.output_root,
                dry_run=True,
            )
            stop_command = camera_core.stop_camera(
                system_config.camera,
                system_config.output_root,
                dry_run=True,
                ignore_errors=True,
            )
            fetch_command = camera_core.fetch_camera(
                system_config.camera,
                system_config.output_root,
                dry_run=True,
                skip_conversion=True,
            )
            convert_command = camera_core.convert_camera(
                system_config.camera,
                system_config.output_root,
                dry_run=True,
            )
            print(f"  Would start synchronous camera recording with baseline {baseline_minutes} minutes")
            print("  Camera command order:")
            print(f"    preflight: {_format_command(preflight_command.command)}")
            print(f"    start: {_format_command(start_command.command)}")
            print("    verify: performed inside remote_camera_control.py start after launch")
            print(f"    stop: {_format_command(stop_command.command)}")
            print(f"    wait: {CAMERA_SETTLING_SEC:.1f} sec")
            print(f"    fetch: {_format_command(fetch_command.command)}")
            print(f"    convert: {_format_command(convert_command.command)}")
        return 0

    camera_preflight_result = None
    camera_preflight_note = None
    if camera_enabled and not args.build_cache_only:
        camera_enabled, camera_preflight_result, camera_preflight_note = _resolve_camera_preflight(
            system_config,
            camera_enabled,
        )
        if camera_preflight_note:
            print(f"Camera mode update: {camera_preflight_note}")
            if not camera_enabled:
                baseline_minutes = None
        duration_summary = summarize_protocol_duration(
            trial_epoch_durations_sec=trial_epoch_seconds,
            initial_gray_sec=config.initial_gray_sec,
            final_gray_sec=config.final_gray_sec,
            camera_enabled=camera_enabled,
            baseline_minutes=baseline_minutes,
        )
        _print_summary(system_config, config, trials, camera_enabled, baseline_minutes, duration_summary)

    if not args.build_cache_only:
        if not prompt_yes_no("Start this session", default_yes=True):
            print("Session aborted before starting. No files were changed.")
            return 0

    rpg = import_rpg_or_raise()
    peak_build_bytes = estimate_peak_build_bytes(
        system_config,
        config,
        iti_frame_counts=iti_frame_counts,
    )
    require_expected_mount(system_config.output_root)
    check_disk_space_before_build(
        cache_root_for_config(system_config, config),
        required_bytes=peak_build_bytes,
        margin_bytes=1024 * 1024 * 1024,
    )
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
        system_config_path,
        session,
        system_config,
        config,
        camera_requested=camera_requested,
        camera_enabled=camera_enabled,
        baseline_minutes=baseline_minutes,
        resolved_seed=resolved_seed,
        cache=cache,
        preflight={
            "memory": memory_check.to_dict(),
            "disk_peak_required_bytes": peak_build_bytes,
            "camera_preflight": _serialize_camera_command_result(camera_preflight_result),
            "camera_preflight_note": camera_preflight_note,
        },
        runtime_environment=collect_runtime_environment(
            repo_root,
            system_config_path,
            rpg_module=rpg,
        ),
        duration_summary=duration_summary,
    )
    update_session_metadata(session.metadata_path, initial_metadata)

    camera_started = False
    baseline_monitor = None
    current_stage = "initializing"
    session_completed = False
    failure_stage = None
    failure_summary = None
    cleanup_stage = None
    cleanup_error = None
    keyboard_interrupt = False
    stored_exception = None
    session_end_logged = False
    camera_cleanup_result = None
    camera_start_requested_utc = None
    camera_start_returned_utc = None
    camera_start_verified = False
    baseline_result = None
    raw_loading_duration_sec = None
    camera_left_running = False
    gpio_controller = None
    progress_reporter = None
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
            loaded_stimuli = {}
            loaded_gray = {}
            gpio_controller = setup_gpio(system_config.gpio)
            if gpio_controller is not None:
                gpio_controller.drive_low()
            if camera_enabled:
                current_stage = "loading_baseline_gray"
                loaded_baseline = screen.load_raw(str(baseline_gray.path))
                current_stage = "displaying_prestim_gray"
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
                camera_start_requested_utc = utc_iso_now()
                append_csv_row(
                    session.event_log_path,
                    {
                        "event_type": "camera_start_requested",
                        "cache_hash": cache.cache_hash,
                        "notes": camera_start_requested_utc,
                    },
                    EVENT_FIELDS,
                )
                current_stage = "starting_camera"
                camera_core.start_camera(
                    session.mouse_id,
                    session.session_id,
                    system_config.camera,
                    system_config.output_root,
                )
                camera_started = True
                camera_start_verified = True
                camera_start_returned_utc = utc_iso_now()
                baseline_start_monotonic = time.monotonic()
                append_csv_row(
                    session.event_log_path,
                    {
                        "event_type": "camera_start_returned",
                        "cache_hash": cache.cache_hash,
                        "notes": camera_start_returned_utc,
                    },
                    EVENT_FIELDS,
                )
                append_csv_row(
                    session.event_log_path,
                    {"event_type": "prestim_baseline_start", "cache_hash": cache.cache_hash},
                    EVENT_FIELDS,
                )
                baseline_monitor = baseline_core.start_early_start_monitor(enabled=True)
                current_stage = "loading_raws"
                raw_load_start = time.monotonic()
                loaded_stimuli = load_raws(screen, cache.stimulus_paths)
                loaded_gray = {key: screen.load_raw(str(path)) for key, path in cache.gray_paths.items()}
                loaded_gray[int(final_gray_frames)] = screen.load_raw(str(final_gray.path))
                raw_loading_duration_sec = time.monotonic() - raw_load_start
                append_csv_row(
                    session.event_log_path,
                    {
                        "event_type": "raw_cache_ready",
                        "cache_hash": cache.cache_hash,
                        "notes": f"raw_loading_duration_sec={raw_loading_duration_sec:.6f}",
                    },
                    EVENT_FIELDS,
                )
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
                current_stage = "loading_raws"
                raw_load_start = time.monotonic()
                loaded_stimuli = load_raws(screen, cache.stimulus_paths)
                loaded_gray = {key: screen.load_raw(str(path)) for key, path in cache.gray_paths.items()}
                loaded_gray[int(initial_gray_frames)] = screen.load_raw(str(initial_gray.path))
                loaded_gray[int(final_gray_frames)] = screen.load_raw(str(final_gray.path))
                raw_loading_duration_sec = time.monotonic() - raw_load_start
                append_csv_row(
                    session.event_log_path,
                    {
                        "event_type": "raw_cache_ready",
                        "cache_hash": cache.cache_hash,
                        "notes": f"raw_loading_duration_sec={raw_loading_duration_sec:.6f}",
                    },
                    EVENT_FIELDS,
                )
                current_stage = "displaying_prestim_gray"
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
                baseline_result = baseline_core.BaselineResult(
                    requested_baseline_seconds=0.0,
                    actual_camera_baseline_seconds=0.0,
                    minimum_gray_seconds=config.initial_gray_sec,
                    actual_gray_seconds=config.initial_gray_sec,
                    override_used=False,
                    end_reason="timer_elapsed",
                    baseline_remaining_at_gate_entry=0.0,
                    gray_remaining_at_gate_entry=0.0,
                    waited_for_minimum_gray_after_override=False,
                )
            _print_playback_start_message(
                trial_sequence_sec=duration_summary.trial_sequence_sec,
                final_gray_sec=config.final_gray_sec,
            )
            progress_reporter = ProgressReporter(total_count=len(trials))
            playback_start_monotonic = time.monotonic()
            progress_reporter.update(
                current_index=0,
                current_condition="waiting_for_first_trial",
                elapsed_seconds=0.0,
                remaining_seconds=duration_summary.trial_sequence_sec + config.final_gray_sec,
            )
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
                progress_reporter=progress_reporter,
                playback_start_monotonic=playback_start_monotonic,
                remaining_after_index=_remaining_suffix_sums(trial_epoch_seconds),
                final_gray_sec=config.final_gray_sec,
                gpio_controller=gpio_controller,
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
            if progress_reporter is not None:
                progress_reporter.update(
                    current_index=len(trials),
                    current_condition="final_gray",
                    elapsed_seconds=time.monotonic() - playback_start_monotonic,
                    remaining_seconds=0.0,
                )
            append_csv_row(session.event_log_path, {"event_type": "session_end", "cache_hash": cache.cache_hash}, EVENT_FIELDS)
            session_completed = True
            session_end_logged = True
    except KeyboardInterrupt:
        keyboard_interrupt = True
        failure_stage = current_stage
        failure_summary = "KeyboardInterrupt"
        if session.event_log_path.exists() and not session_end_logged:
            append_csv_row(
                session.event_log_path,
                {"event_type": "session_end", "notes": "keyboard_interrupt"},
                EVENT_FIELDS,
            )
            session_end_logged = True
    except Exception as exc:
        stored_exception = exc
        failure_stage = current_stage
        failure_summary = f"{type(exc).__name__}: {exc}"
        if session.event_log_path.exists() and not session_end_logged:
            append_csv_row(
                session.event_log_path,
                {"event_type": "session_end", "notes": f"{type(exc).__name__}: {exc}"},
                EVENT_FIELDS,
            )
            session_end_logged = True
    finally:
        if progress_reporter is not None:
            progress_reporter.finish()
        baseline_core.stop_early_start_monitor(baseline_monitor)
        cleanup_stage = "gpio_cleanup"
        if gpio_controller is not None:
            try:
                gpio_controller.drive_low()
                gpio_controller.cleanup()
            except Exception as exc:
                cleanup_error = f"{type(exc).__name__}: {exc}"
        cleanup_stage = "camera_cleanup"
        if camera_started:
            if prompt_yes_no("Stop camera recording and fetch files now?", default_yes=True):
                camera_cleanup_result = camera_core.stop_and_fetch_camera(
                    system_config.camera,
                    system_config.output_root,
                    settle_seconds=CAMERA_SETTLING_SEC,
                )
                if camera_cleanup_result.cleanup_error and cleanup_error is None:
                    cleanup_error = camera_cleanup_result.cleanup_error
            else:
                camera_left_running = True
                camera_cleanup_result = camera_core.CameraCleanupResult(
                    stop_result=None,
                    fetch_result=None,
                    convert_result=None,
                    left_running=True,
                )
                print("Camera left running. Manual cleanup:")
                print(camera_core.manual_stop_fetch_command(repo_root))
        update_session_metadata(
            session.metadata_path,
            session_completed=session_completed,
            session_stage="complete" if session_completed else current_stage,
            failure_stage=None if session_completed else failure_stage,
            failure_summary=None if session_completed else failure_summary,
            cleanup_stage=cleanup_stage,
            cleanup_error=cleanup_error,
            end_utc=utc_iso_now(),
            camera_state={
                **initial_metadata["camera_state"],
                "enabled": camera_enabled,
                "start_requested_utc": camera_start_requested_utc,
                "start_returned_utc": camera_start_returned_utc,
                "start_verified": camera_start_verified,
                "stop_requested": bool(camera_cleanup_result and camera_cleanup_result.stop_result is not None),
                "stopped": bool(camera_cleanup_result and camera_cleanup_result.stop_result and camera_cleanup_result.stop_result.succeeded),
                "settle_seconds": None if camera_cleanup_result is None else camera_cleanup_result.settle_seconds,
                "fetch_requested": bool(camera_cleanup_result and camera_cleanup_result.fetch_result is not None),
                "fetched": bool(camera_cleanup_result and camera_cleanup_result.fetch_result and camera_cleanup_result.fetch_result.succeeded),
                "convert_requested": bool(camera_cleanup_result and camera_cleanup_result.convert_result is not None),
                "conversion_attempted": bool(camera_cleanup_result and camera_cleanup_result.convert_result is not None),
                "conversion_succeeded": bool(camera_cleanup_result and camera_cleanup_result.convert_result and camera_cleanup_result.convert_result.succeeded),
                "cleanup_error": cleanup_error,
                "left_running": camera_left_running,
                "cleanup_result": _serialize_camera_cleanup_result(camera_cleanup_result),
            },
            prestim={
                **initial_metadata["prestim"],
                "actual_camera_baseline_sec": None if baseline_result is None else baseline_result.actual_camera_baseline_seconds,
                "actual_gray_sec": None if baseline_result is None else baseline_result.actual_gray_seconds,
                "override_used": False if baseline_result is None else baseline_result.override_used,
                "end_reason": None if baseline_result is None else baseline_result.end_reason,
                "raw_loading_duration_sec": raw_loading_duration_sec,
            },
        )
    if stored_exception is not None:
        raise stored_exception
    if keyboard_interrupt:
        return 130
    if cleanup_error is not None:
        raise RuntimeError(cleanup_error)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
