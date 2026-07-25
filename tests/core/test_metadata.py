from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rpi_visual_stimuli.core.metadata import atomic_write_json, read_source_provenance, update_session_metadata
from tests.helpers import repo_root


class MetadataTests(unittest.TestCase):
    def test_atomic_write_json_and_update(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "metadata.json"
            atomic_write_json(path, {"stage": "start"})
            payload = update_session_metadata(path, end="done")
            self.assertEqual(payload["stage"], "start")
            self.assertEqual(payload["end"], "done")
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["end"], "done")

    def test_read_source_provenance(self):
        provenance = read_source_provenance(repo_root() / "docs" / "SOURCE_PROVENANCE.md")
        self.assertEqual(
            provenance["vstim_natural_commit"],
            "0c9cad115d47608307d4f7a7190f7969891623a5",
        )
