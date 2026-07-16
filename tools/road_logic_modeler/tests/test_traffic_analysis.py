import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("traffic_analysis", ROOT / "traffic_analysis.py")
ANALYZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYZER)


class TrafficAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.road = {
            "world": {"width": 120, "height": 40, "gridSize": 10},
            "nodes": [
                {"id": "a", "position": {"x": 0, "y": 0}},
                {"id": "b", "position": {"x": 100, "y": 0}},
            ],
            "lanes": [
                {"id": "lane_a", "roadBundleId": "road::a::b", "traffic": {"sourceNodeId": "a", "targetNodeId": "b"}, "markings": {"leftBoundary": "dashed", "rightBoundary": "solid"}, "geometry": {"width": 10, "renderPath": [{"x": 0, "y": 0}, {"x": 100, "y": 0}]}},
                {"id": "lane_b", "roadBundleId": "road::a::b", "traffic": {"sourceNodeId": "a", "targetNodeId": "b"}, "markings": {"leftBoundary": "solid", "rightBoundary": "dashed"}, "geometry": {"width": 10, "renderPath": [{"x": 0, "y": 12}, {"x": 100, "y": 12}]}},
            ],
        }

    def test_assigns_lanes_and_emits_candidate_reverse_and_solid_crossing_events(self):
        observations = [
            {"cameraId": "cam_1", "trackId": "forward", "timestampMs": 0, "worldPoint": {"x": 10, "y": 0}},
            {"cameraId": "cam_1", "trackId": "forward", "timestampMs": 1000, "worldPoint": {"x": 30, "y": 0}},
            {"cameraId": "cam_1", "trackId": "forward", "timestampMs": 2000, "worldPoint": {"x": 50, "y": 0}},
            {"cameraId": "cam_1", "trackId": "reverse", "timestampMs": 0, "worldPoint": {"x": 80, "y": 0}},
            {"cameraId": "cam_1", "trackId": "reverse", "timestampMs": 1000, "worldPoint": {"x": 55, "y": 0}},
            {"cameraId": "cam_1", "trackId": "reverse", "timestampMs": 2000, "worldPoint": {"x": 30, "y": 0}},
            {"cameraId": "cam_1", "trackId": "cross", "timestampMs": 0, "worldPoint": {"x": 20, "y": 0}},
            {"cameraId": "cam_1", "trackId": "cross", "timestampMs": 1000, "worldPoint": {"x": 30, "y": 12}},
        ]
        result = ANALYZER.analyze_observations(self.road, observations)
        self.assertEqual(result["summary"]["trackedVehicleCount"], 3)
        self.assertEqual(result["laneFlow"]["lane_a"]["uniqueTrackCount"], 3)
        event_types = {event["type"] for event in result["events"]}
        self.assertIn("reverse_direction_candidate", event_types)
        self.assertIn("solid_boundary_crossing_candidate", event_types)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "heatmap.png"
            ANALYZER.render_heatmap(self.road, result, output)
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 0)
            base = Path(temp) / "base.png"
            ANALYZER.render_road_base(self.road, base)
            self.assertTrue(base.is_file())
            self.assertGreater(base.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
