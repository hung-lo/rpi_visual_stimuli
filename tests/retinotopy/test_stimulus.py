from __future__ import annotations

import importlib.util
import unittest

NUMPY_AVAILABLE = importlib.util.find_spec("numpy") is not None


@unittest.skipUnless(NUMPY_AVAILABLE, "numpy is required for retinotopy geometry tests")
class RetinotopyStimulusTests(unittest.TestCase):
    def test_vertical_and_horizontal_band_geometry(self):
        from rpi_visual_stimuli.protocols.retinotopy.config import build_test_config
        from rpi_visual_stimuli.protocols.retinotopy.stimulus import generate_direction_frames
        from tests.helpers import load_repo_system_config

        system_config = load_repo_system_config()
        config = build_test_config(system_config)
        left_right = generate_direction_frames(system_config, config, direction="left_to_right")
        top_bottom = generate_direction_frames(system_config, config, direction="top_to_bottom")
        self.assertEqual(len(left_right), config.source_frame_count)
        self.assertTrue((left_right[len(left_right) // 2][:, 512, 0] == left_right[len(left_right) // 2][0, 512, 0]).all())
        self.assertTrue((top_bottom[len(top_bottom) // 2][300, :, 0] == top_bottom[len(top_bottom) // 2][300, 0, 0]).all())

    def test_reverse_directions_are_temporal_reverses(self):
        from rpi_visual_stimuli.protocols.retinotopy.config import build_test_config
        from rpi_visual_stimuli.protocols.retinotopy.stimulus import generate_direction_frames
        from tests.helpers import load_repo_system_config

        system_config = load_repo_system_config()
        config = build_test_config(system_config)
        left_right = generate_direction_frames(system_config, config, direction="left_to_right")
        right_left = generate_direction_frames(system_config, config, direction="right_to_left")
        self.assertTrue((left_right[0] == right_left[-1]).all())
        self.assertTrue((left_right[-1] == right_left[0]).all())
