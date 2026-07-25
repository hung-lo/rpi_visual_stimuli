from __future__ import annotations

from pathlib import Path

from rpi_visual_stimuli.core.config import load_system_config


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_repo_system_config():
    return load_system_config(repo_root() / "config" / "system_config.json")
