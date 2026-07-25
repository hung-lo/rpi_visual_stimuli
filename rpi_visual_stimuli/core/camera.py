from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import time
from typing import Optional, Union

from .config import CameraConfig


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CAMERA_CONTROL_SCRIPT = PROJECT_ROOT / "remote_camera_control.py"


@dataclass(frozen=True)
class CameraCommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class CameraCleanupResult:
    stop_result: Optional[CameraCommandResult]
    fetch_result: Optional[CameraCommandResult]
    convert_result: Optional[CameraCommandResult]
    settle_seconds: float = 0.0
    left_running: bool = False
    cleanup_error: Optional[str] = None


def manual_stop_fetch_command(repo_root: Optional[Union[str, Path]] = None) -> str:
    root = Path(repo_root) if repo_root is not None else PROJECT_ROOT
    return f"cd {root}\npython3 remote_camera_control.py stop-fetch"


def _base_arguments(camera_config: CameraConfig, local_output_root: Union[str, Path]) -> tuple[str, ...]:
    return (
        "--host",
        camera_config.host,
        "--remote-video-root",
        camera_config.remote_video_root,
        "--local-output-root",
        str(local_output_root),
    )


def _preflight_arguments(camera_config: CameraConfig, local_output_root: Union[str, Path]) -> tuple[str, ...]:
    return (
        *_base_arguments(camera_config, local_output_root),
        "--remote-repo",
        camera_config.remote_repo,
        "--remote-start",
        camera_config.remote_start,
        "--remote-stop",
        camera_config.remote_stop,
    )


def _start_arguments(camera_config: CameraConfig, local_output_root: Union[str, Path]) -> tuple[str, ...]:
    return (
        *_preflight_arguments(camera_config, local_output_root),
        "--framerate",
        str(camera_config.framerate),
    )


def _stop_arguments(camera_config: CameraConfig, local_output_root: Union[str, Path]) -> tuple[str, ...]:
    return (
        *_base_arguments(camera_config, local_output_root),
        "--remote-stop",
        camera_config.remote_stop,
    )


def _fetch_arguments(camera_config: CameraConfig, local_output_root: Union[str, Path]) -> tuple[str, ...]:
    return _base_arguments(camera_config, local_output_root)


def _convert_arguments(camera_config: CameraConfig, local_output_root: Union[str, Path]) -> tuple[str, ...]:
    return (
        "--local-output-root",
        str(local_output_root),
        "--framerate",
        str(camera_config.framerate),
    )


def _status_arguments(camera_config: CameraConfig) -> tuple[str, ...]:
    return (
        "--host",
        camera_config.host,
        "--remote-start",
        camera_config.remote_start,
    )


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


def preflight_camera(
    camera_config: CameraConfig,
    local_output_root: Union[str, Path],
    *,
    dry_run: bool = False,
) -> CameraCommandResult:
    return _run_camera_command(
        "preflight",
        *_preflight_arguments(camera_config, local_output_root),
        check=False,
        dry_run=dry_run,
    )


def start_camera(
    mouse_id: str,
    session_id: str,
    camera_config: CameraConfig,
    local_output_root: Union[str, Path],
    *,
    dry_run: bool = False,
) -> CameraCommandResult:
    return _run_camera_command(
        "start",
        "--mouse-id",
        mouse_id,
        "--session-id",
        session_id,
        *_start_arguments(camera_config, local_output_root),
        dry_run=dry_run,
    )


def stop_camera(
    camera_config: CameraConfig,
    local_output_root: Union[str, Path],
    *,
    dry_run: bool = False,
    ignore_errors: bool = False,
) -> CameraCommandResult:
    arguments = [
        "stop",
        *_stop_arguments(camera_config, local_output_root),
    ]
    if ignore_errors:
        arguments.append("--ignore-stop-errors")
    return _run_camera_command(*arguments, check=not ignore_errors, dry_run=dry_run)


def fetch_camera(
    camera_config: CameraConfig,
    local_output_root: Union[str, Path],
    *,
    dry_run: bool = False,
    keep_source_files: bool = False,
    skip_conversion: bool = True,
    check: bool = True,
) -> CameraCommandResult:
    arguments = [
        "fetch",
        *_fetch_arguments(camera_config, local_output_root),
    ]
    if keep_source_files:
        arguments.append("--keep-source-files")
    if skip_conversion:
        arguments.append("--skip-conversion")
    return _run_camera_command(*arguments, check=check, dry_run=dry_run)


def convert_camera(
    camera_config: CameraConfig,
    local_output_root: Union[str, Path],
    *,
    dry_run: bool = False,
    check: bool = True,
) -> CameraCommandResult:
    return _run_camera_command(
        "convert",
        *_convert_arguments(camera_config, local_output_root),
        check=check,
        dry_run=dry_run,
    )


def camera_status(
    camera_config: CameraConfig,
    *,
    dry_run: bool = False,
) -> CameraCommandResult:
    return _run_camera_command(
        "status",
        *_status_arguments(camera_config),
        check=False,
        dry_run=dry_run,
    )


def stop_and_fetch_camera(
    camera_config: CameraConfig,
    local_output_root: Union[str, Path],
    *,
    settle_seconds: float = 2.0,
    dry_run: bool = False,
    keep_source_files: bool = False,
) -> CameraCleanupResult:
    stop_result = None
    fetch_result = None
    convert_result = None
    stop_result = stop_camera(
        camera_config,
        local_output_root,
        dry_run=dry_run,
        ignore_errors=True,
    )
    if not stop_result.succeeded:
        return CameraCleanupResult(
            stop_result=stop_result,
            fetch_result=None,
            convert_result=None,
            settle_seconds=0.0,
            cleanup_error=stop_result.stderr or stop_result.stdout or "camera stop failed",
        )
    if not dry_run and settle_seconds > 0:
        time.sleep(settle_seconds)
    try:
        fetch_result = fetch_camera(
            camera_config,
            local_output_root,
            dry_run=dry_run,
            keep_source_files=keep_source_files,
            skip_conversion=True,
            check=False,
        )
        if not fetch_result.succeeded:
            return CameraCleanupResult(
                stop_result=stop_result,
                fetch_result=fetch_result,
                convert_result=None,
                settle_seconds=float(settle_seconds),
                cleanup_error=fetch_result.stderr or fetch_result.stdout or "camera fetch failed",
            )
        convert_result = convert_camera(
            camera_config,
            local_output_root,
            dry_run=dry_run,
            check=False,
        )
        return CameraCleanupResult(
            stop_result=stop_result,
            fetch_result=fetch_result,
            convert_result=convert_result,
            settle_seconds=float(settle_seconds),
            cleanup_error=None if convert_result.succeeded else (convert_result.stderr or convert_result.stdout or "camera conversion failed"),
        )
    except Exception as exc:
        return CameraCleanupResult(
            stop_result=stop_result,
            fetch_result=fetch_result,
            convert_result=convert_result,
            settle_seconds=float(settle_seconds),
            cleanup_error=f"{type(exc).__name__}: {exc}",
        )
