from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable, Optional

from .config import default_system_config_path


InputFn = Callable[[str], str]


def build_common_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    camera_group = parser.add_mutually_exclusive_group()
    camera_group.add_argument("--camera", action="store_true", help="Enable face-camera recording without asking.")
    camera_group.add_argument("--no-camera", action="store_true", help="Disable face-camera recording without asking.")
    parser.add_argument(
        "--system-config",
        default=str(default_system_config_path()),
        help="Path to the shared system configuration JSON.",
    )
    parser.add_argument("--preview-only", action="store_true", help="Build previews and plan the session without using RPG or camera.")
    parser.add_argument("--build-cache-only", action="store_true", help="Build and validate the persistent cache, then exit.")
    parser.add_argument("--dry-run", action="store_true", help="Validate prompts and planned actions without hardware side effects.")
    parser.add_argument("--test", action="store_true", help="Use the short hardware-test protocol settings.")
    return parser


def prompt_text(prompt: str, *, input_fn: InputFn = input, default: Optional[str] = None) -> str:
    response = input_fn(prompt).strip()
    if response:
        return response
    return default or ""


def prompt_yes_no(prompt: str, *, default_yes: bool = True, input_fn: InputFn = input) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"
    response = input_fn(f"{prompt} {suffix}: ").strip().lower()
    if not response:
        return default_yes
    if response in {"y", "yes"}:
        return True
    if response in {"n", "no"}:
        return False
    raise ValueError("please answer y or n")


def prompt_int(prompt: str, *, default: int, input_fn: InputFn = input) -> int:
    response = input_fn(f"{prompt} [{default}]: ").strip()
    if not response:
        return default
    return int(response)


def prompt_float(prompt: str, *, default: float, input_fn: InputFn = input) -> float:
    response = input_fn(f"{prompt} [{default}]: ").strip()
    if not response:
        return default
    return float(response)


def resolve_camera_enabled(args: argparse.Namespace, *, input_fn: InputFn = input) -> bool:
    if args.camera:
        return True
    if args.no_camera:
        return False
    return prompt_yes_no("Record face camera?", default_yes=True, input_fn=input_fn)


def ensure_existing_path(path_text: str) -> Path:
    path = Path(path_text)
    if not path.exists():
        raise FileNotFoundError(path)
    return path
