from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rpi_visual_stimuli.core.preflight import (
    check_disk_space_before_build,
    check_memory_before_loading,
    nearest_existing_ancestor,
    read_meminfo,
    validate_storage_root,
)


class PreflightTests(unittest.TestCase):
    def test_read_meminfo_parses_bytes(self):
        content = "MemTotal:       1024 kB\nMemAvailable:    256 kB\n"
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write(content)
            path = handle.name
        meminfo = read_meminfo(path)
        self.assertEqual(meminfo["MemTotal"], 1024 * 1024)
        self.assertEqual(meminfo["MemAvailable"], 256 * 1024)

    def test_memory_check_reports_shortfall(self):
        with self.assertRaises(MemoryError) as ctx:
            check_memory_before_loading(
                [100, 100],
                available_memory_bytes=100,
                overhead_factor=1.15,
                safety_margin_bytes=50,
            )
        self.assertIn("shortfall", str(ctx.exception))

    def test_disk_check_uses_margin(self):
        with mock.patch("rpi_visual_stimuli.core.preflight.shutil.disk_usage") as fake_usage:
            fake_usage.return_value = (1000, 100, 900)
            result = check_disk_space_before_build(Path("."), required_bytes=100, margin_bytes=100)
        self.assertEqual(result.shortfall_bytes, 0)

    def test_nearest_existing_ancestor_uses_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "cache"
            target.mkdir()
            self.assertEqual(nearest_existing_ancestor(target), target)

    def test_nearest_existing_ancestor_uses_immediate_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "cache"
            target = parent / "hash"
            parent.mkdir()
            self.assertEqual(nearest_existing_ancestor(target), parent)

    def test_disk_check_walks_multiple_missing_levels_without_mutating(self):
        with tempfile.TemporaryDirectory() as directory:
            storage_root = Path(directory)
            target = storage_root / "vstim_cache" / "retinotopy" / "hash"
            with mock.patch("rpi_visual_stimuli.core.preflight.shutil.disk_usage") as fake_usage:
                fake_usage.return_value = (1000, 100, 900)
                result = check_disk_space_before_build(target, required_bytes=100)
            self.assertEqual(result.disk_check_path, storage_root)
            fake_usage.assert_called_once_with(str(storage_root))
            self.assertFalse((storage_root / "vstim_cache").exists())

    def test_fresh_drifting_gratings_cache_tree_uses_storage_root(self):
        with tempfile.TemporaryDirectory() as directory:
            storage_root = Path(directory)
            target = storage_root / "vstim_cache" / "drifting_gratings" / "hash"
            with mock.patch("rpi_visual_stimuli.core.preflight.shutil.disk_usage") as fake_usage:
                fake_usage.return_value = (1000, 100, 900)
                result = check_disk_space_before_build(target, required_bytes=100)
            self.assertEqual(result.disk_check_path, storage_root)
            self.assertFalse((storage_root / "vstim_cache").exists())

    def test_disk_check_error_includes_ancestor_and_space_details(self):
        with tempfile.TemporaryDirectory() as directory:
            storage_root = Path(directory)
            target = storage_root / "vstim_cache" / "retinotopy" / "hash"
            with mock.patch("rpi_visual_stimuli.core.preflight.shutil.disk_usage") as fake_usage:
                fake_usage.return_value = (1000, 900, 50)
                with self.assertRaises(OSError) as context:
                    check_disk_space_before_build(target, required_bytes=100, margin_bytes=25)
            message = str(context.exception)
            self.assertIn(str(storage_root), message)
            self.assertIn("Free: 50 bytes", message)
            self.assertIn("Required build bytes: 100", message)
            self.assertIn("Safety margin: 25", message)
            self.assertIn("Shortfall: 75 bytes", message)

    def test_storage_validation_allows_non_mount_directory_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            storage_root = Path(directory)
            with mock.patch("rpi_visual_stimuli.core.preflight._backing_mount_info", return_value={}):
                with mock.patch.object(Path, "is_mount", return_value=False):
                    with mock.patch("rpi_visual_stimuli.core.preflight.shutil.disk_usage") as fake_usage:
                        fake_usage.return_value = (1000, 100, 900)
                        result = validate_storage_root(storage_root)
            self.assertFalse(result["is_mount_point"])
            self.assertEqual(result["free_bytes"], 900)

    def test_storage_validation_requires_mount_only_when_configured(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(Path, "is_mount", return_value=False):
                with self.assertRaises(RuntimeError) as context:
                    validate_storage_root(directory, require_separate_mount=True)
        self.assertIn("not an active mount point", str(context.exception))

    def test_storage_validation_rejects_missing_root(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            with self.assertRaises(RuntimeError) as context:
                validate_storage_root(missing)
        self.assertIn("does not exist", str(context.exception))
