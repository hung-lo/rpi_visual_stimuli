from __future__ import annotations

from datetime import datetime, timezone
import time


def unix_ns_to_iso(unix_ns: int) -> str:
    unix_ns = int(unix_ns)
    seconds, nanoseconds = divmod(unix_ns, 1_000_000_000)
    dt = datetime.fromtimestamp(seconds, timezone.utc)
    return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{nanoseconds:09d}+00:00"


def unix_ns_to_seconds_string(unix_ns: int) -> str:
    unix_ns = int(unix_ns)
    seconds, nanoseconds = divmod(unix_ns, 1_000_000_000)
    return f"{seconds}.{nanoseconds:09d}"


def capture_timestamp() -> dict[str, object]:
    unix_ns = time.time_ns()
    return {
        "unix_ns": unix_ns,
        "unix_sec": unix_ns_to_seconds_string(unix_ns),
        "utc_iso": unix_ns_to_iso(unix_ns),
    }


def utc_iso_now() -> str:
    return unix_ns_to_iso(time.time_ns())


def utc_session_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
