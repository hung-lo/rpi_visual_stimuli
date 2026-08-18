from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from collections.abc import Mapping
from typing import Any, Optional, Union

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


def load_raws(screen: Any, key_to_path: dict[str, Union[str, Path]]) -> dict[str, Any]:
    return {key: screen.load_raw(str(path)) for key, path in key_to_path.items()}


@dataclass(frozen=True)
class DisplayTiming:
    display_request_unix_ns: int
    display_return_unix_ns: int
    display_return_utc_iso: str
    display_request_perf_counter_ns: int
    display_return_perf_counter_ns: int
    display_call_duration_sec: float
    start_time_unix: Optional[float]
    mean_interframe_us: Optional[float]
    stddev_interframe_us: Optional[float]

    def to_event_fields(self) -> dict[str, object]:
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


def _empty_rpg_performance() -> dict[str, Optional[float]]:
    return {
        "start_time_unix": None,
        "mean_interframe_us": None,
        "stddev_interframe_us": None,
    }


def _coerce_metric(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_rpg_performance(perf: Any, *, diagnostic: bool = False) -> dict[str, Optional[float]]:
    if perf is None:
        return _empty_rpg_performance()

    if isinstance(perf, Mapping):
        values = dict(perf)
    else:
        values = {}
        for name in dir(perf):
            if name.startswith("_"):
                continue
            try:
                values[name] = getattr(perf, name)
            except Exception:
                continue

    normalized = {
        str(key).lower().replace("-", "_").replace(" ", "_"): value
        for key, value in values.items()
    }
    aliases = {
        "start_time_unix": ("start_time_unix", "start_time", "start_unix"),
        "mean_interframe_us": (
            "mean_interframe_us",
            "mean_interframe",
            "mean_interframe_time_us",
        ),
        "stddev_interframe_us": (
            "stddev_interframe_us",
            "stddev_interframe",
            "std_interframe_us",
            "std_interframe",
        ),
    }
    result = _empty_rpg_performance()
    for output_name, candidate_names in aliases.items():
        for candidate_name in candidate_names:
            if candidate_name in normalized:
                result[output_name] = _coerce_metric(normalized[candidate_name])
                break
    if diagnostic:
        print("RPG display_raw return type: {}".format(type(perf)))
        representation = repr(perf)
        if len(representation) > 2000:
            representation = representation[:2000] + "..."
        print("RPG display_raw return repr: {}".format(representation))
        print("available timing fields:")
        for name in aliases:
            print("  {} = {}".format(name, result[name]))
    return result


def diagnose_rpg_display_return(screen: Any, loaded_raw: Any) -> dict[str, Optional[float]]:
    """Display one raw and print the bounded RPG return-value diagnostic."""
    perf = screen.display_raw(loaded_raw)
    return extract_rpg_performance(perf, diagnostic=True)


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
