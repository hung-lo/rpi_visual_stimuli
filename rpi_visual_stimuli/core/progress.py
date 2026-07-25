from __future__ import annotations


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
    remaining_durations_seconds: list[float],
) -> str:
    remaining = max(0.0, sum(remaining_durations_seconds))
    percent = 0.0 if total_count <= 0 else (100.0 * current_index / total_count)
    return (
        f"{current_index}/{total_count} "
        f"{current_condition} "
        f"elapsed={format_seconds(elapsed_seconds)} "
        f"remaining={format_seconds(remaining)} "
        f"complete={percent:.1f}%"
    )
