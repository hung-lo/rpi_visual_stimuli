from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

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
from .cache import approximate_build_peak_bytes, approximate_loaded_bytes, cache_root_for_config, ensure_cache
from .config import (
    DEFAULT_DIRECTIONS,
    DEFAULT_REPEATS_PER_DIRECTION,
    FOUR_DIRECTION_MODE,
    build_config,
    build_test_config,
)
from .events import EVENT_FIELDS
from .sequence import build_trial_sequence


PROTOCOL_NAME = "retinotopy"
CAMERA_SETTLING_SEC = 2.0


def build_parser() -> argparse.ArgumentParser:
    return build_common_parser("Run the retinotopic mapping protocol.")


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
    cache_dir: Path,
    camera_enabled: bool,
    baseline_minutes: float | None,
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
    print(f"  Cache root: {cache_dir}")
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


def _initial_metadata(
    repo_root: Path,
    session,
    system_config: SystemConfig,
    config,
    *,
    camera_enabled: bool,
    baseline_minutes: float | None,
    resolved_seed: int,
    cache,
    preflight,
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
            "requested_baseline_minutes": baseline_minutes,
            "stop_fetch_outcome": None,
            "manual_command_if_left_running": camera_core.manual_stop_fetch_command(repo_root),
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
        "timing_note": (
            "The request timestamp is the Raspberry Pi software request immediately before "
            "screen.display_raw(). It is not measured monitor onset. The photodiode is the "
            "physical timing ground truth."
        ),
    }


def _playback_trials(screen, trials, cache, loaded_sweeps, loaded_inter_sweep, event_log_path, config):
    start_monotonic = time.monotonic()
    total = len(trials)
    for index, trial in enumerate(trials, start=1):
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
        if index < total:
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
        elapsed = time.monotonic() - start_monotonic
        remaining = []
        for item in trials[index:]:
            remaining.append(float(item["planned_sweep_duration_sec"]))
            remaining.append(float(item["planned_gray_duration_sec"]))
        print(
            render_progress_line(
                current_index=index,
                total_count=total,
                current_condition=f"direction={trial['direction']}",
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
    config = _prompt_protocol_config(system_config, test_mode=args.test)
    trials, resolved_seed = build_trial_sequence(system_config, config)

    if args.dry_run:
        _print_summary(system_config, config, trials, cache_root_for_config(system_config, config), camera_enabled, baseline_minutes)
        print()
        print("Dry-run mode:")
        print(f"  Would build cache at: {cache_root_for_config(system_config, config)}")
        print(f"  Would run {len(trials)} retinotopy sweeps")
        return 0

    rpg = import_rpg_or_raise()
    check_disk_space_before_build(
        cache_root_for_config(system_config, config),
        required_bytes=approximate_build_peak_bytes(system_config, config),
        margin_bytes=1024 * 1024 * 1024,
    )
    cache = ensure_cache(system_config, config, convert_raw_fn=rpg.convert_raw)
    _print_summary(system_config, config, trials, cache.cache_dir, camera_enabled, baseline_minutes)
    if args.preview_only:
        print()
        print("Preview-only mode:")
        print(f"  Contact sheet: {cache.contact_sheet_path}")
        print(f"  Cache manifest: {cache.manifest_path}")
        return 0
    if args.build_cache_only:
        print(f"Cache built: {cache.cache_dir}")
        print(f"Manifest: {cache.manifest_path}")
        return 0
    if not prompt_yes_no("Start this session", default_yes=True):
        print("Session aborted before starting. No session folder was created.")
        return 0

    memory_check = check_memory_before_loading(
        list(cache.sweep_paths.values()),
        overhead_factor=1.15,
        safety_margin_bytes=768 * 1024 * 1024,
        suggestion="Reduce directions, shorten sweeps, or run two-direction mode first.",
    )
    session = build_session_context(PROTOCOL_NAME, mouse_id_raw, session_notes, system_config.output_root)
    create_session_directories(session)
    planned_rows = _planned_rows(trials, cache.cache_hash)
    write_csv(session.planned_sequence_path, planned_rows, list(planned_rows[0].keys()))
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

    baseline_monitor = None
    camera_started = False
    current_stage = "initializing"
    session_completed = False
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
            current_stage = "loading_raws"
            loaded_sweeps = load_raws(screen, cache.sweep_paths)
            loaded_inter_sweep = screen.load_raw(str(cache.inter_sweep_gray_path))
            loaded_initial_gray = screen.load_raw(str(initial_gray.path))
            loaded_final_gray = screen.load_raw(str(final_gray.path))
            loaded_baseline_gray = screen.load_raw(str(baseline_gray.path))
            current_stage = "displaying_prestim_gray"
            if camera_enabled:
                prestim_timing = display_raw_with_timing(screen, loaded_baseline_gray)
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
            append_csv_row(session.event_log_path, {"event_type": "session_start", "cache_hash": cache.cache_hash}, EVENT_FIELDS)
            current_stage = "playback"
            _playback_trials(
                screen,
                trials,
                cache,
                loaded_sweeps,
                loaded_inter_sweep,
                session.event_log_path,
                config,
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
            append_csv_row(session.event_log_path, {"event_type": "session_end", "cache_hash": cache.cache_hash}, EVENT_FIELDS)
            session_completed = True
    except Exception as exc:
        if session.event_log_path.exists():
            append_csv_row(session.event_log_path, {"event_type": "session_end", "notes": f"{type(exc).__name__}: {exc}"}, EVENT_FIELDS)
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
