from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
from typing import Any, Optional, Union


def atomic_write_json(path: Union[str, Path], payload: dict[str, Any]) -> None:
    final_path = Path(path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=final_path.parent,
        prefix=final_path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(serialized)
        handle.flush()
        os.fsync(handle.fileno())
        temp_name = handle.name
    os.replace(temp_name, final_path)


def update_session_metadata(path: Union[str, Path], payload: Optional[dict[str, Any]] = None, **updates: Any) -> dict[str, Any]:
    metadata_path = Path(path)
    merged: dict[str, Any] = {}
    if metadata_path.exists():
        merged.update(json.loads(metadata_path.read_text(encoding="utf-8")))
    if payload:
        merged.update(payload)
    merged.update(updates)
    atomic_write_json(metadata_path, merged)
    return merged


def sha256_path(path: Union[str, Path]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_git_commit(repo_root: Union[str, Path]) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


def get_git_status_short(repo_root: Union[str, Path]) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _module_details(module_name: str) -> dict[str, Optional[str]]:
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return {"version": None, "path": None}
    return {
        "version": getattr(module, "__version__", None),
        "path": getattr(module, "__file__", None),
    }


def collect_runtime_environment(
    repo_root: Union[str, Path],
    system_config_path: Union[str, Path],
    *,
    rpg_module: Any = None,
) -> dict[str, object]:
    repo_root = Path(repo_root)
    config_path = Path(system_config_path)
    dirty_status = get_git_status_short(repo_root)
    numpy_details = _module_details("numpy")
    pillow_details = _module_details("PIL")
    if rpg_module is None:
        rpg_details = _module_details("rpg")
    else:
        rpg_details = {
            "version": getattr(rpg_module, "__version__", None),
            "path": getattr(rpg_module, "__file__", None),
        }
    return {
        "hostname": socket.gethostname(),
        "python_executable": sys.executable,
        "python_version": sys.version.replace("\n", " "),
        "system_config_path": str(config_path.resolve()),
        "system_config_sha256": sha256_path(config_path),
        "repository_dirty": bool(dirty_status),
        "repository_status_short": dirty_status,
        "numpy_version": numpy_details["version"],
        "numpy_path": numpy_details["path"],
        "pillow_version": pillow_details["version"],
        "pillow_path": pillow_details["path"],
        "rpg_version": rpg_details["version"],
        "rpg_path": rpg_details["path"],
    }


def read_source_provenance(path: Union[str, Path]) -> dict[str, str]:
    content = Path(path).read_text(encoding="utf-8")
    matches = re.findall(r"^\s*-\s*([a-zA-Z0-9_]+):\s*`?([^`\n]+)`?\s*$", content, re.MULTILINE)
    return {key: value.strip() for key, value in matches}
