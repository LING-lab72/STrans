import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("road_surface_renderer", ROOT / "road_surface_renderer.py")
RENDERER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDERER)


class RoadSurfaceRendererTest(unittest.TestCase):
    def test_traces_same_direction_lanes_through_a_non_branching_node(self):
        road = {
            "world": {"width": 240, "height": 80},
            "nodes": [{"id": "a", "position": {"x": 0, "y": 40}}, {"id": "b", "position": {"x": 100, "y": 40}}, {"id": "c", "position": {"x": 200, "y": 40}}],
            "buildings": [],
            "lanes": [
                {"id": "first", "traffic": {"sourceNodeId": "a", "targetNodeId": "b"}, "markings": {"leftBoundary": "solid", "rightBoundary": "dashed"}, "geometry": {"width": 12, "renderPath": [{"x": 0, "y": 40}, {"x": 100, "y": 40}]}},
                {"id": "second", "traffic": {"sourceNodeId": "b", "targetNodeId": "c"}, "markings": {"leftBoundary": "solid", "rightBoundary": "dashed"}, "geometry": {"width": 12, "renderPath": [{"x": 100, "y": 40}, {"x": 200, "y": 40}]}},
            ],
        }
        traces = RENDERER.build_lane_traces(road)
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["laneIds"], ["first", "second"])
        self.assertGreater(len(traces[0]["path"]), 4)
        self.assertEqual(traces[0]["continuities"][0]["atNodeId"], "b")


if __name__ == "__main__":
    unittest.main()
