from __future__ import annotations

from dataclasses import dataclass, field
import sys
from typing import Optional, TextIO


def format_seconds(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:d}:{secs:02d}"


def render_progress_line(
    *,
    current_index: int,
    total_count: int,
    current_condition: str,
    elapsed_seconds: float,
    remaining_seconds: float,
    bar_width: int = 20,
) -> str:
    if total_count <= 0:
        fraction = 1.0
    else:
        fraction = min(1.0, max(0.0, current_index / total_count))
    completed_width = int(round(fraction * bar_width))
    completed_width = min(bar_width, max(0, completed_width))
    bar = "#" * completed_width + "-" * (bar_width - completed_width)
    remaining = max(0.0, remaining_seconds)
    return (
        f"[{bar}] "
        f"{current_index}/{total_count} "
        f"{fraction * 100:5.1f}% "
        f"{current_condition} "
        f"elapsed {format_seconds(elapsed_seconds)} "
        f"ETA {format_seconds(remaining)}"
    )


@dataclass
class ProgressReporter:
    total_count: int
    bar_width: int = 20
    stream: Optional[TextIO] = None
    _last_line_length: int = field(default=0, init=False)
    _finished: bool = field(default=False, init=False)
    _interactive: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.stream is None:
            self.stream = sys.stdout
        isatty = getattr(self.stream, "isatty", None)
        self._interactive = bool(isatty()) if callable(isatty) else False

    def update(
        self,
        *,
        current_index: int,
        current_condition: str,
        elapsed_seconds: float,
        remaining_seconds: float,
    ) -> None:
        line = render_progress_line(
            current_index=current_index,
            total_count=self.total_count,
            current_condition=current_condition,
            elapsed_seconds=elapsed_seconds,
            remaining_seconds=remaining_seconds,
            bar_width=self.bar_width,
        )
        if self._interactive:
            padding = " " * max(0, self._last_line_length - len(line))
            self.stream.write("\r" + line + padding)
            self.stream.flush()
            self._last_line_length = len(line)
            return
        self.stream.write(line + "\n")
        self.stream.flush()

    def finish(self) -> None:
        if self._finished:
            return
        if self._interactive:
            self.stream.write("\n")
            self.stream.flush()
        self._finished = True
