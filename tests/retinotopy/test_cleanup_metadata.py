from __future__ import annotations

import unittest

from rpi_visual_stimuli.protocols.retinotopy.runner import _resolve_cleanup_stage


class RetinotopyCleanupMetadataTests(unittest.TestCase):
    def test_no_camera_cleanup_does_not_report_camera_cleanup_stage(self):
        self.assertEqual(
            _resolve_cleanup_stage(
                screen_opened=True,
                gpio_cleanup_attempted=False,
                camera_cleanup_attempted=False,
            ),
            "rpg_cleanup",
        )

    def test_camera_cleanup_stage_requires_an_attempt(self):
        self.assertIsNone(
            _resolve_cleanup_stage(
                screen_opened=False,
                gpio_cleanup_attempted=False,
                camera_cleanup_attempted=False,
            )
        )
        self.assertEqual(
            _resolve_cleanup_stage(
                screen_opened=True,
                gpio_cleanup_attempted=False,
                camera_cleanup_attempted=True,
            ),
            "camera_cleanup",
        )
