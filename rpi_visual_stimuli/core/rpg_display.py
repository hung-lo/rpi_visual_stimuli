from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

from .config import SystemConfig
from .timestamps import capture_timestamp


def import_rpg_or_raise():
    try:
        import rpg
    except ImportError as exc:
        raise RuntimeError(
            "The rpg package is not installed. Install the SjulsonLab rpg repo on the Raspberry Pi first."
        ) from exc
    return rpg


def open_screen(system_config: SystemConfig):
    rpg = import_rpg_or_raise()
    return rpg.Screen(
        (system_config.screen.width_px, system_config.screen.height_px),
        background=system_config.screen.background_gray_u8,
        colormode=system_config.screen.colormode,
    )


def load_raws(screen: Any, key_to_path: dict[str, str | Path]) -> dict[str, Any]:
    return {key: screen.load_raw(str(path)) for key, path in key_to_path.items()}


@dataclass(frozen=True)
class DisplayTiming:
    display_request_unix_ns: int
    display_return_unix_ns: int
    display_return_utc_iso: str
    display_request_perf_counter_ns: int
    display_return_perf_counter_ns: int
    display_call_duration_sec: float
    start_time_unix: float | None
    mean_interframe_us: float | None
    stddev_interframe_us: float | None

    def to_event_fields(self) -> dict[str, int | float | str | None]:
        return {
            "display_request_unix_ns": self.display_request_unix_ns,
            "display_return_unix_ns": self.display_return_unix_ns,
            "display_return_utc_iso": self.display_return_utc_iso,
            "display_request_perf_counter_ns": self.display_request_perf_counter_ns,
            "display_return_perf_counter_ns": self.display_return_perf_counter_ns,
            "display_call_duration_sec": self.display_call_duration_sec,
            "start_time_unix": self.start_time_unix,
            "mean_interframe_us": self.mean_interframe_us,
            "stddev_interframe_us": self.stddev_interframe_us,
        }


def extract_rpg_performance(perf: Any) -> dict[str, float | None]:
    if perf is None:
        return {
            "start_time_unix": None,
            "mean_interframe_us": None,
            "stddev_interframe_us": None,
        }
    if isinstance(perf, dict):
        getter = perf.get
    else:
        getter = lambda name: getattr(perf, name, None)
    return {
        "start_time_unix": getter("start_time_unix"),
        "mean_interframe_us": getter("mean_interframe_us"),
        "stddev_interframe_us": getter("stddev_interframe_us"),
    }


def display_raw_with_timing(screen: Any, loaded_raw: Any) -> DisplayTiming:
    request = capture_timestamp()
    request_perf_counter_ns = time.perf_counter_ns()
    perf = screen.display_raw(loaded_raw)
    return_perf_counter_ns = time.perf_counter_ns()
    returned = capture_timestamp()
    perf_fields = extract_rpg_performance(perf)
    return DisplayTiming(
        display_request_unix_ns=int(request["unix_ns"]),
        display_return_unix_ns=int(returned["unix_ns"]),
        display_return_utc_iso=str(returned["utc_iso"]),
        display_request_perf_counter_ns=request_perf_counter_ns,
        display_return_perf_counter_ns=return_perf_counter_ns,
        display_call_duration_sec=(return_perf_counter_ns - request_perf_counter_ns) / 1_000_000_000.0,
        start_time_unix=perf_fields["start_time_unix"],
        mean_interframe_us=perf_fields["mean_interframe_us"],
        stddev_interframe_us=perf_fields["stddev_interframe_us"],
    )
