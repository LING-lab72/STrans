import subprocess
import sys
import unittest
from pathlib import Path

from scripts.render_sandtable_clip import build_clip_ffmpeg_command, clip_timestamps, inference_device_label


class SandtableClipRendererTests(unittest.TestCase):
    def test_status_label_uses_the_actual_inference_device(self):
        self.assertEqual(inference_device_label({"device": "cuda:0"}), "CUDA:0")
        self.assertEqual(inference_device_label({"device": "cpu"}), "CPU")
        self.assertEqual(inference_device_label(None), "UNKNOWN")

    def test_clip_encoder_falls_back_to_media_foundation_h264(self):
        command = build_clip_ffmpeg_command(
            "ffmpeg",
            Path("frames/%04d.jpg"),
            4.0,
            Path("clip.mp4"),
            {"h264_mf", "mpeg4"},
        )

        self.assertEqual(command[command.index("-c:v") + 1], "h264_mf")
        self.assertNotIn("-preset", command)
        self.assertNotIn("-crf", command)
        self.assertEqual(command[command.index("-b:v") + 1], "5M")

    def test_clip_encoder_prefers_libx264_for_portable_h264(self):
        command = build_clip_ffmpeg_command(
            "ffmpeg",
            Path("frames/%04d.jpg"),
            4.0,
            Path("clip.mp4"),
            {"libx264", "h264_mf"},
        )

        self.assertEqual(command[command.index("-c:v") + 1], "libx264")
        self.assertIn("-preset", command)
        self.assertIn("-crf", command)

    def test_clip_timestamps_are_even_and_end_exclusive(self):
        self.assertEqual(clip_timestamps(27.0, 2.0, 2.0), [27.0, 27.5, 28.0, 28.5])
        self.assertEqual(clip_timestamps(0.0, 0.0, 4.0), [])
        self.assertEqual(clip_timestamps(0.0, 5.0, 0.0), [])

    def test_script_help_runs_from_backend_working_directory(self):
        backend_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(backend_root / "scripts" / "render_sandtable_clip.py"), "--help"],
            cwd=backend_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--sample-fps", completed.stdout)


if __name__ == "__main__":
    unittest.main()
