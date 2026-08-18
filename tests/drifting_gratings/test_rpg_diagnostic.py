from __future__ import annotations

import unittest

from rpi_visual_stimuli.protocols.drifting_gratings import runner


class DriftingGratingsRpgDiagnosticTests(unittest.TestCase):
    def test_parser_accepts_rpg_return_diagnostic(self):
        args = runner.build_parser().parse_args(["--test-rpg-return"])
        self.assertTrue(args.test_rpg_return)

    def test_diagnostic_rejects_camera(self):
        args = runner.build_parser().parse_args(["--camera", "--test-rpg-return"])
        with self.assertRaisesRegex(ValueError, "no-camera"):
            runner.run(args)
