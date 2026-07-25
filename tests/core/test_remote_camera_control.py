from __future__ import annotations

import unittest

import remote_camera_control


class RemoteCameraControlTests(unittest.TestCase):
    def test_state_file_is_namespaced(self):
        self.assertEqual(
            remote_camera_control.STATE_FILE.name,
            ".rpi_visual_stimuli_camera_session.json",
        )
