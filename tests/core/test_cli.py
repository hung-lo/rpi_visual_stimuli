from __future__ import annotations

import unittest

from rpi_visual_stimuli.core.cli import build_common_parser, resolve_camera_enabled


class CliTests(unittest.TestCase):
    def test_camera_flags_are_mutually_exclusive(self):
        parser = build_common_parser("demo")
        with self.assertRaises(SystemExit):
            parser.parse_args(["--camera", "--no-camera"])

    def test_interactive_camera_prompt_defaults_to_yes(self):
        parser = build_common_parser("demo")
        args = parser.parse_args([])
        self.assertTrue(resolve_camera_enabled(args, input_fn=lambda _prompt: ""))
