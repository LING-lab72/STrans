import importlib.util
import unittest
from pathlib import Path

from shapely.geometry import LineString, shape


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("junction_geometry_compiler", ROOT / "junction_geometry_compiler.py")
COMPILER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPILER)


class JunctionGeometryCompilerTest(unittest.TestCase):
    def test_compiles_cross_node_into_one_surface_with_ports_and_crosswalks(self):
        road = {
            "world": {"width": 240, "height": 240},
            "nodes": [
                {"id": "center", "position": {"x": 120, "y": 120}},
                {"id": "north", "position": {"x": 120, "y": 0}},
                {"id": "east", "position": {"x": 240, "y": 120}},
                {"id": "south", "position": {"x": 120, "y": 240}},
                {"id": "west", "position": {"x": 0, "y": 120}},
            ],
            "buildings": [],
            "lanes": [
                {"id": "north_in", "roadBundleId": "north", "traffic": {"sourceNodeId": "north", "targetNodeId": "center"}, "geometry": {"width": 12, "renderPath": [{"x": 114, "y": 0}, {"x": 114, "y": 120}]}, "markings": {"leftBoundary": "solid", "rightBoundary": "dashed"}},
                {"id": "north_out", "roadBundleId": "north", "traffic": {"sourceNodeId": "center", "targetNodeId": "north"}, "geometry": {"width": 12, "renderPath": [{"x": 126, "y": 120}, {"x": 126, "y": 0}]}, "markings": {"leftBoundary": "dashed", "rightBoundary": "solid"}},
                {"id": "east_out", "roadBundleId": "east", "traffic": {"sourceNodeId": "center", "targetNodeId": "east"}, "geometry": {"width": 12, "renderPath": [{"x": 120, "y": 114}, {"x": 240, "y": 114}]}, "markings": {"leftBoundary": "solid", "rightBoundary": "solid"}},
                {"id": "south_out", "roadBundleId": "south", "traffic": {"sourceNodeId": "center", "targetNodeId": "south"}, "geometry": {"width": 12, "renderPath": [{"x": 114, "y": 120}, {"x": 114, "y": 240}]}, "markings": {"leftBoundary": "solid", "rightBoundary": "solid"}},
                {"id": "west_in", "roadBundleId": "west", "traffic": {"sourceNodeId": "west", "targetNodeId": "center"}, "geometry": {"width": 12, "renderPath": [{"x": 0, "y": 126}, {"x": 120, "y": 126}]}, "markings": {"leftBoundary": "solid", "rightBoundary": "solid"}},
            ],
        }
        rules = {"nodeId": "center", "cutback": 34, "connections": [{"fromLaneId": "north_in", "toLaneId": "south_out"}, {"fromLaneId": "west_in", "toLaneId": "east_out"}]}

        compiled = COMPILER.compile_junction(road, rules)

        surface = shape(compiled["surface"])
        self.assertTrue(surface.is_valid)
        self.assertEqual(compiled["summary"]["approachCount"], 4)
        self.assertEqual(len(compiled["crosswalks"]), 4)
        self.assertNotIn("nodePoint", compiled)
        for connection in compiled["laneConnections"]:
            self.assertTrue(surface.buffer(0.01).covers(LineString([(point["x"], point["y"]) for point in connection["path"]])))


if __name__ == "__main__":
    unittest.main()
