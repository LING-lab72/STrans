import unittest
from pathlib import Path

from scripts.record_sandtable_rtsp import build_ffmpeg_command, select_video_codec


class SandtableRecordingTests(unittest.TestCase):
    def test_recording_uses_stream_copy_and_a_bounded_segment_ring(self):
        command = build_ffmpeg_command(
            ffmpeg="ffmpeg",
            source="rtsp://example.test:8554/live/live1",
            output_pattern=Path("recordings/live1_%03d.mkv"),
            segment_seconds=300,
            max_segments=96,
        )

        self.assertIn("copy", command)
        self.assertIn("segment", command)
        self.assertIn("96", command)
        self.assertIn("-rtsp_transport", command)

    def test_recording_can_transcode_with_a_space_saving_h264_profile(self):
        command = build_ffmpeg_command(
            ffmpeg="ffmpeg",
            source="rtsp://example.test:8554/live/live1",
            output_pattern=Path("recordings/live1_%03d.mkv"),
            segment_seconds=300,
            max_segments=24,
            video_codec="libx264",
            preset="ultrafast",
            crf=30,
        )

        self.assertEqual(command[command.index("-c:v") + 1], "libx264")
        self.assertEqual(command[command.index("-preset") + 1], "ultrafast")
        self.assertEqual(command[command.index("-crf") + 1], "30")

    def test_stream_copy_is_used_when_libx264_is_not_available(self):
        codec = select_video_codec("libx264", {"h264_mf", "mjpeg"})

        self.assertEqual(codec, "copy")


if __name__ == "__main__":
    unittest.main()
