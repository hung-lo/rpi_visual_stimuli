from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
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


def read_source_provenance(path: Union[str, Path]) -> dict[str, str]:
    content = Path(path).read_text(encoding="utf-8")
    matches = re.findall(r"^\s*-\s*([a-zA-Z0-9_]+):\s*`?([^`\n]+)`?\s*$", content, re.MULTILINE)
    return {key: value.strip() for key, value in matches}
