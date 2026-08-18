#!/usr/bin/env python3
"""
Standalone second-Pi camera controller for rpi_visual_stimuli.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Optional


DEFAULT_CAMERA_HOST = "pi@192.168.1.152"

REMOTE_CAMERA_REPO = "/home/pi/RPi4_behavior_boxes"
REMOTE_CAMERA_START = "/home/pi/RPi4_behavior_boxes/video_acquisition/start_acquisition.py"
REMOTE_CAMERA_STOP = "/home/pi/RPi4_behavior_boxes/video_acquisition/stop_acquisition.sh"
REMOTE_CAMERA_PREVIEW_LOG = "/home/pi/stim_logs/camera_preview.log"
REMOTE_CAMERA_PREVIEW_PID_FILE = "/tmp/remote_camera_preview.pid"

REMOTE_VIDEO_ROOT = "/home/pi/stim_logs"
LOCAL_VIDEO_ROOT = Path("/mnt/hd")
SESSION_NAME_SUFFIX = "rpi_visual_stimuli"
CAMERA_FRAMERATE = 30
DEFAULT_VERIFY_WAIT_SEC = 1.5
SSH_CONNECT_TIMEOUT_SEC = 5
SSH_COMMAND_TIMEOUT_SEC = 15.0
RSYNC_IO_TIMEOUT_SEC = 60
RSYNC_COMMAND_TIMEOUT_SEC = 3600.0

PROJECT_ROOT = Path(__file__).resolve().parent
STATE_FILE = LOCAL_VIDEO_ROOT / ".rpi_visual_stimuli_camera_session.json"
LEGACY_STATE_FILE = LOCAL_VIDEO_ROOT / ".last_remote_camera_session.json"


class CameraControlError(RuntimeError):
    exit_code = 1


class PreflightError(CameraControlError):
    exit_code = 2


class ExistingAcquisitionError(CameraControlError):
    exit_code = 3


def utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_label() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sanitize_id(text: str) -> str:
    keep: list[str] = []
    for char in str(text).strip():
        if char.isalnum() or char in {"-", "_"}:
            keep.append(char)
        else:
            keep.append("_")
    return "".join(keep)


def make_session_name(mouse_id: str, session_stamp: str) -> str:
    return f"{mouse_id}_{session_stamp}_{SESSION_NAME_SUFFIX}"


def run_cmd(
    cmd: list[str],
    *,
    check: bool = True,
    dry_run: bool = False,
    quiet: bool = False,
    timeout_sec: Optional[float] = None,
) -> subprocess.CompletedProcess[str]:
    if not quiet:
        print("+ " + " ".join(shlex.quote(part) for part in cmd))
    if dry_run:
        return subprocess.CompletedProcess(cmd, 0, "", "")
    try:
        result = subprocess.run(
            cmd,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise CameraControlError(
            f"command timed out after {timeout_sec} seconds: {' '.join(cmd)}"
        ) from exc
    if check and result.returncode != 0:
        if result.stdout and not quiet:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        raise CameraControlError(
            f"command failed with exit code {result.returncode}: {' '.join(cmd)}"
        )
    if result.stdout and not quiet:
        print(result.stdout, end="")
    if result.stderr and not quiet:
        print(result.stderr, end="", file=sys.stderr)
    return result


def run_ssh(
    camera_host: str,
    remote_cmd: str,
    *,
    check: bool = True,
    dry_run: bool = False,
    batch_mode: bool = True,
    connect_timeout: Optional[int] = SSH_CONNECT_TIMEOUT_SEC,
    command_timeout_sec: Optional[float] = SSH_COMMAND_TIMEOUT_SEC,
    quiet: bool = False,
) -> subprocess.CompletedProcess[str]:
    cmd = ["ssh"]
    if batch_mode:
        cmd.extend(["-o", "BatchMode=yes"])
    if connect_timeout is not None:
        cmd.extend(["-o", f"ConnectTimeout={int(connect_timeout)}"])
    cmd.extend([camera_host, remote_cmd])
    return run_cmd(
        cmd,
        check=check,
        dry_run=dry_run,
        quiet=quiet,
        timeout_sec=command_timeout_sec,
    )


def run_rsync(
    camera_host: str,
    remote_dir: str,
    local_dir: Path,
    *,
    remove_source_files: bool = True,
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    local_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["rsync", "-av", "--progress", f"--timeout={RSYNC_IO_TIMEOUT_SEC}"]
    cmd.extend([f"{camera_host}:{remote_dir.rstrip('/')}/", str(local_dir) + "/"])
    cmd[1:1] = ["-e", f"ssh -o BatchMode=yes -o ConnectTimeout={SSH_CONNECT_TIMEOUT_SEC}"]
    return run_cmd(cmd, check=True, dry_run=dry_run, timeout_sec=RSYNC_COMMAND_TIMEOUT_SEC)


def convert_h264_to_mp4(
    local_video_dir: Path,
    *,
    framerate: int = CAMERA_FRAMERATE,
    dry_run: bool = False,
) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise PreflightError("ffmpeg not found in PATH")
    h264_files = sorted(local_video_dir.glob("*.h264"))
    if not h264_files:
        print("No .h264 files found for mp4 conversion.")
        return True
    for input_path in h264_files:
        output_path = input_path.with_suffix(".mp4")
        if output_path.exists():
            print(f"MP4 already exists, skipping: {output_path}")
            continue
        cmd = [
            ffmpeg,
            "-y",
            "-framerate",
            str(framerate),
            "-i",
            str(input_path),
            "-c:v",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        print("+ " + " ".join(shlex.quote(part) for part in cmd))
        if dry_run:
            continue
        result = subprocess.run(cmd, check=False, text=True, capture_output=True)
        if result.returncode != 0:
            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
            raise CameraControlError(f"ffmpeg conversion failed for {input_path.name}")
        print(f"Converted {input_path.name} -> {output_path.name}")
    return True


def append_event(local_video_dir: Path, event: str, details: Optional[dict[str, object]] = None) -> None:
    local_video_dir.mkdir(parents=True, exist_ok=True)
    path = local_video_dir / "camera_control_events.csv"
    exists = path.exists()
    fieldnames = ["unix_time_utc_sec", "iso_time_utc", "event", "details_json"]
    row = {
        "unix_time_utc_sec": f"{time.time():.6f}",
        "iso_time_utc": utc_iso_now(),
        "event": event,
        "details_json": json.dumps(details or {}, sort_keys=True),
    }
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def save_state(state: dict[str, object]) -> None:
    state_path = Path(state["state_file_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=state_path.parent,
                                         prefix=f".{state_path.name}.", suffix=".tmp", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, state_path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    print(f"Saved state: {state_path}")


def load_state(*, allow_legacy_state: bool = False) -> dict[str, object]:
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CameraControlError(
                f"Camera state at {STATE_FILE} is unreadable or corrupt ({exc}). "
                "The file was retained; use explicit stop-recovery to stop a running acquisition."
            ) from exc
        state.setdefault("state_file_path", str(STATE_FILE))
        return state
    if allow_legacy_state and LEGACY_STATE_FILE.exists():
        state = json.loads(LEGACY_STATE_FILE.read_text(encoding="utf-8"))
        if state.get("mouse_id") and state.get("session_id"):
            session_id = state["session_id"]
            local_session_dir = (LOCAL_VIDEO_ROOT / session_id).resolve()
            state["local_session_dir"] = str(local_session_dir)
            state["local_video_dir"] = str(local_session_dir / "video")
        state.setdefault("state_file_path", str(LEGACY_STATE_FILE))
        return state
    raise CameraControlError(
        f"No saved camera session state found at {STATE_FILE}. "
        f"Legacy state at {LEGACY_STATE_FILE} is ignored unless --allow-legacy-state is passed."
    )


def resolve_camera_host(args, state: Optional[dict[str, object]] = None) -> str:
    if getattr(args, "camera_host", None):
        return args.camera_host
    if state and state.get("camera_host"):
        return str(state["camera_host"])
    return DEFAULT_CAMERA_HOST


def resolve_local_output_root(args, state: Optional[dict[str, object]] = None) -> Path:
    if getattr(args, "local_output_root", None):
        return Path(args.local_output_root)
    if state and state.get("local_output_root"):
        return Path(str(state["local_output_root"]))
    return LOCAL_VIDEO_ROOT


def resolve_remote_video_root(args, state: Optional[dict[str, object]] = None) -> str:
    if getattr(args, "remote_video_root", None):
        return args.remote_video_root
    if state and state.get("remote_video_root"):
        return str(state["remote_video_root"])
    return REMOTE_VIDEO_ROOT


def resolve_remote_start(args, state: Optional[dict[str, object]] = None) -> str:
    if getattr(args, "remote_camera_start", None):
        return args.remote_camera_start
    if state and state.get("remote_camera_start"):
        return str(state["remote_camera_start"])
    return REMOTE_CAMERA_START


def resolve_remote_stop(args, state: Optional[dict[str, object]] = None) -> str:
    if getattr(args, "remote_camera_stop", None):
        return args.remote_camera_stop
    if state and state.get("remote_camera_stop"):
        return str(state["remote_camera_stop"])
    return REMOTE_CAMERA_STOP


def resolve_remote_repo(args, state: Optional[dict[str, object]] = None) -> str:
    if getattr(args, "remote_camera_repo", None):
        return args.remote_camera_repo
    if state and state.get("remote_camera_repo"):
        return str(state["remote_camera_repo"])
    return REMOTE_CAMERA_REPO


def acquisition_pattern(remote_start_path: str) -> str:
    return f"[{Path(remote_start_path).name[0]}]{Path(remote_start_path).name[1:]}"


def make_session_paths(args) -> dict[str, str]:
    mouse_id = sanitize_id(args.mouse_id)
    if not mouse_id:
        raise CameraControlError("mouse ID cannot be empty")
    session_id = sanitize_id(args.session_id) if args.session_id else make_session_name(mouse_id, utc_label())
    local_output_root = resolve_local_output_root(args)
    remote_video_root = resolve_remote_video_root(args)
    local_session_dir = (local_output_root / session_id).resolve()
    local_video_dir = local_session_dir / "video"
    remote_session_dir = f"{remote_video_root.rstrip('/')}/{session_id}"
    remote_video_dir = f"{remote_session_dir}/video"
    remote_base_path = f"{remote_video_dir}/{session_id}"
    return {
        "mouse_id": mouse_id,
        "session_id": session_id,
        "local_output_root": str(local_output_root),
        "local_session_dir": str(local_session_dir),
        "local_video_dir": str(local_video_dir),
        "remote_video_root": remote_video_root,
        "remote_session_dir": remote_session_dir,
        "remote_video_dir": remote_video_dir,
        "remote_base_path": remote_base_path,
        "state_file_path": str(STATE_FILE),
    }


def build_state_from_args(args) -> dict[str, object]:
    if not getattr(args, "mouse_id", None):
        raise CameraControlError("Pass --mouse-id when no saved state exists.")
    if not getattr(args, "session_id", None):
        raise CameraControlError("Pass --session-id when no saved state exists.")
    return {
        "created_utc": utc_iso_now(),
        "camera_host": resolve_camera_host(args),
        "framerate": getattr(args, "framerate", CAMERA_FRAMERATE),
        "remote_camera_repo": resolve_remote_repo(args),
        "remote_camera_start": resolve_remote_start(args),
        "remote_camera_stop": resolve_remote_stop(args),
        **make_session_paths(args),
    }


def _command_available(name: str) -> dict[str, object]:
    path = shutil.which(name)
    return {"name": name, "ok": path is not None, "path": path}


def _check_local_writable(path: Path) -> bool:
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path, delete=True):
        pass
    return True


def _check_state_file_parent_writable() -> bool:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=STATE_FILE.parent, delete=True):
        pass
    return True


def _query_remote_acquisition(
    camera_host: str,
    remote_start_path: str,
    *,
    dry_run: bool = False,
    batch_mode: bool = False,
    connect_timeout: Optional[int] = None,
) -> dict[str, object]:
    pattern = acquisition_pattern(remote_start_path)
    result = run_ssh(
        camera_host,
        f"pgrep -af {shlex.quote(pattern)} || true",
        check=False,
        dry_run=dry_run,
        batch_mode=batch_mode,
        connect_timeout=connect_timeout,
        quiet=True,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return {"running": bool(lines), "lines": lines}


def _run_preflight_checks(args) -> dict[str, object]:
    camera_host = resolve_camera_host(args)
    remote_repo = resolve_remote_repo(args)
    remote_start = resolve_remote_start(args)
    remote_stop = resolve_remote_stop(args)
    remote_video_root = resolve_remote_video_root(args)
    local_output_root = resolve_local_output_root(args)

    checks = {
        "ssh": _command_available("ssh"),
        "rsync": _command_available("rsync"),
        "ffmpeg": _command_available("ffmpeg"),
    }
    missing = [name for name, value in checks.items() if not value["ok"]]
    if missing:
        raise PreflightError("Missing required local tools: " + ", ".join(sorted(missing)))

    try:
        _check_local_writable(local_output_root)
        _check_state_file_parent_writable()
    except OSError as exc:
        raise PreflightError(f"Local output path or state-file directory is not writable: {exc}") from exc

    connect = run_ssh(
        camera_host,
        "echo camera_connection_ok",
        check=False,
        dry_run=args.dry_run,
        batch_mode=True,
        connect_timeout=SSH_CONNECT_TIMEOUT_SEC,
        command_timeout_sec=SSH_COMMAND_TIMEOUT_SEC,
        quiet=True,
    )
    if not args.dry_run:
        if connect.returncode != 0 or "camera_connection_ok" not in connect.stdout:
            raise PreflightError(
                f"Cannot connect noninteractively to {camera_host} with ssh -o BatchMode=yes -o ConnectTimeout=5"
            )

    remote_checks_cmd = (
        "set -e; "
        f"test -d {shlex.quote(remote_repo)}; "
        f"test -f {shlex.quote(remote_start)}; "
        f"test -f {shlex.quote(remote_stop)}; "
        f"mkdir -p {shlex.quote(remote_video_root)}; "
        f"test -w {shlex.quote(remote_video_root)}; "
        "echo remote_preflight_ok"
    )
    remote_checks = run_ssh(
        camera_host,
        remote_checks_cmd,
        check=False,
        dry_run=args.dry_run,
        batch_mode=True,
        connect_timeout=SSH_CONNECT_TIMEOUT_SEC,
        command_timeout_sec=SSH_COMMAND_TIMEOUT_SEC,
        quiet=True,
    )
    if not args.dry_run:
        if remote_checks.returncode != 0 or "remote_preflight_ok" not in remote_checks.stdout:
            raise PreflightError(
                "Remote camera repository, start/stop scripts, or remote video root check failed."
            )

    acquisition = _query_remote_acquisition(
        camera_host,
        remote_start,
        dry_run=args.dry_run,
        batch_mode=True,
        connect_timeout=SSH_CONNECT_TIMEOUT_SEC,
        command_timeout_sec=SSH_COMMAND_TIMEOUT_SEC,
    )
    known_state = None
    try:
        known_state = load_state(allow_legacy_state=args.allow_legacy_state)
    except CameraControlError:
        known_state = None

    return {
        "camera_host": camera_host,
        "remote_repo": remote_repo,
        "remote_start": remote_start,
        "remote_stop": remote_stop,
        "remote_video_root": remote_video_root,
        "local_output_root": str(local_output_root),
        "acquisition_running": acquisition["running"],
        "acquisition_lines": acquisition["lines"],
        "known_state_session_id": None if known_state is None else known_state.get("session_id"),
    }


def preflight_camera(args) -> int:
    result = _run_preflight_checks(args)
    print("Camera preflight summary:")
    print(f"  Camera host:        {result['camera_host']}")
    print(f"  Remote repo:        {result['remote_repo']}")
    print(f"  Remote start:       {result['remote_start']}")
    print(f"  Remote stop:        {result['remote_stop']}")
    print(f"  Remote video root:  {result['remote_video_root']}")
    print(f"  Local output root:  {result['local_output_root']}")
    if result["acquisition_running"]:
        lines = "\n".join("    " + line for line in result["acquisition_lines"])
        known_session = result["known_state_session_id"]
        extra = f"\nKnown local session ID: {known_session}" if known_session else ""
        raise ExistingAcquisitionError(
            "An existing camera acquisition is already running on Box 152:\n"
            + lines
            + extra
        )
    print("  Acquisition status: idle")
    print("Camera preflight passed.")
    return 0


def start_camera(args) -> int:
    preflight = _run_preflight_checks(args)
    if preflight["acquisition_running"]:
        lines = "\n".join("    " + line for line in preflight["acquisition_lines"])
        known_session = preflight["known_state_session_id"]
        extra = f"\nKnown local session ID: {known_session}" if known_session else ""
        raise ExistingAcquisitionError(
            "Refusing to start because an acquisition is already running on Box 152.\n"
            + lines
            + extra
        )

    state = {
        "created_utc": utc_iso_now(),
        "status": "starting",
        "launch_attempted": False,
        "launch_verified": False,
        "rollback_attempted": False,
        "rollback_succeeded": None,
        "rollback_error": None,
        "camera_host": preflight["camera_host"],
        "framerate": args.framerate,
        "remote_camera_repo": preflight["remote_repo"],
        "remote_camera_start": preflight["remote_start"],
        "remote_camera_stop": preflight["remote_stop"],
        **make_session_paths(args),
    }
    state["remote_output_path"] = state["remote_base_path"]
    local_video_dir = Path(state["local_video_dir"])
    local_video_dir.mkdir(parents=True, exist_ok=True)
    append_event(local_video_dir, "camera_start_requested", state)
    if not args.dry_run:
        save_state(state)
    remote_log = f"{state['remote_video_dir']}/camera_acquisition.log"
    launch_cmd = (
        f"mkdir -p {shlex.quote(state['remote_video_dir'])} && "
        f"cd {shlex.quote(str(state['remote_camera_repo']))} && "
        f"nohup python3 {shlex.quote(str(state['remote_camera_start']))} "
        f"{shlex.quote(state['remote_base_path'])} {int(args.framerate)} "
        f">> {shlex.quote(remote_log)} 2>&1 &"
    )
    state["launch_attempted"] = True
    if not args.dry_run:
        save_state(state)
    try:
        run_ssh(
            str(state["camera_host"]), launch_cmd, dry_run=args.dry_run, batch_mode=True,
            connect_timeout=SSH_CONNECT_TIMEOUT_SEC, command_timeout_sec=SSH_COMMAND_TIMEOUT_SEC,
        )
    except Exception as exc:
        state.update(status="launch_failed", launch_error=f"{type(exc).__name__}: {exc}")
        if not args.dry_run:
            save_state(state)
        raise CameraControlError(f"Camera launch failed before verification: {exc}") from exc
    state.update(status="launched", launch_attempted=True)
    if not args.dry_run:
        save_state(state)
    if not args.dry_run:
        time.sleep(float(args.verify_wait_sec))
    verification_error = None
    acquisition = {"running": False, "lines": []}
    verify = subprocess.CompletedProcess([], 1, "", "")
    try:
        acquisition = _query_remote_acquisition(
            str(state["camera_host"]), str(state["remote_camera_start"]),
            dry_run=args.dry_run, batch_mode=True, connect_timeout=SSH_CONNECT_TIMEOUT_SEC,
            command_timeout_sec=SSH_COMMAND_TIMEOUT_SEC,
        )
        verify_cmd = (
            f"test -d {shlex.quote(state['remote_session_dir'])} && "
            f"test -d {shlex.quote(state['remote_video_dir'])} && "
            "echo camera_start_verified"
        )
        verify = run_ssh(
            str(state["camera_host"]), verify_cmd, check=False, dry_run=args.dry_run,
            batch_mode=True, connect_timeout=SSH_CONNECT_TIMEOUT_SEC,
            command_timeout_sec=SSH_COMMAND_TIMEOUT_SEC, quiet=True,
        )
    except Exception as exc:
        verification_error = f"post-launch verification command failed: {exc}"
    if not args.dry_run and verification_error is None:
        if not acquisition["running"]:
            verification_error = "the acquisition process was not alive after verification"
        elif verify.returncode != 0 or "camera_start_verified" not in verify.stdout:
            verification_error = "the expected remote session directories were not verified"
    if verification_error:
        state.update(status="verification_failed", launch_verified=False, rollback_attempted=True)
        if not args.dry_run:
            save_state(state)
        try:
            rollback = run_ssh(
                str(state["camera_host"]), f"bash {shlex.quote(str(state['remote_camera_stop']))}",
                check=False, batch_mode=True, connect_timeout=SSH_CONNECT_TIMEOUT_SEC,
                command_timeout_sec=SSH_COMMAND_TIMEOUT_SEC, quiet=True,
            )
            after = _query_remote_acquisition(
                str(state["camera_host"]), str(state["remote_camera_start"]),
                batch_mode=True, connect_timeout=SSH_CONNECT_TIMEOUT_SEC,
                command_timeout_sec=SSH_COMMAND_TIMEOUT_SEC,
            )
            succeeded = rollback.returncode == 0 and not after["running"]
            state.update(rollback_succeeded=succeeded,
                         rollback_error=None if succeeded else (rollback.stderr or "acquisition still running after rollback"),
                         rollback_process_lines=after["lines"])
            if not args.dry_run:
                save_state(state)
            if not succeeded:
                raise CameraControlError(
                    f"Camera startup verification failed ({verification_error}); rollback did not stop acquisition. "
                    f"Recovery state retained at {state['state_file_path']}."
                )
        except CameraControlError:
            raise
        except Exception as exc:
            state.update(rollback_succeeded=False, rollback_error=f"{type(exc).__name__}: {exc}")
            if not args.dry_run:
                save_state(state)
            raise CameraControlError(
                f"Camera startup verification failed ({verification_error}); rollback failed: {exc}. "
                f"Recovery state retained at {state['state_file_path']}."
            ) from exc
        raise CameraControlError(f"Camera startup verification failed ({verification_error}); rollback succeeded.")

    state.update(status="recording", launch_verified=True, start_verified_utc=utc_iso_now())
    state["acquisition_status_lines"] = acquisition["lines"]
    append_event(
        local_video_dir,
        "camera_start_returned",
        {
            "verified": True,
            "acquisition_lines": acquisition["lines"],
            "remote_session_dir": state["remote_session_dir"],
            "remote_video_dir": state["remote_video_dir"],
        },
    )
    if not args.dry_run:
        save_state(state)
    print("Camera start command verified.")
    print(f"Camera host:        {state['camera_host']}")
    print(f"Remote session dir: {state['remote_session_dir']}")
    print(f"Local video dir:    {state['local_video_dir']}")
    return 0


def stop_camera(args, state: Optional[dict[str, object]] = None) -> int:
    if state is None:
        state = load_state(allow_legacy_state=args.allow_legacy_state)
    camera_host = resolve_camera_host(args, state)
    local_video_dir = Path(state.get("local_video_dir", resolve_local_output_root(args) / "unknown" / "video"))
    local_video_dir.mkdir(parents=True, exist_ok=True)
    append_event(local_video_dir, "camera_stop_requested", {"camera_host": camera_host})
    run_ssh(
        camera_host,
        f"bash {shlex.quote(resolve_remote_stop(args, state))}",
        check=not args.ignore_stop_errors,
        dry_run=args.dry_run,
        batch_mode=True,
        connect_timeout=SSH_CONNECT_TIMEOUT_SEC,
        command_timeout_sec=SSH_COMMAND_TIMEOUT_SEC,
    )
    append_event(local_video_dir, "camera_stop_returned", {"camera_host": camera_host})
    print("Camera stop command sent.")
    return 0


def stop_camera_recovery(args) -> int:
    camera_host = resolve_camera_host(args)
    remote_start = resolve_remote_start(args)
    acquisition = _query_remote_acquisition(
        camera_host, remote_start, dry_run=args.dry_run, batch_mode=True,
        connect_timeout=SSH_CONNECT_TIMEOUT_SEC, command_timeout_sec=SSH_COMMAND_TIMEOUT_SEC,
    )
    lines = acquisition["lines"]
    if len(lines) != 1:
        if not lines:
            raise CameraControlError("Recovery stop refused: no matching camera acquisition is running.")
        raise CameraControlError("Recovery stop refused: multiple matching camera processes were found; refusing to kill ambiguously.")
    identified = lines[0]
    result = run_ssh(
        camera_host, f"bash {shlex.quote(resolve_remote_stop(args))}", check=False,
        dry_run=args.dry_run, batch_mode=True, connect_timeout=SSH_CONNECT_TIMEOUT_SEC,
        command_timeout_sec=SSH_COMMAND_TIMEOUT_SEC,
    )
    after = _query_remote_acquisition(
        camera_host, remote_start, dry_run=args.dry_run, batch_mode=True,
        connect_timeout=SSH_CONNECT_TIMEOUT_SEC, command_timeout_sec=SSH_COMMAND_TIMEOUT_SEC,
    )
    recovery_dir = resolve_local_output_root(args) / "camera_recovery"
    append_event(recovery_dir, "camera_recovery_stop", {
        "camera_host": camera_host, "remote_start": remote_start,
        "identified_process": identified, "stop_returncode": result.returncode,
        "stopped": not after["running"],
    })
    if result.returncode != 0 or after["running"]:
        raise CameraControlError("Recovery stop failed or the matching acquisition is still running; recovery record retained.")
    print(f"Recovery stop verified for process: {identified}")
    return 0


def preview_camera(args) -> int:
    camera_host = resolve_camera_host(args)
    preview_cmd = (
        "set -e; "
        "cam=$(command -v rpicam-hello || command -v libcamera-hello); "
        "if [ -z \"$cam\" ]; then echo 'No rpicam-hello or libcamera-hello found' >&2; exit 1; fi; "
        "mkdir -p /home/pi/stim_logs; "
        f"nohup \"$cam\" -t 0 --fullscreen >{shlex.quote(REMOTE_CAMERA_PREVIEW_LOG)} 2>&1 & "
        f"echo $! > {shlex.quote(REMOTE_CAMERA_PREVIEW_PID_FILE)}"
    )
    stop_cmd = (
        f"if [ -f {shlex.quote(REMOTE_CAMERA_PREVIEW_PID_FILE)} ]; then "
        f"pid=$(cat {shlex.quote(REMOTE_CAMERA_PREVIEW_PID_FILE)}); "
        "kill \"$pid\" 2>/dev/null || true; "
        "sleep 0.5; "
        "kill -9 \"$pid\" 2>/dev/null || true; "
        f"rm -f {shlex.quote(REMOTE_CAMERA_PREVIEW_PID_FILE)}; "
        "fi"
    )
    print(f"Starting remote camera preview on {camera_host}...")
    run_ssh(
        camera_host,
        preview_cmd,
        dry_run=args.dry_run,
        batch_mode=True,
        connect_timeout=SSH_CONNECT_TIMEOUT_SEC,
        command_timeout_sec=SSH_COMMAND_TIMEOUT_SEC,
    )
    print("Preview started. Type y and Enter to stop it.")
    if not args.dry_run:
        while True:
            try:
                response = input("> ").strip().lower()
            except EOFError:
                response = "y"
            if response == "y":
                break
            print("Preview still running. Type y and Enter to stop.")
        run_ssh(
            camera_host,
            stop_cmd,
            dry_run=args.dry_run,
            batch_mode=True,
            connect_timeout=SSH_CONNECT_TIMEOUT_SEC,
            command_timeout_sec=SSH_COMMAND_TIMEOUT_SEC,
        )
        print("Preview stopped.")
    return 0


def fetch_camera(args, state: Optional[dict[str, object]] = None) -> int:
    if state is None:
        try:
            state = load_state(allow_legacy_state=args.allow_legacy_state)
        except CameraControlError:
            state = build_state_from_args(args)
    camera_host = resolve_camera_host(args, state)
    remote_video_dir = str(state["remote_video_dir"])
    local_video_dir = Path(state["local_video_dir"])
    local_video_dir.mkdir(parents=True, exist_ok=True)
    append_event(
        local_video_dir,
        "camera_fetch_requested",
        {
            "camera_host": camera_host,
            "remote_video_dir": remote_video_dir,
            "local_video_dir": str(local_video_dir),
            "skip_conversion": bool(args.skip_conversion),
        },
    )
    run_rsync(
        camera_host,
        remote_video_dir,
        local_video_dir,
        remove_source_files=not args.keep_source_files,
        dry_run=args.dry_run,
    )
    if not args.keep_source_files:
        run_ssh(
            camera_host,
            f"find {shlex.quote(remote_video_dir)} -maxdepth 1 -type f -name '*.h264' -delete",
            batch_mode=True, connect_timeout=SSH_CONNECT_TIMEOUT_SEC,
            command_timeout_sec=SSH_COMMAND_TIMEOUT_SEC, dry_run=args.dry_run, quiet=True,
        )
    append_event(
        local_video_dir,
        "camera_fetch_returned",
        {
            "camera_host": camera_host,
            "remote_video_dir": remote_video_dir,
            "local_video_dir": str(local_video_dir),
        },
    )
    if not args.skip_conversion:
        append_event(local_video_dir, "camera_conversion_requested", {"local_video_dir": str(local_video_dir)})
        convert_h264_to_mp4(
            local_video_dir,
            framerate=int(state.get("framerate", CAMERA_FRAMERATE)),
            dry_run=args.dry_run,
        )
        append_event(local_video_dir, "camera_conversion_returned", {"local_video_dir": str(local_video_dir)})
    print(f"Fetched camera files to: {local_video_dir}")
    return 0


def convert_camera(args, state: Optional[dict[str, object]] = None) -> int:
    if state is None:
        try:
            state = load_state(allow_legacy_state=args.allow_legacy_state)
        except CameraControlError:
            state = build_state_from_args(args)
    local_video_dir = Path(state["local_video_dir"])
    local_video_dir.mkdir(parents=True, exist_ok=True)
    append_event(local_video_dir, "camera_conversion_requested", {"local_video_dir": str(local_video_dir)})
    convert_h264_to_mp4(
        local_video_dir,
        framerate=int(state.get("framerate", CAMERA_FRAMERATE)),
        dry_run=args.dry_run,
    )
    append_event(local_video_dir, "camera_conversion_returned", {"local_video_dir": str(local_video_dir)})
    print(f"Converted camera files in: {local_video_dir}")
    return 0


def status_camera(args) -> int:
    state = None
    try:
        state = load_state(allow_legacy_state=args.allow_legacy_state)
    except CameraControlError:
        state = None
    camera_host = resolve_camera_host(args, state)
    remote_start = resolve_remote_start(args, state)
    acquisition = _query_remote_acquisition(
        camera_host,
        remote_start,
        dry_run=args.dry_run,
        batch_mode=True,
        connect_timeout=SSH_CONNECT_TIMEOUT_SEC,
        command_timeout_sec=SSH_COMMAND_TIMEOUT_SEC,
    )
    print("Camera status:")
    print(f"  Camera host: {camera_host}")
    if acquisition["running"]:
        print("  Acquisition: running")
        for line in acquisition["lines"]:
            print("   ", line)
    else:
        print("  Acquisition: idle")
    if state is not None:
        print(f"  Last saved session ID: {state.get('session_id')}")
        print(f"  Last local video dir: {state.get('local_video_dir')}")
    return 0


def print_last_state(args) -> int:
    print(json.dumps(load_state(allow_legacy_state=args.allow_legacy_state), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standalone second-Pi camera controller for rpi_visual_stimuli."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--host", "--camera-host", dest="camera_host", default=None, help=f"SSH host for camera Pi. Default: {DEFAULT_CAMERA_HOST}")
    common.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    common.add_argument(
        "--allow-legacy-state",
        action="store_true",
        help=f"Allow fallback to legacy state at {LEGACY_STATE_FILE}.",
    )
    common.add_argument("--remote-video-root", default=REMOTE_VIDEO_ROOT)
    common.add_argument("--local-output-root", default=str(LOCAL_VIDEO_ROOT))

    start = sub.add_parser("start", parents=[common], help="Start remote camera recording.")
    start.add_argument("--mouse-id", required=True, help="Mouse ID for session folder.")
    start.add_argument("--session-id", default=None, help="Optional session ID. Default: mouse_UTCtimestamp.")
    start.add_argument("--framerate", type=int, default=CAMERA_FRAMERATE)
    start.add_argument("--remote-repo", "--remote-camera-repo", dest="remote_camera_repo", default=REMOTE_CAMERA_REPO)
    start.add_argument("--remote-start", "--remote-camera-start", dest="remote_camera_start", default=REMOTE_CAMERA_START)
    start.add_argument("--remote-stop", "--remote-camera-stop", dest="remote_camera_stop", default=REMOTE_CAMERA_STOP)
    start.add_argument("--verify-wait-sec", type=float, default=DEFAULT_VERIFY_WAIT_SEC)
    start.set_defaults(func=start_camera)

    stop = sub.add_parser("stop", parents=[common], help="Stop remote camera recording.")
    stop.add_argument("--remote-stop", "--remote-camera-stop", dest="remote_camera_stop", default=REMOTE_CAMERA_STOP)
    stop.add_argument("--ignore-stop-errors", action="store_true", default=False)
    stop.set_defaults(func=stop_camera)

    recovery = sub.add_parser("stop-recovery", parents=[common], help="Explicitly stop one matching acquisition without local state.")
    recovery.add_argument("--remote-start", "--remote-camera-start", dest="remote_camera_start", default=REMOTE_CAMERA_START)
    recovery.add_argument("--remote-stop", "--remote-camera-stop", dest="remote_camera_stop", default=REMOTE_CAMERA_STOP)
    recovery.set_defaults(func=stop_camera_recovery)

    fetch = sub.add_parser("fetch", parents=[common], help="Fetch last remote camera files with rsync.")
    fetch.add_argument("--mouse-id", default=None, help="Mouse ID if no saved session state exists yet.")
    fetch.add_argument("--session-id", default=None, help="Session ID if no saved session state exists yet.")
    fetch.add_argument("--keep-source-files", action="store_true", help="Keep remote source video files after fetch.")
    fetch.add_argument("--skip-conversion", action="store_true", help="Fetch files only and skip local mp4 conversion.")
    fetch.set_defaults(func=fetch_camera)

    convert = sub.add_parser("convert", parents=[common], help="Convert fetched h264 files to mp4 locally.")
    convert.add_argument("--mouse-id", default=None, help="Mouse ID if no saved session state exists yet.")
    convert.add_argument("--session-id", default=None, help="Session ID if no saved session state exists yet.")
    convert.add_argument("--framerate", type=int, default=CAMERA_FRAMERATE)
    convert.set_defaults(func=convert_camera)

    preview = sub.add_parser("preview", parents=[common], help="Start a live camera preview, then stop it when you type y.")
    preview.set_defaults(func=preview_camera)

    stop_fetch = sub.add_parser("stop-fetch", parents=[common], help="Stop recording, wait, fetch files, and convert them.")
    stop_fetch.add_argument("--mouse-id", default=None, help="Mouse ID if no saved session state exists yet.")
    stop_fetch.add_argument("--session-id", default=None, help="Session ID if no saved session state exists yet.")
    stop_fetch.add_argument("--remote-stop", "--remote-camera-stop", dest="remote_camera_stop", default=REMOTE_CAMERA_STOP)
    stop_fetch.add_argument("--ignore-stop-errors", action="store_true", default=False)
    stop_fetch.add_argument("--keep-source-files", action="store_true", help="Keep remote source video files after fetch.")
    stop_fetch.add_argument("--skip-conversion", action="store_true", help="Stop and fetch without local mp4 conversion.")

    def do_stop_fetch(args):
        try:
            state = load_state(allow_legacy_state=args.allow_legacy_state)
        except CameraControlError:
            state = build_state_from_args(args)
        stop_camera(args, state)
        if not args.dry_run:
            time.sleep(2.0)
        fetch_camera(args, state)
        return 0

    stop_fetch.set_defaults(func=do_stop_fetch)

    status = sub.add_parser("status", parents=[common], help="Check whether camera acquisition is running.")
    status.add_argument("--remote-start", "--remote-camera-start", dest="remote_camera_start", default=REMOTE_CAMERA_START)
    status.set_defaults(func=status_camera)

    preflight = sub.add_parser("preflight", parents=[common], help="Check local tools and remote camera readiness.")
    preflight.add_argument("--remote-repo", "--remote-camera-repo", dest="remote_camera_repo", default=REMOTE_CAMERA_REPO)
    preflight.add_argument("--remote-start", "--remote-camera-start", dest="remote_camera_start", default=REMOTE_CAMERA_START)
    preflight.add_argument("--remote-stop", "--remote-camera-stop", dest="remote_camera_stop", default=REMOTE_CAMERA_STOP)
    preflight.set_defaults(func=preflight_camera)

    last = sub.add_parser("last-state", parents=[common], help="Print the saved camera session state.")
    last.set_defaults(func=print_last_state)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    return int(result) if isinstance(result, int) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CameraControlError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(exc.exit_code)
