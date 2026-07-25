from __future__ import annotations

import unittest

from rpi_visual_stimuli.core.rpg_display import display_raw_with_timing


class FakeScreen:
    def display_raw(self, _loaded_raw):
        return {
            "start_time_unix": 1.23,
            "mean_interframe_us": 16666.7,
            "stddev_interframe_us": 100.0,
        }


class RpgDisplayTests(unittest.TestCase):
    def test_display_raw_with_timing_captures_wrapper_fields(self):
        timing = display_raw_with_timing(FakeScreen(), object())
        fields = timing.to_event_fields()
        self.assertIn("display_request_unix_ns", fields)
        self.assertIn("display_return_unix_ns", fields)
        self.assertEqual(fields["mean_interframe_us"], 16666.7)
