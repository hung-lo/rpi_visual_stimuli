from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import shutil
from typing import Iterable


def format_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    amount = float(value)
    unit = units[0]
    for unit in units:
        if abs(amount) < 1024.0 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024.0
    return f"{amount:.1f} {unit}"


def read_meminfo(path: str | Path = "/proc/meminfo") -> dict[str, int]:
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


def read_mem_available_bytes(meminfo: dict[str, int] | None = None) -> int:
    meminfo = meminfo or read_meminfo()
    if "MemAvailable" in meminfo:
        return meminfo["MemAvailable"]
    if "MemFree" in meminfo:
        return meminfo["MemFree"]
    raise KeyError("MemAvailable and MemFree are missing from meminfo")


def _coerce_file_size(item: int | str | Path) -> int:
    if isinstance(item, int):
        return item
    return Path(item).stat().st_size


@dataclass(frozen=True)
class MemoryCheckResult:
    total_memory_bytes: int | None
    available_memory_bytes: int
    total_raw_file_bytes: int
    overhead_factor: float
    safety_margin_bytes: int
    required_bytes: int
    shortfall_bytes: int

    def to_dict(self) -> dict[str, int | float | None]:
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
    raw_files_or_sizes: Iterable[int | str | Path],
    *,
    available_memory_bytes: int | None = None,
    meminfo_path: str | Path = "/proc/meminfo",
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
    free_bytes: int
    required_bytes: int
    margin_bytes: int
    shortfall_bytes: int


def check_disk_space_before_build(
    target_path: str | Path,
    *,
    required_bytes: int,
    margin_bytes: int = 0,
) -> DiskCheckResult:
    path = Path(target_path)
    usage = shutil.disk_usage(path if path.exists() else path.parent)
    total_required = required_bytes + margin_bytes
    shortfall = max(0, total_required - usage.free)
    result = DiskCheckResult(
        target_path=path,
        free_bytes=usage.free,
        required_bytes=required_bytes,
        margin_bytes=margin_bytes,
        shortfall_bytes=shortfall,
    )
    if shortfall > 0:
        raise OSError(
            "Insufficient disk space: "
            f"free={format_bytes(usage.free)}, required={format_bytes(required_bytes)}, "
            f"margin={format_bytes(margin_bytes)}, shortfall={format_bytes(shortfall)}."
        )
    return result
