import subprocess
import sys
import unittest
from pathlib import Path

from scripts.evaluate_sandtable_videos import normalize_output_path, sample_timestamps, summarize_records


class SandtableDatasetEvaluationTests(unittest.TestCase):
    def test_output_path_is_recorded_as_an_absolute_path(self):
        backend_root = Path(__file__).resolve().parents[1]
        output = normalize_output_path(Path("../output/dataset-evaluation"), backend_root)

        self.assertTrue(output.is_absolute())
        self.assertEqual(output, backend_root.parent / "output" / "dataset-evaluation")

    def test_script_help_runs_from_backend_working_directory(self):
        backend_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(backend_root / "scripts" / "evaluate_sandtable_videos.py"), "--help"],
            cwd=backend_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--samples", completed.stdout)

    def test_sample_timestamps_use_even_frame_centers(self):
        self.assertEqual(sample_timestamps(300.0, 5), [30.0, 90.0, 150.0, 210.0, 270.0])
        self.assertEqual(sample_timestamps(0.0, 5), [])
        self.assertEqual(sample_timestamps(25.0, 0), [])

    def test_summary_separates_errors_and_counts_detection_evidence(self):
        summary = summarize_records(
            [
                {
                    "error": None,
                    "detection_count": 2,
                    "vehicle_count": 2,
                    "plates": ["京A12345"],
                    "event_count": 1,
                    "inference_ms": 10.0,
                },
                {
                    "error": None,
                    "detection_count": 0,
                    "vehicle_count": 0,
                    "plates": [],
                    "event_count": 0,
                    "inference_ms": 20.0,
                },
                {
                    "error": "unreadable frame",
                    "detection_count": 0,
                    "vehicle_count": 0,
                    "plates": [],
                    "event_count": 0,
                    "inference_ms": None,
                },
            ]
        )

        self.assertEqual(summary["sampled_frames"], 3)
        self.assertEqual(summary["successful_frames"], 2)
        self.assertEqual(summary["error_frames"], 1)
        self.assertEqual(summary["frames_with_detections"], 1)
        self.assertEqual(summary["detection_count"], 2)
        self.assertEqual(summary["unique_plates"], ["京A12345"])
        self.assertEqual(summary["event_count"], 1)
        self.assertEqual(summary["inference_ms_p50"], 15.0)
        self.assertEqual(summary["inference_ms_p95"], 20.0)


if __name__ == "__main__":
    unittest.main()
