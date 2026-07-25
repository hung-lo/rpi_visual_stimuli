from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import remote_camera_control


class RemoteCameraControlTests(unittest.TestCase):
    def test_state_file_is_namespaced(self):
        self.assertEqual(
            remote_camera_control.STATE_FILE.name,
            ".rpi_visual_stimuli_camera_session.json",
        )

    def test_parser_accepts_config_aliases(self):
        parser = remote_camera_control.build_parser()
        args = parser.parse_args(
            [
                "preflight",
                "--camera-host",
                "pi@example",
                "--remote-camera-repo",
                "/repo",
                "--remote-camera-start",
                "/repo/start.py",
                "--remote-camera-stop",
                "/repo/stop.sh",
                "--remote-video-root",
                "/remote/videos",
                "--local-output-root",
                "/tmp/output",
            ]
        )
        self.assertEqual(args.camera_host, "pi@example")
        self.assertEqual(args.remote_camera_repo, "/repo")
        self.assertEqual(args.remote_camera_start, "/repo/start.py")
        self.assertEqual(args.remote_camera_stop, "/repo/stop.sh")
        self.assertEqual(args.remote_video_root, "/remote/videos")
        self.assertEqual(args.local_output_root, "/tmp/output")

    def test_make_session_paths_uses_explicit_session_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            args = SimpleNamespace(
                mouse_id="mouse-7",
                session_id="session-123",
                local_output_root=temp_dir,
                remote_video_root="/remote/videos",
            )
            paths = remote_camera_control.make_session_paths(args)
        self.assertEqual(paths["mouse_id"], "mouse-7")
        self.assertEqual(paths["session_id"], "session-123")
        self.assertTrue(paths["local_session_dir"].endswith("session-123"))
        self.assertTrue(paths["local_video_dir"].endswith("session-123/video"))
        self.assertEqual(paths["remote_session_dir"], "/remote/videos/session-123")
        self.assertEqual(paths["remote_video_dir"], "/remote/videos/session-123/video")
        self.assertEqual(paths["remote_base_path"], "/remote/videos/session-123/video/session-123")

    def test_build_state_from_args_uses_configured_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            args = SimpleNamespace(
                mouse_id="mouse 1",
                session_id="session 1",
                camera_host="pi@camera-box",
                framerate=45,
                remote_camera_repo="/repo",
                remote_camera_start="/repo/start.py",
                remote_camera_stop="/repo/stop.sh",
                remote_video_root="/remote/videos",
                local_output_root=temp_dir,
            )
            state = remote_camera_control.build_state_from_args(args)
        self.assertEqual(state["camera_host"], "pi@camera-box")
        self.assertEqual(state["framerate"], 45)
        self.assertEqual(state["remote_camera_repo"], "/repo")
        self.assertEqual(state["remote_camera_start"], "/repo/start.py")
        self.assertEqual(state["remote_camera_stop"], "/repo/stop.sh")
        self.assertEqual(state["remote_video_root"], "/remote/videos")
        self.assertTrue(state["local_video_dir"].endswith("session_1/video"))
        self.assertEqual(state["session_id"], "session_1")

    def test_preflight_raises_existing_acquisition_error(self):
        args = SimpleNamespace(dry_run=False)
        with patch.object(
            remote_camera_control,
            "_run_preflight_checks",
            return_value={
                "camera_host": "pi@camera-box",
                "remote_repo": "/repo",
                "remote_start": "/repo/start.py",
                "remote_stop": "/repo/stop.sh",
                "remote_video_root": "/remote/videos",
                "local_output_root": "/tmp/output",
                "acquisition_running": True,
                "acquisition_lines": ["123 python3 start.py"],
                "known_state_session_id": "session-abc",
            },
        ):
            with self.assertRaises(remote_camera_control.ExistingAcquisitionError) as ctx:
                remote_camera_control.preflight_camera(args)
        self.assertEqual(ctx.exception.exit_code, 3)
        self.assertIn("session-abc", str(ctx.exception))

    def test_load_state_prefers_namespaced_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / ".rpi_visual_stimuli_camera_session.json"
            legacy_path = Path(temp_dir) / ".last_remote_camera_session.json"
            state_path.write_text('{"session_id": "new-state"}', encoding="utf-8")
            legacy_path.write_text('{"session_id": "legacy-state"}', encoding="utf-8")
            with patch.object(remote_camera_control, "STATE_FILE", state_path), patch.object(
                remote_camera_control, "LEGACY_STATE_FILE", legacy_path
            ):
                state = remote_camera_control.load_state(allow_legacy_state=True)
        self.assertEqual(state["session_id"], "new-state")
