import unittest
from pathlib import Path

from app.services.local_model import LocalModelService, is_frame_entry_candidate


class ForkRecognitionBaselineTests(unittest.TestCase):
    def test_new_vehicle_count_is_visible_immediately(self):
        service = LocalModelService()

        self.assertEqual(service._stable_vehicle_count("live1", 2), 2)
        self.assertEqual(service._stable_vehicle_count("live1", 2), 2)
        self.assertEqual(service._stable_vehicle_count("live1", 3), 3)

    def test_single_count_drop_is_smoothed_until_it_is_stable(self):
        service = LocalModelService()
        for count in (3, 3, 3):
            service._stable_vehicle_count("live1", count)

        self.assertEqual(service._stable_vehicle_count("live1", 2), 3)
        for _ in range(3):
            smoothed = service._stable_vehicle_count("live1", 2)
        self.assertEqual(smoothed, 2)

    def test_weak_untracked_targets_are_entry_candidates_only_near_frame_edges(self):
        height = 1000

        self.assertTrue(is_frame_entry_candidate((100, 100, 200, 200), height))
        self.assertTrue(is_frame_entry_candidate((100, 700, 200, 900), height))
        self.assertFalse(is_frame_entry_candidate((100, 300, 200, 600), height))

    def test_bytetrack_buffer_keeps_the_fork_tuned_value(self):
        config_path = Path(__file__).resolve().parents[1] / "data" / "bytetrack_sandtable.yaml"

        self.assertIn("track_buffer: 18", config_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
