"""Import smoke tests for the complete hardware runner modules."""

from __future__ import annotations

import importlib
import unittest


class RunnerImportTests(unittest.TestCase):
    def test_complete_runners_import_under_supported_python(self):
        importlib.import_module("rpi_visual_stimuli.protocols.retinotopy.runner")
        importlib.import_module("rpi_visual_stimuli.protocols.drifting_gratings.runner")
