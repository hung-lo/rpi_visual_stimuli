from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import shutil
import subprocess
from typing import Iterable, Optional, Union


def format_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    amount = float(value)
    unit = units[0]
    for unit in units:
        if abs(amount) < 1024.0 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024.0
    return f"{amount:.1f} {unit}"


def read_meminfo(path: Union[str, Path] = "/proc/meminfo") -> dict[str, int]:
    meminfo: dict[str, int] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        parts = value.strip().split()
        if not parts:
            continue
        numeric = int(parts[0])
        unit = parts[1].lower() if len(parts) > 1 else "b"
        if unit == "kb":
            numeric *= 1024
        meminfo[key] = numeric
    return meminfo


def read_mem_available_bytes(meminfo: Optional[dict[str, int]] = None) -> int:
    meminfo = meminfo or read_meminfo()
    if "MemAvailable" in meminfo:
        return meminfo["MemAvailable"]
    if "MemFree" in meminfo:
        return meminfo["MemFree"]
    raise KeyError("MemAvailable and MemFree are missing from meminfo")


def _coerce_file_size(item: Union[int, str, Path]) -> int:
    if isinstance(item, int):
        return item
    return Path(item).stat().st_size


def nearest_existing_ancestor(path: Union[str, Path]) -> Path:
    candidate = Path(path)
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise FileNotFoundError(
                "No existing ancestor found for target path: {}".format(path)
            )
        candidate = parent
    return candidate


def _backing_mount_info(path: Path) -> dict[str, Optional[str]]:
    try:
        result = subprocess.run(
            ["findmnt", "-T", str(path), "-o", "TARGET,SOURCE,FSTYPE", "-n"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return {
            "backing_mount": None,
            "backing_device": None,
            "filesystem_type": None,
        }
    fields = result.stdout.strip().split(None, 2)
    if len(fields) != 3:
        return {
            "backing_mount": None,
            "backing_device": None,
            "filesystem_type": None,
        }
    return {
        "backing_mount": fields[0],
        "backing_device": fields[1],
        "filesystem_type": fields[2],
    }


def validate_storage_root(
    path: Union[str, Path],
    *,
    require_separate_mount: bool = False,
) -> dict[str, object]:
    storage_root = Path(path)
    if not storage_root.exists():
        raise RuntimeError(
            "Configured output root does not exist: {}".format(storage_root)
        )
    if not storage_root.is_dir():
        raise RuntimeError(
            "Configured output root is not a directory: {}".format(storage_root)
        )
    if not os.access(str(storage_root), os.W_OK):
        raise RuntimeError(
            "Configured output root is not writable: {}".format(storage_root)
        )

    is_mount_point = storage_root.is_mount()
    if require_separate_mount and not is_mount_point:
        raise RuntimeError(
            "Configured output root {} is not an active mount point. "
            "A separate mounted storage root is required by configuration.".format(storage_root)
        )

    usage = shutil.disk_usage(str(storage_root))
    total_bytes = usage.total if hasattr(usage, "total") else usage[0]
    used_bytes = usage.used if hasattr(usage, "used") else usage[1]
    free_bytes = usage.free if hasattr(usage, "free") else usage[2]
    backing_mount = _backing_mount_info(storage_root)
    return {
        "path": str(storage_root),
        "exists": True,
        "writable": True,
        "is_mount_point": is_mount_point,
        "require_separate_mount": require_separate_mount,
        "total_bytes": total_bytes,
        "used_bytes": used_bytes,
        "free_bytes": free_bytes,
        **backing_mount,
    }


@dataclass(frozen=True)
class MemoryCheckResult:
    total_memory_bytes: Optional[int]
    available_memory_bytes: int
    total_raw_file_bytes: int
    overhead_factor: float
    safety_margin_bytes: int
    required_bytes: int
    shortfall_bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "total_memory_bytes": self.total_memory_bytes,
            "available_memory_bytes": self.available_memory_bytes,
            "total_raw_file_bytes": self.total_raw_file_bytes,
            "overhead_factor": self.overhead_factor,
            "safety_margin_bytes": self.safety_margin_bytes,
            "required_bytes": self.required_bytes,
            "shortfall_bytes": self.shortfall_bytes,
        }


def check_memory_before_loading(
    raw_files_or_sizes: Iterable[Union[int, str, Path]],
    *,
    available_memory_bytes: Optional[int] = None,
    meminfo_path: Union[str, Path] = "/proc/meminfo",
    overhead_factor: float = 1.15,
    safety_margin_bytes: int = 0,
    suggestion: str = "",
) -> MemoryCheckResult:
    raw_sizes = [_coerce_file_size(item) for item in raw_files_or_sizes]
    total_raw_file_bytes = sum(raw_sizes)
    meminfo = None
    if available_memory_bytes is None:
        meminfo = read_meminfo(meminfo_path)
        available_memory_bytes = read_mem_available_bytes(meminfo)
    total_memory_bytes = meminfo.get("MemTotal") if meminfo else None
    required_bytes = math.ceil(total_raw_file_bytes * overhead_factor) + safety_margin_bytes
    shortfall_bytes = max(0, required_bytes - available_memory_bytes)
    result = MemoryCheckResult(
        total_memory_bytes=total_memory_bytes,
        available_memory_bytes=available_memory_bytes,
        total_raw_file_bytes=total_raw_file_bytes,
        overhead_factor=overhead_factor,
        safety_margin_bytes=safety_margin_bytes,
        required_bytes=required_bytes,
        shortfall_bytes=shortfall_bytes,
    )
    if shortfall_bytes > 0:
        message = (
            "Insufficient memory for raw loading: "
            f"total raw size={format_bytes(total_raw_file_bytes)}, "
            f"available={format_bytes(available_memory_bytes)}, "
            f"overhead factor={overhead_factor:.2f}, "
            f"safety margin={format_bytes(safety_margin_bytes)}, "
            f"required={format_bytes(required_bytes)}, "
            f"shortfall={format_bytes(shortfall_bytes)}."
        )
        if suggestion:
            message += f" {suggestion}"
        raise MemoryError(message)
    return result


@dataclass(frozen=True)
class DiskCheckResult:
    target_path: Path
    disk_check_path: Path
    free_bytes: int
    required_bytes: int
    margin_bytes: int
    required_total_bytes: int
    shortfall_bytes: int


def check_disk_space_before_build(
    target_path: Union[str, Path],
    *,
    required_bytes: int,
    margin_bytes: int = 0,
) -> DiskCheckResult:
    path = Path(target_path)
    disk_check_path = nearest_existing_ancestor(path)
    usage = shutil.disk_usage(str(disk_check_path))
    free_bytes = usage.free if hasattr(usage, "free") else usage[2]
    required_bytes = int(required_bytes)
    margin_bytes = int(margin_bytes)
    total_required = required_bytes + margin_bytes
    shortfall = max(0, total_required - free_bytes)
    result = DiskCheckResult(
        target_path=path,
        disk_check_path=disk_check_path,
        free_bytes=free_bytes,
        required_bytes=required_bytes,
        margin_bytes=margin_bytes,
        required_total_bytes=total_required,
        shortfall_bytes=shortfall,
    )
    if shortfall > 0:
        raise OSError(
            "Insufficient free disk space for cache build. "
            "Disk checked at: {}. "
            "Free: {} bytes. "
            "Required build bytes: {}. "
            "Safety margin: {}. "
            "Shortfall: {} bytes.".format(
                disk_check_path,
                free_bytes,
                required_bytes,
                margin_bytes,
                shortfall,
            )
        )
    return result
