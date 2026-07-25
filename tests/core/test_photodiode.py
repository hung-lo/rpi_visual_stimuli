from __future__ import annotations

import unittest

from rpi_visual_stimuli.core.config import PhotodiodeConfig, ScreenConfig
from rpi_visual_stimuli.core.photodiode import compute_patch_geometry


class PhotodiodeTests(unittest.TestCase):
    def test_supported_corners_produce_in_bounds_geometry(self):
        screen = ScreenConfig(
            width_px=100,
            height_px=80,
            refresh_rate_hz=60,
            colormode=16,
            background_gray_u8=127,
            visible_width_cm=10.0,
            visible_height_cm=8.0,
        )
        for corner in ("top_left", "top_right", "bottom_left", "bottom_right"):
            photodiode = PhotodiodeConfig(
                enabled=True,
                corner=corner,
                size_px=10,
                margin_px=2,
                on_rgb=(255, 255, 255),
                off_rgb=(0, 0, 0),
            )
            geometry = compute_patch_geometry(screen, photodiode)
            self.assertGreaterEqual(geometry.left, 0)
            self.assertGreaterEqual(geometry.top, 0)
            self.assertLessEqual(geometry.right, screen.width_px)
            self.assertLessEqual(geometry.bottom, screen.height_px)
