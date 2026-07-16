import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("node_flow_classifier", ROOT / "node_flow_classifier.py")
CLASSIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLASSIFIER)


class NodeFlowClassifierTest(unittest.TestCase):
    def test_classifies_two_three_and_four_arm_nodes_conservatively(self):
        road = {
            "nodes": [
                {"id": "west", "position": {"x": 0, "y": 100}},
                {"id": "two", "position": {"x": 100, "y": 100}},
                {"id": "three", "position": {"x": 200, "y": 100}},
                {"id": "north", "position": {"x": 200, "y": 0}},
                {"id": "four", "position": {"x": 300, "y": 100}},
                {"id": "south", "position": {"x": 300, "y": 200}},
                {"id": "east", "position": {"x": 400, "y": 100}},
                {"id": "four_north", "position": {"x": 300, "y": 0}},
            ],
            "lanes": [],
            "roadBundles": [
                {"id": "w-two", "endpointIds": ["west", "two"], "laneIds": [], "directionalLaneIds": {}},
                {"id": "two-three", "endpointIds": ["two", "three"], "laneIds": [], "directionalLaneIds": {}},
                {"id": "three-north", "endpointIds": ["three", "north"], "laneIds": [], "directionalLaneIds": {}},
                {"id": "three-four", "endpointIds": ["three", "four"], "laneIds": [], "directionalLaneIds": {}},
                {"id": "four-south", "endpointIds": ["four", "south"], "laneIds": [], "directionalLaneIds": {}},
                {"id": "four-east", "endpointIds": ["four", "east"], "laneIds": [], "directionalLaneIds": {}},
                {"id": "four-north", "endpointIds": ["four", "four_north"], "laneIds": [], "directionalLaneIds": {}},
            ],
        }

        classified = {item["nodeId"]: item for item in CLASSIFIER.classify_nodes(road)}

        self.assertEqual(classified["two"]["classification"], "simple_continuation")
        self.assertEqual(classified["three"]["classification"], "simple_branch")
        self.assertEqual(set(classified["three"]["trunkRoadBundleIds"]), {"two-three", "three-four"})
        self.assertEqual(classified["four"]["classification"], "chaotic_intersection")
        self.assertEqual(classified["four"]["assignmentPolicy"], "road_port_only")

    def test_sorts_lane_ids_by_their_physical_order_at_the_node(self):
        road = {
            "nodes": [{"id": "a", "position": {"x": 0, "y": 100}}, {"id": "b", "position": {"x": 100, "y": 100}}],
            "lanes": [
                {"id": "lower", "traffic": {"sourceNodeId": "a", "targetNodeId": "b"}, "geometry": {"renderPath": [{"x": 0, "y": 110}, {"x": 100, "y": 110}]}},
                {"id": "upper", "traffic": {"sourceNodeId": "a", "targetNodeId": "b"}, "geometry": {"renderPath": [{"x": 0, "y": 90}, {"x": 100, "y": 90}]}},
            ],
            "roadBundles": [{"id": "road", "endpointIds": ["a", "b"], "laneIds": ["lower", "upper"], "directionalLaneIds": {}}],
        }
        classified = {item["nodeId"]: item for item in CLASSIFIER.classify_nodes(road)}
        self.assertEqual(classified["a"]["arms"][0]["laneIds"], ["upper", "lower"])


if __name__ == "__main__":
    unittest.main()
