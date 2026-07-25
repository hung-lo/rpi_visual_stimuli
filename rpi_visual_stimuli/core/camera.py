from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CAMERA_CONTROL_SCRIPT = PROJECT_ROOT / "remote_camera_control.py"


@dataclass(frozen=True)
class CameraCommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def manual_stop_fetch_command(repo_root: str | Path | None = None) -> str:
    root = Path(repo_root) if repo_root is not None else PROJECT_ROOT
    return f"cd {root}\npython3 remote_camera_control.py stop-fetch"


def _run_camera_command(*arguments: str, check: bool = True, dry_run: bool = False) -> CameraCommandResult:
    command = (sys.executable, str(CAMERA_CONTROL_SCRIPT), *arguments)
    if dry_run:
        return CameraCommandResult(command=command, returncode=0, stdout="", stderr="")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    wrapped = CameraCommandResult(
        command=command,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"camera command failed with exit code {result.returncode}: {' '.join(command)}\n"
            f"{result.stderr or result.stdout}"
        )
    return wrapped


def start_camera(mouse_id: str, session_id: str, *, dry_run: bool = False) -> CameraCommandResult:
    return _run_camera_command("start", "--mouse-id", mouse_id, "--session-id", session_id, dry_run=dry_run)


def stop_camera(*, dry_run: bool = False) -> CameraCommandResult:
    return _run_camera_command("stop", dry_run=dry_run)


def fetch_camera(*, dry_run: bool = False) -> CameraCommandResult:
    return _run_camera_command("fetch", dry_run=dry_run)


def stop_and_fetch_camera(*, dry_run: bool = False) -> CameraCommandResult:
    return _run_camera_command("stop-fetch", dry_run=dry_run)
