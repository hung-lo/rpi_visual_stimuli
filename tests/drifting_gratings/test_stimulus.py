from __future__ import annotations

import importlib.util
import unittest

NUMPY_AVAILABLE = importlib.util.find_spec("numpy") is not None


@unittest.skipUnless(NUMPY_AVAILABLE, "numpy is required for stimulus geometry tests")
class DriftingGratingStimulusTests(unittest.TestCase):
    def test_default_frame_shape_and_orientation_conventions(self):
        from rpi_visual_stimuli.protocols.drifting_gratings.config import build_config
        from rpi_visual_stimuli.protocols.drifting_gratings.stimulus import drift_direction_deg, generate_grating_frame
        from tests.helpers import load_repo_system_config

        system_config = load_repo_system_config()
        config = build_config(system_config)
        frame0 = generate_grating_frame(system_config, config, bar_orientation_deg=0.0, frame_index=0)
        frame90 = generate_grating_frame(system_config, config, bar_orientation_deg=90.0, frame_index=0)
        self.assertEqual(frame0.shape, (600, 1024, 3))
        self.assertEqual(frame0.dtype.name, "uint8")
        self.assertEqual(drift_direction_deg(0.0), 270.0)
        self.assertEqual(drift_direction_deg(90.0), 0.0)
        self.assertTrue((frame0[300, :, 0] == frame0[300, 0, 0]).all())
        self.assertTrue((frame90[:, 512, 0] == frame90[0, 512, 0]).all())

    def test_frame_zero_and_frame_thirty_match_within_rounding(self):
        from rpi_visual_stimuli.protocols.drifting_gratings.config import build_config
        from rpi_visual_stimuli.protocols.drifting_gratings.stimulus import generate_grating_frame
        from tests.helpers import load_repo_system_config

        system_config = load_repo_system_config()
        config = build_config(system_config)
        frame0 = generate_grating_frame(system_config, config, bar_orientation_deg=45.0, frame_index=0)
        frame30 = generate_grating_frame(system_config, config, bar_orientation_deg=45.0, frame_index=30)
        self.assertLessEqual(abs(frame0.astype(int) - frame30.astype(int)).max(), 1)
