from __future__ import annotations

import unittest
from types import SimpleNamespace

from rpi_visual_stimuli.core.rpg_display import display_raw_with_timing, extract_rpg_performance


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

    def test_extracts_attribute_return_shape(self):
        result = extract_rpg_performance(
            SimpleNamespace(
                start_time_unix=1.25,
                mean_interframe_us=0.0,
                stddev_interframe_us=2.5,
            )
        )
        self.assertEqual(result["start_time_unix"], 1.25)
        self.assertEqual(result["mean_interframe_us"], 0.0)
        self.assertEqual(result["stddev_interframe_us"], 2.5)

    def test_extracts_known_aliases_without_truthiness_loss(self):
        result = extract_rpg_performance(
            {
                "start_time": 0,
                "mean_interframe": 0,
                "std_interframe_us": 0,
            }
        )
        self.assertEqual(result, {
            "start_time_unix": 0.0,
            "mean_interframe_us": 0.0,
            "stddev_interframe_us": 0.0,
        })

    def test_missing_or_unexpected_return_shape_is_nonfatal(self):
        empty = {"start_time_unix": None, "mean_interframe_us": None, "stddev_interframe_us": None}
        self.assertEqual(extract_rpg_performance(None), empty)
        self.assertEqual(extract_rpg_performance(object()), empty)
