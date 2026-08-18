from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Optional, Union

from .metadata import atomic_write_json
from .raw_conversion import sha256_file


MANIFEST_FILENAME = "manifest.json"


@dataclass(frozen=True)
class CacheValidationResult:
    valid: bool
    cache_dir: Path
    manifest: Optional[dict[str, Any]]
    reason: Optional[str] = None


def stable_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(stable_json_dumps(payload).encode("utf-8")).hexdigest()


def expected_file_entry(path: Union[str, Path], *, checksum: Optional[str] = None) -> dict[str, Any]:
    actual_path = Path(path)
    entry = {"size_bytes": actual_path.stat().st_size}
    if checksum is not None:
        entry["sha256"] = checksum
    return entry


def write_manifest(cache_dir: Union[str, Path], manifest: dict[str, Any]) -> Path:
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    manifest_path = cache_path / MANIFEST_FILENAME
    atomic_write_json(manifest_path, manifest)
    return manifest_path


def load_manifest(cache_dir: Union[str, Path]) -> dict[str, Any]:
    manifest_path = Path(cache_dir) / MANIFEST_FILENAME
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def validate_cache(
    cache_dir: Union[str, Path],
    *,
    require_checksums: bool = False,
    expected_cache_hash: Optional[str] = None,
) -> CacheValidationResult:
    cache_path = Path(cache_dir)
    manifest_path = cache_path / MANIFEST_FILENAME
    if not manifest_path.exists():
        return CacheValidationResult(False, cache_path, None, "missing manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_cache_hash = manifest.get("cache_hash")
    if manifest_cache_hash:
        hash_to_validate = cache_path.name if expected_cache_hash is None else str(expected_cache_hash)
        if manifest_cache_hash != hash_to_validate:
            if expected_cache_hash is None:
                reason = (
                    "Final cache manifest hash does not match canonical directory name: "
                    "manifest={!r}, directory={!r}".format(manifest_cache_hash, cache_path.name)
                )
            else:
                reason = (
                    "Staging cache manifest hash does not match expected canonical hash: "
                    "manifest={!r}, expected={!r}, staging_directory={!r}".format(
                        manifest_cache_hash,
                        hash_to_validate,
                        cache_path,
                    )
                )
            return CacheValidationResult(False, cache_path, manifest, reason)
    expected_files = manifest.get("expected_files", {})
    if not isinstance(expected_files, dict):
        return CacheValidationResult(False, cache_path, manifest, "expected_files is not a mapping")
    for relative_path, expected in expected_files.items():
        path = cache_path / relative_path
        if not path.exists():
            return CacheValidationResult(False, cache_path, manifest, f"missing expected file {relative_path}")
        actual_size = path.stat().st_size
        if actual_size <= 0:
            return CacheValidationResult(False, cache_path, manifest, f"zero-byte file {relative_path}")
        if expected.get("size_bytes") != actual_size:
            return CacheValidationResult(False, cache_path, manifest, f"size mismatch for {relative_path}")
        expected_sha = expected.get("sha256")
        if expected_sha:
            if sha256_file(path) != expected_sha:
                return CacheValidationResult(False, cache_path, manifest, f"checksum mismatch for {relative_path}")
        elif require_checksums:
            return CacheValidationResult(False, cache_path, manifest, f"missing checksum for {relative_path}")
    return CacheValidationResult(True, cache_path, manifest, None)


def copy_manifest_to_session(cache_dir: Union[str, Path], destination_path: Union[str, Path]) -> Path:
    source = Path(cache_dir) / MANIFEST_FILENAME
    destination = Path(destination_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination
