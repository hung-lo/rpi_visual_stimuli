from __future__ import annotations

from datetime import datetime, timezone
import unittest

from rpi_visual_stimuli.core.duration import estimated_local_completion, format_duration, summarize_protocol_duration


class DurationTests(unittest.TestCase):
    def test_format_duration_examples(self):
        self.assertEqual(format_duration(934), "15 min 34 sec")
        self.assertEqual(format_duration(1006), "16 min 46 sec")

    def test_format_duration_rejects_negative_values(self):
        with self.assertRaises(ValueError):
            format_duration(-0.1)

    def test_summary_adds_initial_and_final_gray_without_camera(self):
        summary = summarize_protocol_duration(
            trial_epoch_durations_sec=[10.0, 20.0, 30.0],
            initial_gray_sec=3.0,
            final_gray_sec=4.0,
            camera_enabled=False,
            baseline_minutes=None,
        )
        self.assertEqual(summary.trial_sequence_sec, 60.0)
        self.assertEqual(summary.no_camera_protocol_sec, 67.0)
        self.assertIsNone(summary.camera_start_to_protocol_end_nominal_sec)

    def test_camera_summary_uses_requested_baseline_without_adding_initial_gray_again(self):
        summary = summarize_protocol_duration(
            trial_epoch_durations_sec=[100.0],
            initial_gray_sec=3.0,
            final_gray_sec=3.0,
            camera_enabled=True,
            baseline_minutes=3.0,
        )
        self.assertEqual(summary.trial_sequence_sec, 100.0)
        self.assertEqual(summary.no_camera_protocol_sec, 106.0)
        self.assertEqual(summary.camera_start_to_protocol_end_nominal_sec, 283.0)

    def test_estimated_local_completion_uses_timezone_aware_now(self):
        now = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)
        completion = estimated_local_completion(90.0, now=now)
        self.assertEqual(completion, datetime(2026, 7, 25, 12, 1, 30, tzinfo=timezone.utc))

