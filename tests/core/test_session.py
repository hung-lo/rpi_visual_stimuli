from __future__ import annotations

import unittest
from pathlib import Path

from rpi_visual_stimuli.core.session import build_session_context


class SessionTests(unittest.TestCase):
    def test_session_naming(self):
        session = build_session_context(
            "retinotopy",
            "mouse 1",
            "notes",
            Path("/mnt/hd"),
            session_stamp="20260725T010203Z",
        )
        self.assertEqual(session.session_id, "mouse_1_20260725T010203Z_retinotopy")
        self.assertTrue(str(session.event_log_path).endswith("_event_log.csv"))
