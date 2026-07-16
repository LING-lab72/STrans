import unittest

from app.services.video_stream import redact_stream_error, safe_source_label


class VideoStreamSecurityTests(unittest.TestCase):
    def test_stream_url_is_redacted_in_public_status(self):
        source = "rtsp://viewer:super-secret@example.test:8554/mobile-camera"

        self.assertEqual(safe_source_label(source), "configured video source")

    def test_camera_index_remains_visible_for_diagnostics(self):
        self.assertEqual(safe_source_label("0"), "0")

    def test_stream_error_does_not_echo_the_configured_url(self):
        source = "rtsp://viewer:super-secret@example.test:8554/mobile-camera"
        error = redact_stream_error(f"OpenCV failed to open {source}", source)

        self.assertNotIn(source, error)
        self.assertNotIn("super-secret", error)
        self.assertIn("configured video source", error)


if __name__ == "__main__":
    unittest.main()
