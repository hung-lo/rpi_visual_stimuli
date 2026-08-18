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

    def _write_hash_test_cache(self, directory_name, manifest_hash):
        cache_dir = directory_name
        cache_dir.mkdir()
        raw_path = cache_dir / "movie.raw"
        raw_path.write_bytes(b"1234")
        write_manifest(
            cache_dir,
            {
                "cache_hash": manifest_hash,
                "expected_files": {"movie.raw": {"size_bytes": 4}},
            },
        )
        return cache_dir

    def test_canonical_final_directory_passes_strict_hash_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = self._write_hash_test_cache(Path(temp_dir) / "abc123", "abc123")
            result = validate_cache(cache_dir)
        self.assertTrue(result.valid)

    def test_canonical_final_directory_mismatch_fails_strict_hash_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = self._write_hash_test_cache(Path(temp_dir) / "abc123", "def456")
            result = validate_cache(cache_dir)
        self.assertFalse(result.valid)
        self.assertIn("Final cache manifest hash", result.reason)

    def test_staging_directory_accepts_explicit_expected_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = self._write_hash_test_cache(Path(temp_dir) / "abc123.tmp-XYZ", "abc123")
            result = validate_cache(cache_dir, expected_cache_hash="abc123")
        self.assertTrue(result.valid)

    def test_staging_directory_rejects_wrong_expected_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = self._write_hash_test_cache(Path(temp_dir) / "abc123.tmp-XYZ", "abc123")
            result = validate_cache(cache_dir, expected_cache_hash="def456")
        self.assertFalse(result.valid)
        self.assertIn("Staging cache manifest hash", result.reason)

    def test_staging_directory_remains_strict_without_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = self._write_hash_test_cache(Path(temp_dir) / "abc123.tmp-XYZ", "abc123")
            result = validate_cache(cache_dir)
        self.assertFalse(result.valid)
