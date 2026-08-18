from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import sys
import time
from typing import Optional

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
    format_bytes,
    validate_storage_root,
)
from ...core.progress import ProgressReporter
from ...core.raw_cache import copy_manifest_to_session
from ...core.rpg_display import (
    diagnose_rpg_display_return,
    display_raw_with_timing,
    import_rpg_or_raise,
    load_raws,
    open_screen,
)
from ...core.session import build_session_context, create_session_directories
from ...core.timestamps import utc_iso_now
from .cache import (
    approximate_build_peak_bytes,
    approximate_loaded_bytes,
    cache_root_for_config,
    ensure_cache,
    ensure_preview_assets,
)
from .config import (
    DEFAULT_DIRECTIONS,
    DEFAULT_REPEATS_PER_DIRECTION,
    FOUR_DIRECTION_MODE,
    build_config,
    build_test_config,
)
from .events import EVENT_FIELDS
from .sequence import build_trial_sequence, trial_epoch_durations_sec


PROTOCOL_NAME = "retinotopy"
CAMERA_SETTLING_SEC = 2.0


def build_parser() -> argparse.ArgumentParser:
    parser = build_common_parser("Run the retinotopic mapping protocol.")
    parser.add_argument(
        "--test-rpg-return",
        action="store_true",
        help="Display one cached sweep and print the RPG return-value timing diagnostic.",
    )
    return parser


def _prompt_protocol_config(system_config: SystemConfig, *, test_mode: bool):
    if test_mode:
        return build_test_config(system_config)
    mapping_mode = prompt_text("Mapping mode: 2 directions or 4 directions", default="2").strip().lower()
    if mapping_mode not in {"2", "4"}:
        raise ValueError("mapping mode must be 2 or 4")
    enabled_directions = DEFAULT_DIRECTIONS if mapping_mode == "2" else FOUR_DIRECTION_MODE
    repeats_per_direction = prompt_int("Repeats per direction", default=DEFAULT_REPEATS_PER_DIRECTION)
    sweep_duration_sec = prompt_float("Sweep duration (sec)", default=20.0)
    inter_sweep_gray_sec = prompt_float("Gray interval between sweeps (sec)", default=5.0)
    movement_frame_rate_hz = prompt_int("Movement frame rate (Hz)", default=15)
    order_mode = prompt_text("Sequence order: fixed or shuffled", default="fixed").strip().lower()
    return build_config(
        system_config,
        sweep_duration_sec=sweep_duration_sec,
        inter_sweep_gray_sec=inter_sweep_gray_sec,
        movement_frame_rate_hz=movement_frame_rate_hz,
        enabled_directions=enabled_directions,
        repeats_per_direction=repeats_per_direction,
        sequence_order_mode=order_mode,
    )


def _print_summary(
    system_config: SystemConfig,
    config,
    trials,
    camera_enabled: bool,
    baseline_minutes: Optional[float],
    duration_summary: ProtocolDurationSummary,
) -> None:
    print()
    print("Retinotopy setup summary:")
    print(f"  Camera enabled: {camera_enabled}")
    if baseline_minutes is not None:
        print(f"  Camera baseline minutes: {baseline_minutes}")
    print(f"  Directions: {', '.join(config.enabled_directions)}")
    print(f"  Repeats per direction: {config.repeats_per_direction}")
    print(f"  Total sweeps: {len(trials)}")
    print(f"  Sweep duration: {config.sweep_duration_sec} sec")
    print(f"  Gray interval: {config.inter_sweep_gray_sec} sec")
    print(f"  Movement frame rate: {config.movement_frame_rate_hz} Hz")
    print(f"  Refreshes per movement frame: {config.refreshes_per_movement_frame}")
    print(f"  Cache root: {cache_root_for_config(system_config, config)}")
    print(
        "  Exact planned sweep-sequence duration: "
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
    print(
        "  Estimated loaded raw bytes: "
        f"{approximate_loaded_bytes(system_config, config)}"
    )


def _planned_rows(trials, cache_hash: str):
    rows = []
    for trial in trials:
        rows.append(
            {
                "trial_index": trial["trial_index"],
                "repeat_number": trial["repeat_number"],
                "direction": trial["direction"],
                "direction_code": trial["direction_code"],
                "axis": trial["axis"],
                "start_edge": trial["start_edge"],
                "end_edge": trial["end_edge"],
                "planned_sweep_duration_sec": trial["planned_sweep_duration_sec"],
                "planned_gray_duration_sec": trial["planned_gray_duration_sec"],
                "raw_key": trial["raw_key"],
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


def _resolve_cleanup_stage(
    *,
    screen_opened: bool,
    gpio_cleanup_attempted: bool,
    camera_cleanup_attempted: bool,
) -> Optional[str]:
    if camera_cleanup_attempted:
        return "camera_cleanup"
    if gpio_cleanup_attempted:
        return "gpio_cleanup"
    if screen_opened:
        return "rpg_cleanup"
    return None


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
    print("Starting retinotopy stimulation.")
    print(f"  Planned sweep + inter-sweep-gray duration: {format_duration(trial_sequence_sec)}")
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
):
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
            "pulse_semantics": "one pulse immediately before each retinotopy sweep request",
        },
        "cache": {
            "cache_hash": cache.cache_hash,
            "cache_dir": str(cache.cache_dir),
            "manifest_path": str(cache.manifest_path),
            "sweep_paths": {key: str(path) for key, path in cache.sweep_paths.items()},
            "inter_sweep_gray_path": str(cache.inter_sweep_gray_path),
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
        "timing_note": (
            "The request timestamp is the Raspberry Pi software request immediately before "
            "screen.display_raw(). It is not measured monitor onset. The photodiode is the "
            "physical timing ground truth."
        ),
    }


def _playback_trials(
    screen,
    trials,
    cache,
    loaded_sweeps,
    loaded_inter_sweep,
    *,
    event_log_path: Path,
    config,
    progress_reporter: ProgressReporter,
    playback_start_monotonic: float,
    remaining_after_index: list[float],
    final_gray_sec: float,
    gpio_controller=None,
):
    for index, trial in enumerate(trials, start=1):
        if gpio_controller is not None:
            gpio_controller.pulse()
        sweep_timing = display_raw_with_timing(screen, loaded_sweeps[trial["raw_key"]])
        append_csv_row(
            event_log_path,
            {
                "event_type": "sweep_display",
                "planned_duration_sec": trial["planned_sweep_duration_sec"],
                "raw_path": str(cache.sweep_paths[trial["raw_key"]]),
                "trial_index": trial["trial_index"],
                "repeat_number": trial["repeat_number"],
                "direction": trial["direction"],
                "direction_code": trial["direction_code"],
                "axis": trial["axis"],
                "start_edge": trial["start_edge"],
                "end_edge": trial["end_edge"],
                "movement_frame_rate_hz": config.movement_frame_rate_hz,
                "refreshes_per_movement_frame": config.refreshes_per_movement_frame,
                "bar_width_fraction": config.bar_width_fraction,
                "cache_hash": cache.cache_hash,
                **sweep_timing.to_event_fields(),
            },
            EVENT_FIELDS,
        )
        gray_timing = display_raw_with_timing(screen, loaded_inter_sweep)
        append_csv_row(
            event_log_path,
            {
                "event_type": "inter_sweep_gray",
                "planned_duration_sec": trial["planned_gray_duration_sec"],
                "raw_path": str(cache.inter_sweep_gray_path),
                "trial_index": trial["trial_index"],
                "repeat_number": trial["repeat_number"],
                "direction": trial["direction"],
                "direction_code": trial["direction_code"],
                "axis": trial["axis"],
                "start_edge": trial["start_edge"],
                "end_edge": trial["end_edge"],
                "movement_frame_rate_hz": config.movement_frame_rate_hz,
                "refreshes_per_movement_frame": config.refreshes_per_movement_frame,
                "bar_width_fraction": config.bar_width_fraction,
                "cache_hash": cache.cache_hash,
                **gray_timing.to_event_fields(),
            },
            EVENT_FIELDS,
        )
        progress_reporter.update(
            current_index=index,
            current_condition=f"direction={trial['direction']}",
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
    config = _prompt_protocol_config(system_config, test_mode=args.test)
    trials, resolved_seed = build_trial_sequence(system_config, config)
    trial_epoch_seconds = trial_epoch_durations_sec(trials)
    duration_summary = summarize_protocol_duration(
        trial_epoch_durations_sec=trial_epoch_seconds,
        initial_gray_sec=config.initial_gray_sec,
        final_gray_sec=config.final_gray_sec,
        camera_enabled=camera_enabled,
        baseline_minutes=baseline_minutes,
    )
    planned_cache_dir = cache_root_for_config(system_config, config)
    planned_rows = _planned_rows(trials, planned_cache_dir.name)
    _print_summary(system_config, config, trials, camera_enabled, baseline_minutes, duration_summary)

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
        if using_fallback:
            print(f"  Preview cache directory: {preview_cache_dir}")
        print(f"  Preview plan: {preview_plan_path}")
        print(f"  Contact sheet: {contact_sheet_path}")
        print(f"  Preview images: {len(preview_paths)}")
        print(f"  Estimated loaded raw bytes: {approximate_loaded_bytes(system_config, config)}")
        print(f"  Estimated peak build bytes: {approximate_build_peak_bytes(system_config, config)}")
        return 0

    if args.dry_run:
        print()
        print("Dry-run mode:")
        print(f"  Would build cache at: {planned_cache_dir}")
        print(f"  Would run {len(trials)} retinotopy sweeps")
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
            print("Session aborted before starting. No session folder was created.")
            return 0

    peak_build_bytes = approximate_build_peak_bytes(system_config, config)
    rpg = import_rpg_or_raise()
    storage_check = validate_storage_root(
        system_config.output_root,
        require_separate_mount=system_config.storage.require_separate_mount,
    )
    if not storage_check["is_mount_point"]:
        print(
            "Storage root: {}\n"
            "  Free space: {}\n"
            "WARNING: {} is not a separate mount point. "
            "Continuing because this deployment allows non-mounted storage roots.".format(
                system_config.output_root,
                format_bytes(int(storage_check["free_bytes"])),
                system_config.output_root,
            )
        )
    check_disk_space_before_build(
        planned_cache_dir,
        required_bytes=peak_build_bytes,
        margin_bytes=1024 * 1024 * 1024,
    )
    cache = ensure_cache(system_config, config, convert_raw_fn=rpg.convert_raw)
    if args.test_rpg_return:
        first_direction = config.enabled_directions[0]
        with open_screen(system_config) as screen:
            loaded_raw = screen.load_raw(str(cache.sweep_paths[first_direction]))
            diagnose_rpg_display_return(screen, loaded_raw)
        return 0
    if args.build_cache_only:
        print(f"Cache built: {cache.cache_dir}")
        print(f"Manifest: {cache.manifest_path}")
        return 0

    memory_check = check_memory_before_loading(
        list(cache.sweep_paths.values()),
        overhead_factor=1.15,
        safety_margin_bytes=768 * 1024 * 1024,
        suggestion="Reduce directions, shorten sweeps, or run two-direction mode first.",
    )
    session = build_session_context(PROTOCOL_NAME, mouse_id_raw, session_notes, system_config.output_root)
    create_session_directories(session)
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
            "storage": storage_check,
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

    baseline_monitor = None
    camera_started = False
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
    screen_opened = False
    progress_reporter = None
    try:
        baseline_gray = get_baseline_gray_raw(cache.cache_dir, system_config, convert_raw_fn=rpg.convert_raw)
        initial_gray_frames = max(1, int(round(config.initial_gray_sec * system_config.screen.refresh_rate_hz)))
        final_gray_frames = max(1, int(round(config.final_gray_sec * system_config.screen.refresh_rate_hz)))
        initial_gray = get_timed_gray_raw(
            cache.cache_dir,
            system_config,
            duration_frames=initial_gray_frames,
            stem=f"gray_initial_{initial_gray_frames}frames",
            convert_raw_fn=rpg.convert_raw,
        )
        final_gray = get_timed_gray_raw(
            cache.cache_dir,
            system_config,
            duration_frames=final_gray_frames,
            stem=f"gray_final_{final_gray_frames}frames",
            convert_raw_fn=rpg.convert_raw,
        )
        with open_screen(system_config) as screen:
            screen_opened = True
            loaded_sweeps = {}
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
                loaded_sweeps = load_raws(screen, cache.sweep_paths)
                loaded_inter_sweep = screen.load_raw(str(cache.inter_sweep_gray_path))
                loaded_final_gray = screen.load_raw(str(final_gray.path))
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
                loaded_sweeps = load_raws(screen, cache.sweep_paths)
                loaded_inter_sweep = screen.load_raw(str(cache.inter_sweep_gray_path))
                loaded_initial_gray = screen.load_raw(str(initial_gray.path))
                loaded_final_gray = screen.load_raw(str(final_gray.path))
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
                prestim_timing = display_raw_with_timing(screen, loaded_initial_gray)
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
                current_condition="waiting_for_first_sweep",
                elapsed_seconds=0.0,
                remaining_seconds=duration_summary.trial_sequence_sec + config.final_gray_sec,
            )
            append_csv_row(
                session.event_log_path,
                {"event_type": "session_start", "cache_hash": cache.cache_hash},
                EVENT_FIELDS,
            )
            current_stage = "playback"
            _playback_trials(
                screen,
                trials,
                cache,
                loaded_sweeps,
                loaded_inter_sweep,
                event_log_path=session.event_log_path,
                config=config,
                progress_reporter=progress_reporter,
                playback_start_monotonic=playback_start_monotonic,
                remaining_after_index=_remaining_suffix_sums(trial_epoch_seconds),
                final_gray_sec=config.final_gray_sec,
                gpio_controller=gpio_controller,
            )
            current_stage = "final_gray"
            final_timing = display_raw_with_timing(screen, loaded_final_gray)
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
            append_csv_row(
                session.event_log_path,
                {"event_type": "session_end", "cache_hash": cache.cache_hash},
                EVENT_FIELDS,
            )
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
        gpio_cleanup_attempted = gpio_controller is not None
        gpio_cleanup_succeeded = None
        gpio_cleanup_error = None
        if gpio_controller is not None:
            try:
                gpio_controller.drive_low()
                gpio_controller.cleanup()
                gpio_cleanup_succeeded = True
            except Exception as exc:
                gpio_cleanup_error = f"{type(exc).__name__}: {exc}"
                if cleanup_error is None:
                    cleanup_error = gpio_cleanup_error
        camera_cleanup_attempted = False
        if camera_started:
            camera_cleanup_attempted = True
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
        cleanup_stage = _resolve_cleanup_stage(
            screen_opened=screen_opened,
            gpio_cleanup_attempted=gpio_cleanup_attempted,
            camera_cleanup_attempted=camera_cleanup_attempted,
        )
        update_session_metadata(
            session.metadata_path,
            session_completed=session_completed,
            session_stage="complete" if session_completed else current_stage,
            failure_stage=None if session_completed else failure_stage,
            failure_summary=None if session_completed else failure_summary,
            cleanup_stage=cleanup_stage,
            cleanup_error=cleanup_error,
            cleanup={
                "rpg": {"attempted": screen_opened, "succeeded": True if screen_opened else None, "error": None},
                "gpio": {
                    "attempted": gpio_cleanup_attempted,
                    "succeeded": gpio_cleanup_succeeded,
                    "error": gpio_cleanup_error,
                },
                "camera": {
                    "applicable": camera_enabled,
                    "attempted": camera_cleanup_attempted,
                    "succeeded": (
                        None
                        if camera_cleanup_result is None
                        else not camera_cleanup_result.left_running and not bool(camera_cleanup_result.cleanup_error)
                    ),
                    "error": None if camera_cleanup_result is None else camera_cleanup_result.cleanup_error,
                },
            },
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
