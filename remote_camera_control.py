#!/usr/bin/env python3
"""
Standalone second-Pi camera controller for rpi_visual_stimuli.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
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

PROJECT_ROOT = Path(__file__).resolve().parent
STATE_FILE = LOCAL_VIDEO_ROOT / ".rpi_visual_stimuli_camera_session.json"
LEGACY_STATE_FILE = LOCAL_VIDEO_ROOT / ".last_remote_camera_session.json"


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


def run_cmd(cmd: list[str], *, check: bool = True, dry_run: bool = False):
    print("+ " + " ".join(shlex.quote(part) for part in cmd))
    if dry_run:
        return subprocess.CompletedProcess(cmd, 0, "", "")
    result = subprocess.run(cmd, check=False, text=True, capture_output=True)
    if check and result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        raise RuntimeError(f"command failed with exit code {result.returncode}: {' '.join(cmd)}")
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result


def run_ssh(camera_host: str, remote_cmd: str, *, check: bool = True, dry_run: bool = False):
    return run_cmd(["ssh", camera_host, remote_cmd], check=check, dry_run=dry_run)


def run_rsync(
    camera_host: str,
    remote_dir: str,
    local_dir: Path,
    *,
    remove_source_files: bool = True,
    dry_run: bool = False,
):
    local_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["rsync", "-av", "--progress"]
    if remove_source_files:
        cmd.append("--remove-source-files")
    cmd.extend([f"{camera_host}:{remote_dir.rstrip('/')}/", str(local_dir) + "/"])
    return run_cmd(cmd, check=True, dry_run=dry_run)


def convert_h264_to_mp4(local_video_dir: Path, *, framerate: int = CAMERA_FRAMERATE, dry_run: bool = False) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        print("ffmpeg not found; skipping mp4 conversion.")
        return
    h264_files = sorted(local_video_dir.glob("*.h264"))
    if not h264_files:
        print("No .h264 files found for mp4 conversion.")
        return
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
            raise RuntimeError(f"ffmpeg conversion failed for {input_path.name}")
        print(f"Converted {input_path.name} -> {output_path.name}")


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
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Saved state: {STATE_FILE}")


def load_state(*, allow_legacy_state: bool = False) -> dict[str, object]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if allow_legacy_state and LEGACY_STATE_FILE.exists():
        state = json.loads(LEGACY_STATE_FILE.read_text(encoding="utf-8"))
        if state.get("mouse_id") and state.get("session_id"):
            session_id = state["session_id"]
            local_session_dir = (LOCAL_VIDEO_ROOT / session_id).resolve()
            state["local_session_dir"] = str(local_session_dir)
            state["local_video_dir"] = str(local_session_dir / "video")
        return state
    raise RuntimeError(
        f"No saved camera session state found at {STATE_FILE}. "
        f"Legacy state at {LEGACY_STATE_FILE} is ignored unless --allow-legacy-state is passed."
    )


def resolve_camera_host(args, state: Optional[dict[str, object]] = None) -> str:
    if getattr(args, "camera_host", None):
        return args.camera_host
    if state and state.get("camera_host"):
        return str(state["camera_host"])
    return DEFAULT_CAMERA_HOST


def make_session_paths(args) -> dict[str, str]:
    mouse_id = sanitize_id(args.mouse_id)
    if not mouse_id:
        raise RuntimeError("mouse ID cannot be empty")
    session_id = sanitize_id(args.session_id) if args.session_id else make_session_name(mouse_id, utc_label())
    local_session_dir = (LOCAL_VIDEO_ROOT / session_id).resolve()
    local_video_dir = local_session_dir / "video"
    remote_session_dir = f"{REMOTE_VIDEO_ROOT}/{session_id}"
    remote_video_dir = f"{remote_session_dir}/video"
    remote_base_path = f"{remote_video_dir}/{session_id}"
    return {
        "mouse_id": mouse_id,
        "session_id": session_id,
        "local_session_dir": str(local_session_dir),
        "local_video_dir": str(local_video_dir),
        "remote_session_dir": remote_session_dir,
        "remote_video_dir": remote_video_dir,
        "remote_base_path": remote_base_path,
    }


def build_state_from_args(args) -> dict[str, object]:
    if not getattr(args, "mouse_id", None):
        raise RuntimeError("Pass --mouse-id when no saved state exists.")
    if not getattr(args, "session_id", None):
        raise RuntimeError("Pass --session-id when no saved state exists.")
    return {
        "created_utc": utc_iso_now(),
        "camera_host": resolve_camera_host(args),
        "framerate": getattr(args, "framerate", CAMERA_FRAMERATE),
        "remote_camera_repo": getattr(args, "remote_camera_repo", REMOTE_CAMERA_REPO),
        "remote_camera_start": getattr(args, "remote_camera_start", REMOTE_CAMERA_START),
        "remote_camera_stop": getattr(args, "remote_camera_stop", REMOTE_CAMERA_STOP),
        **make_session_paths(args),
    }


def start_camera(args):
    camera_host = resolve_camera_host(args)
    state = {
        "created_utc": utc_iso_now(),
        "camera_host": camera_host,
        "framerate": args.framerate,
        "remote_camera_repo": args.remote_camera_repo,
        "remote_camera_start": args.remote_camera_start,
        "remote_camera_stop": args.remote_camera_stop,
        **make_session_paths(args),
    }
    local_video_dir = Path(state["local_video_dir"])
    local_video_dir.mkdir(parents=True, exist_ok=True)
    append_event(local_video_dir, "camera_start_requested", state)
    remote_log = f"{state['remote_video_dir']}/camera_acquisition.log"
    safe_start_pattern = "[v]ideo_acquisition/start_acquisition.py"
    cleanup_cmd = f"pkill -f {shlex.quote(safe_start_pattern)} || true"
    launch_cmd = (
        f"mkdir -p {shlex.quote(state['remote_video_dir'])} && "
        f"cd {shlex.quote(args.remote_camera_repo)} && "
        f"nohup python3 {shlex.quote(args.remote_camera_start)} "
        f"{shlex.quote(state['remote_base_path'])} {int(args.framerate)} "
        f">> {shlex.quote(remote_log)} 2>&1 &"
    )
    run_ssh(camera_host, cleanup_cmd, dry_run=args.dry_run)
    run_ssh(camera_host, launch_cmd, dry_run=args.dry_run)
    append_event(local_video_dir, "camera_start_returned", state)
    save_state(state)
    print("Camera start command sent.")
    print(f"Camera host:      {camera_host}")
    print(f"Remote video dir: {state['remote_video_dir']}")
    print(f"Local video dir:  {local_video_dir}")
    return state


def stop_camera(args, state: Optional[dict[str, object]] = None):
    if state is None:
        state = load_state(allow_legacy_state=args.allow_legacy_state)
    camera_host = resolve_camera_host(args, state)
    local_video_dir = Path(state.get("local_video_dir", LOCAL_VIDEO_ROOT / "unknown" / "video"))
    local_video_dir.mkdir(parents=True, exist_ok=True)
    append_event(local_video_dir, "camera_stop_requested", {"camera_host": camera_host})
    remote_stop = (
        getattr(args, "remote_camera_stop", None)
        or state.get("remote_camera_stop")
        or REMOTE_CAMERA_STOP
    )
    run_ssh(
        camera_host,
        f"bash {shlex.quote(str(remote_stop))}",
        check=not args.ignore_stop_errors,
        dry_run=args.dry_run,
    )
    append_event(local_video_dir, "camera_stop_returned", {"camera_host": camera_host})
    print("Camera stop command sent.")
    return state


def preview_camera(args):
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
    run_ssh(camera_host, preview_cmd, dry_run=args.dry_run)
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
        run_ssh(camera_host, stop_cmd, dry_run=args.dry_run)
        print("Preview stopped.")


def fetch_camera(args, state: Optional[dict[str, object]] = None):
    if state is None:
        try:
            state = load_state(allow_legacy_state=args.allow_legacy_state)
        except RuntimeError:
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
        },
    )
    run_rsync(
        camera_host,
        remote_video_dir,
        local_video_dir,
        remove_source_files=not args.keep_source_files,
        dry_run=args.dry_run,
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
    append_event(local_video_dir, "camera_conversion_requested", {"local_video_dir": str(local_video_dir)})
    convert_h264_to_mp4(
        local_video_dir,
        framerate=int(state.get("framerate", CAMERA_FRAMERATE)),
        dry_run=args.dry_run,
    )
    append_event(local_video_dir, "camera_conversion_returned", {"local_video_dir": str(local_video_dir)})
    print(f"Fetched camera files to: {local_video_dir}")
    return state


def status_camera(args):
    state = None
    try:
        state = load_state(allow_legacy_state=args.allow_legacy_state)
    except RuntimeError:
        pass
    camera_host = resolve_camera_host(args, state)
    safe_start_pattern = "[v]ideo_acquisition/start_acquisition.py"
    remote_cmd = (
        "echo '--- camera acquisition processes ---'; "
        f"pgrep -af {shlex.quote(safe_start_pattern)} || true; "
        "echo '--- recent camera logs ---'; "
        "find /home/pi/stim_logs -name 'camera_acquisition.log' -type f 2>/dev/null | tail -n 5 || true"
    )
    run_ssh(camera_host, remote_cmd, dry_run=args.dry_run)


def print_last_state(args):
    print(json.dumps(load_state(allow_legacy_state=args.allow_legacy_state), indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standalone second-Pi camera controller for rpi_visual_stimuli."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--camera-host", default=None, help=f"SSH host for camera Pi. Default: {DEFAULT_CAMERA_HOST}")
    common.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    common.add_argument(
        "--allow-legacy-state",
        action="store_true",
        help=f"Allow fallback to legacy state at {LEGACY_STATE_FILE}.",
    )

    start = sub.add_parser("start", parents=[common], help="Start remote camera recording.")
    start.add_argument("--mouse-id", required=True, help="Mouse ID for session folder.")
    start.add_argument("--session-id", default=None, help="Optional session ID. Default: mouse_UTCtimestamp.")
    start.add_argument("--framerate", type=int, default=CAMERA_FRAMERATE)
    start.add_argument("--remote-camera-repo", default=REMOTE_CAMERA_REPO)
    start.add_argument("--remote-camera-start", default=REMOTE_CAMERA_START)
    start.add_argument("--remote-camera-stop", default=REMOTE_CAMERA_STOP)
    start.set_defaults(func=start_camera)

    stop = sub.add_parser("stop", parents=[common], help="Stop remote camera recording.")
    stop.add_argument("--remote-camera-stop", default=REMOTE_CAMERA_STOP)
    stop.add_argument("--ignore-stop-errors", action="store_true", default=False)
    stop.set_defaults(func=stop_camera)

    fetch = sub.add_parser("fetch", parents=[common], help="Fetch last remote camera files with rsync.")
    fetch.add_argument("--mouse-id", default=None, help="Mouse ID if no saved session state exists yet.")
    fetch.add_argument("--session-id", default=None, help="Session ID if no saved session state exists yet.")
    fetch.add_argument("--keep-source-files", action="store_true", help="Keep remote source video files after fetch.")
    fetch.set_defaults(func=fetch_camera)

    preview = sub.add_parser("preview", parents=[common], help="Start a live camera preview, then stop it when you type y.")
    preview.set_defaults(func=preview_camera)

    stop_fetch = sub.add_parser("stop-fetch", parents=[common], help="Stop recording, wait, then fetch files.")
    stop_fetch.add_argument("--mouse-id", default=None, help="Mouse ID if no saved session state exists yet.")
    stop_fetch.add_argument("--session-id", default=None, help="Session ID if no saved session state exists yet.")
    stop_fetch.add_argument("--remote-camera-stop", default=REMOTE_CAMERA_STOP)
    stop_fetch.add_argument("--ignore-stop-errors", action="store_true", default=False)
    stop_fetch.add_argument("--keep-source-files", action="store_true", help="Keep remote source video files after fetch.")

    def do_stop_fetch(args):
        try:
            state = load_state(allow_legacy_state=args.allow_legacy_state)
        except RuntimeError:
            state = build_state_from_args(args)
        stop_camera(args, state)
        time.sleep(2.0)
        fetch_camera(args, state)

    stop_fetch.set_defaults(func=do_stop_fetch)

    status = sub.add_parser("status", parents=[common], help="Check whether camera acquisition is running.")
    status.set_defaults(func=status_camera)

    last = sub.add_parser("last-state", parents=[common], help="Print the saved camera session state.")
    last.set_defaults(func=print_last_state)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
