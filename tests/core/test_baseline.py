from __future__ import annotations

import threading
import unittest

from rpi_visual_stimuli.core.baseline import wait_for_prestimulus_gate


class FakeClock:
    def __init__(self, now=0.0):
        self.now_value = now

    def now(self):
        return self.now_value

    def sleep(self, seconds):
        self.now_value += seconds


class BaselineTests(unittest.TestCase):
    def test_timer_elapsed(self):
        clock = FakeClock(now=0.0)
        result = wait_for_prestimulus_gate(
            requested_baseline_seconds=2.0,
            minimum_gray_seconds=1.0,
            baseline_start_monotonic=0.0,
            gray_start_monotonic=0.0,
            now_fn=clock.now,
            sleep_fn=clock.sleep,
            poll_interval_sec=0.5,
        )
        self.assertEqual(result.end_reason, "timer_elapsed")
        self.assertGreaterEqual(result.actual_camera_baseline_seconds, 2.0)

    def test_timer_satisfied_during_preparation(self):
        clock = FakeClock(now=5.0)
        result = wait_for_prestimulus_gate(
            requested_baseline_seconds=2.0,
            minimum_gray_seconds=1.0,
            baseline_start_monotonic=0.0,
            gray_start_monotonic=0.0,
            now_fn=clock.now,
            sleep_fn=clock.sleep,
        )
        self.assertEqual(result.end_reason, "timer_satisfied_during_preparation")

    def test_user_override_still_waits_for_minimum_gray(self):
        clock = FakeClock(now=0.0)
        override = threading.Event()
        override.set()
        result = wait_for_prestimulus_gate(
            requested_baseline_seconds=30.0,
            minimum_gray_seconds=3.0,
            baseline_start_monotonic=0.0,
            gray_start_monotonic=0.0,
            override_event=override,
            now_fn=clock.now,
            sleep_fn=clock.sleep,
            poll_interval_sec=0.5,
        )
        self.assertEqual(result.end_reason, "user_override")
        self.assertTrue(result.waited_for_minimum_gray_after_override)
        self.assertGreaterEqual(result.actual_gray_seconds, 3.0)
