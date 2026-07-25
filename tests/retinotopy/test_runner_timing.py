from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rpi_visual_stimuli.protocols.retinotopy import runner


class _FakeTiming:
    def to_event_fields(self):
        return {}


class _FakeProgressReporter:
    def __init__(self):
        self.updates: list[dict[str, object]] = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class RetinotopyRunnerTimingTests(unittest.TestCase):
    def test_final_sweep_is_followed_by_inter_sweep_gray_and_exact_eta_uses_final_gray(self):
        event_types: list[str] = []
        gray_durations: list[float] = []
        trials = [
            {
                "trial_index": 0,
                "repeat_number": 1,
                "direction": "left_to_right",
                "direction_code": 1,
                "axis": "x",
                "start_edge": "left",
                "end_edge": "right",
                "planned_sweep_duration_sec": 2.0,
                "planned_gray_duration_sec": 1.0,
                "raw_key": "left_to_right",
            },
            {
                "trial_index": 1,
                "repeat_number": 1,
                "direction": "top_to_bottom",
                "direction_code": 2,
                "axis": "y",
                "start_edge": "top",
                "end_edge": "bottom",
                "planned_sweep_duration_sec": 2.0,
                "planned_gray_duration_sec": 1.0,
                "raw_key": "top_to_bottom",
            },
        ]
        cache = SimpleNamespace(
            sweep_paths={
                "left_to_right": Path("/tmp/left_to_right.raw"),
                "top_to_bottom": Path("/tmp/top_to_bottom.raw"),
            },
            inter_sweep_gray_path=Path("/tmp/inter_sweep_gray.raw"),
            cache_hash="cache-hash",
        )
        config = SimpleNamespace(
            movement_frame_rate_hz=15,
            refreshes_per_movement_frame=4,
            bar_width_fraction=0.1,
        )
        progress_reporter = _FakeProgressReporter()

        def append_side_effect(_path, row, _fieldnames, fsync=False):
            del fsync
            event_types.append(row["event_type"])
            if row["event_type"] == "inter_sweep_gray":
                gray_durations.append(float(row["planned_duration_sec"]))

        with patch.object(runner, "display_raw_with_timing", return_value=_FakeTiming()), patch.object(
            runner, "append_csv_row", side_effect=append_side_effect
        ), patch.object(runner.time, "monotonic", side_effect=[1.0, 2.0]):
            runner._playback_trials(
                screen=object(),
                trials=trials,
                cache=cache,
                loaded_sweeps={"left_to_right": object(), "top_to_bottom": object()},
                loaded_inter_sweep=object(),
                event_log_path=Path("/tmp/event_log.csv"),
                config=config,
                progress_reporter=progress_reporter,
                playback_start_monotonic=0.0,
                remaining_after_index=[6.0, 3.0, 0.0],
                final_gray_sec=1.5,
            )

        self.assertEqual(
            event_types,
            ["sweep_display", "inter_sweep_gray", "sweep_display", "inter_sweep_gray"],
        )
        self.assertEqual(gray_durations, [1.0, 1.0])
        self.assertEqual(
            progress_reporter.updates,
            [
                {
                    "current_index": 1,
                    "current_condition": "direction=left_to_right",
                    "elapsed_seconds": 1.0,
                    "remaining_seconds": 4.5,
                },
                {
                    "current_index": 2,
                    "current_condition": "direction=top_to_bottom",
                    "elapsed_seconds": 2.0,
                    "remaining_seconds": 1.5,
                },
            ],
        )
