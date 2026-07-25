from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rpi_visual_stimuli.core.raw_cache import stable_hash, validate_cache, write_manifest


class RawCacheTests(unittest.TestCase):
    def test_hash_is_deterministic_and_changes_with_payload(self):
        payload_a = {"a": 1, "b": [2, 3]}
        payload_b = {"a": 1, "b": [2, 4]}
        self.assertEqual(stable_hash(payload_a), stable_hash({"b": [2, 3], "a": 1}))
        self.assertNotEqual(stable_hash(payload_a), stable_hash(payload_b))

    def test_validate_cache_detects_size_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "cachehash"
            cache_dir.mkdir()
            raw_path = cache_dir / "movie.raw"
            raw_path.write_bytes(b"1234")
            write_manifest(
                cache_dir,
                {
                    "cache_hash": "cachehash",
                    "expected_files": {"movie.raw": {"size_bytes": 4}},
                },
            )
            self.assertTrue(validate_cache(cache_dir).valid)
            raw_path.write_bytes(b"12345")
            result = validate_cache(cache_dir)
        self.assertFalse(result.valid)
        self.assertIn("size mismatch", result.reason)
