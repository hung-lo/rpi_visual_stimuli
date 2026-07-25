from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Iterable, Mapping, Union

from .timestamps import capture_timestamp


SHARED_EVENT_FIELDS = [
    "utc_iso",
    "unix_time_utc_sec",
    "event_type",
    "display_request_unix_ns",
    "display_return_unix_ns",
    "display_return_utc_iso",
    "display_request_perf_counter_ns",
    "display_return_perf_counter_ns",
    "display_call_duration_sec",
    "start_time_unix",
    "mean_interframe_us",
    "stddev_interframe_us",
    "planned_duration_sec",
    "raw_path",
    "notes",
]


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _flush(handle, *, fsync: bool) -> None:
    handle.flush()
    if fsync:
        os.fsync(handle.fileno())


def write_csv(path: Union[str, Path], rows: Iterable[Mapping[str, object]], fieldnames: list[str], *, fsync: bool = False) -> None:
    csv_path = Path(path)
    _ensure_dir(csv_path)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})
        _flush(handle, fsync=fsync)


def append_csv_row(path: Union[str, Path], row: Mapping[str, object], fieldnames: list[str], *, fsync: bool = False) -> None:
    csv_path = Path(path)
    _ensure_dir(csv_path)
    exists = csv_path.exists()
    payload = dict(row)
    if not payload.get("utc_iso") or not payload.get("unix_time_utc_sec"):
        captured = capture_timestamp()
        payload.setdefault("utc_iso", captured["utc_iso"])
        payload.setdefault("unix_time_utc_sec", captured["unix_sec"])
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow({name: payload.get(name, "") for name in fieldnames})
        _flush(handle, fsync=fsync)
