from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Callable


InputFn = Callable[[str], str]


@dataclass
class EarlyStartMonitor:
    override_event: threading.Event
    stop_event: threading.Event
    thread: threading.Thread | None


@dataclass(frozen=True)
class BaselineResult:
    requested_baseline_seconds: float
    actual_camera_baseline_seconds: float
    minimum_gray_seconds: float
    actual_gray_seconds: float
    override_used: bool
    end_reason: str
    baseline_remaining_at_gate_entry: float
    gray_remaining_at_gate_entry: float
    waited_for_minimum_gray_after_override: bool

    def to_dict(self) -> dict[str, float | bool | str]:
        return {
            "requested_baseline_seconds": self.requested_baseline_seconds,
            "actual_camera_baseline_seconds": self.actual_camera_baseline_seconds,
            "minimum_gray_seconds": self.minimum_gray_seconds,
            "actual_gray_seconds": self.actual_gray_seconds,
            "override_used": self.override_used,
            "end_reason": self.end_reason,
            "baseline_remaining_at_gate_entry": self.baseline_remaining_at_gate_entry,
            "gray_remaining_at_gate_entry": self.gray_remaining_at_gate_entry,
            "waited_for_minimum_gray_after_override": self.waited_for_minimum_gray_after_override,
        }


def start_early_start_monitor(
    *,
    input_fn: InputFn = input,
    prompt: str = "Press Enter to start early once minimum gray is satisfied: ",
    enabled: bool = True,
) -> EarlyStartMonitor:
    override_event = threading.Event()
    stop_event = threading.Event()
    if not enabled:
        return EarlyStartMonitor(override_event=override_event, stop_event=stop_event, thread=None)

    def _worker() -> None:
        try:
            input_fn(prompt)
        except EOFError:
            return
        if not stop_event.is_set():
            override_event.set()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return EarlyStartMonitor(override_event=override_event, stop_event=stop_event, thread=thread)


def stop_early_start_monitor(monitor: EarlyStartMonitor | None) -> None:
    if monitor is None:
        return
    monitor.stop_event.set()


def wait_for_prestimulus_gate(
    *,
    requested_baseline_seconds: float,
    minimum_gray_seconds: float,
    baseline_start_monotonic: float,
    gray_start_monotonic: float,
    override_event: threading.Event | None = None,
    now_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
    poll_interval_sec: float = 0.05,
) -> BaselineResult:
    gate_entry = now_fn()
    baseline_elapsed = max(0.0, gate_entry - baseline_start_monotonic)
    gray_elapsed = max(0.0, gate_entry - gray_start_monotonic)
    baseline_remaining = max(0.0, requested_baseline_seconds - baseline_elapsed)
    gray_remaining = max(0.0, minimum_gray_seconds - gray_elapsed)

    if baseline_remaining <= 0.0 and gray_remaining <= 0.0:
        end_reason = "timer_satisfied_during_preparation"
        waited_after_override = False
        override_used = False
    else:
        end_reason = "timer_elapsed"
        waited_after_override = False
        override_used = False
        while True:
            now = now_fn()
            baseline_elapsed = max(0.0, now - baseline_start_monotonic)
            gray_elapsed = max(0.0, now - gray_start_monotonic)
            baseline_remaining = max(0.0, requested_baseline_seconds - baseline_elapsed)
            gray_remaining = max(0.0, minimum_gray_seconds - gray_elapsed)
            if override_event is not None and override_event.is_set():
                override_used = True
                end_reason = "user_override"
                while gray_remaining > 0.0:
                    waited_after_override = True
                    sleep_fn(min(poll_interval_sec, gray_remaining))
                    now = now_fn()
                    gray_elapsed = max(0.0, now - gray_start_monotonic)
                    gray_remaining = max(0.0, minimum_gray_seconds - gray_elapsed)
                break
            if baseline_remaining <= 0.0 and gray_remaining <= 0.0:
                break
            sleep_fn(poll_interval_sec)

    finished = now_fn()
    return BaselineResult(
        requested_baseline_seconds=requested_baseline_seconds,
        actual_camera_baseline_seconds=max(0.0, finished - baseline_start_monotonic),
        minimum_gray_seconds=minimum_gray_seconds,
        actual_gray_seconds=max(0.0, finished - gray_start_monotonic),
        override_used=override_used,
        end_reason=end_reason,
        baseline_remaining_at_gate_entry=max(0.0, requested_baseline_seconds - max(0.0, gate_entry - baseline_start_monotonic)),
        gray_remaining_at_gate_entry=max(0.0, minimum_gray_seconds - max(0.0, gate_entry - gray_start_monotonic)),
        waited_for_minimum_gray_after_override=waited_after_override,
    )
