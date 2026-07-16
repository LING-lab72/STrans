import unittest
from pathlib import Path

from scripts.export_sandtable_recordings import build_export_command, is_complete_recording


class SandtableRecordingExportTests(unittest.TestCase):
    def test_complete_recording_requires_data_and_a_probeable_video_stream(self):
        self.assertTrue(is_complete_recording(1024, 0, "h264\n12.5\n"))
        self.assertFalse(is_complete_recording(0, 0, "h264\n12.5\n"))
        self.assertFalse(is_complete_recording(1024, 1, ""))
        self.assertFalse(is_complete_recording(1024, 0, ""))

    def test_export_remuxes_video_to_mp4_without_reencoding(self):
        command = build_export_command(
            "ffmpeg",
            Path("recordings/live1_000.mkv"),
            Path("exports/live1_000.mp4"),
        )

        self.assertEqual(command[command.index("-c:v") + 1], "copy")
        self.assertIn("+faststart", command)
        self.assertEqual(Path(command[-1]), Path("exports/live1_000.mp4"))


if __name__ == "__main__":
    unittest.main()
