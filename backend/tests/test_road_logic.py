import unittest

from app.services.road_logic import (
    RoadLogicService,
    _distance_to_path,
    _distance_to_segment,
    _point_in_polygon,
)


class RoadGeometryTests(unittest.TestCase):
    def test_distance_to_segment_projects_inside_the_segment(self):
        distance = _distance_to_segment((5, 3), {"x": 0, "y": 0}, {"x": 10, "y": 0})

        self.assertAlmostEqual(distance, 3.0)

    def test_distance_to_path_returns_infinity_when_path_has_no_segment(self):
        self.assertEqual(_distance_to_path((1, 1), [{"x": 0, "y": 0}]), float("inf"))

    def test_point_in_polygon_distinguishes_inside_and_outside_points(self):
        polygon = [
            {"x": 0, "y": 0},
            {"x": 10, "y": 0},
            {"x": 10, "y": 10},
            {"x": 0, "y": 10},
        ]

        self.assertTrue(_point_in_polygon((5, 5), polygon))
        self.assertFalse(_point_in_polygon((15, 5), polygon))

    def test_reliable_vehicle_box_rejects_tiny_or_flat_road_markings(self):
        self.assertTrue(RoadLogicService._is_reliable_vehicle_box([0, 0, 40, 30]))
        self.assertFalse(RoadLogicService._is_reliable_vehicle_box([0, 0, 10, 80]))
        self.assertFalse(RoadLogicService._is_reliable_vehicle_box([0, 0, 80, 10]))

    def test_congestion_track_requires_repeated_observations(self):
        service = RoadLogicService()
        service._update_congestion_track(
            track_key="camera:1",
            camera_id="camera",
            track_id=1,
            lane_id="lane-1",
            junction_id=None,
            world_point=(10, 20),
            speed_cm_s=5,
            now=100,
        )
        service._update_congestion_track(
            track_key="camera:1",
            camera_id="camera",
            track_id=1,
            lane_id="lane-1",
            junction_id=None,
            world_point=(11, 20),
            speed_cm_s=4,
            now=101,
        )

        self.assertEqual(service._congestion_tracks["camera:1"]["seen_count"], 2)

    def test_stationary_vehicle_emits_one_illegal_stop_event_after_dwell_limit(self):
        service = RoadLogicService()
        observation = {
            "lane_name": "测试车道",
            "camera_id": "camera",
            "bbox": [10, 20, 50, 80],
        }

        first = service._update_stop_state("camera:1", (10, 10), 100, observation, "京A12345")
        alert = service._update_stop_state("camera:1", (11, 10), 131, observation, "京A12345")
        duplicate = service._update_stop_state("camera:1", (11, 10), 132, observation, "京A12345")

        self.assertIsNone(first)
        self.assertEqual(alert.type, "illegal_stop")
        self.assertIn("京A12345", alert.description)
        self.assertIsNone(duplicate)


if __name__ == "__main__":
    unittest.main()
