import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("road_logic_analysis", ROOT / "road_logic_analysis.py")
ANALYZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYZER)


class RoadLogicAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.model = {
            "world": {"width": 100, "height": 100, "gridSize": 20},
            "nodes": [
                {"id": "n1", "type": "junction", "x": 20, "y": 40},
                {"id": "n2", "type": "boundary", "x": 80, "y": 40},
            ],
            "lanes": [
                {"id": "forward", "endpoint1": "n1", "endpoint2": "n2", "direction": "1-2", "width": 12, "controlPoints": [], "leftLineStyle": "solid", "rightLineStyle": "dashed"},
                {"id": "reverse", "endpoint1": "n2", "endpoint2": "n1", "direction": "1-2", "width": 12, "controlPoints": [], "leftLineStyle": "dashed", "rightLineStyle": "solid"},
            ],
            "laneEndpointGroups": [],
            "buildings": [{"id": "b1", "x": 50, "y": 80, "width": 20, "height": 20}],
            "cameraCalibrations": [{"id": "cal1", "image": {"name": "frame.jpg", "dataUrl": "data:image/jpeg;base64,AA=="}, "points": [{"id": "p1", "x": 100, "y": 100}], "lines": []}],
            "cameras": [{"id": "cam1", "x": 20, "y": 20, "direction": 0, "fov": 90, "range": 80, "calibrationId": "cal1", "coverage": {"gridCells": []}, "pointBindings": [{"imagePointId": "p1", "worldPoint": {"x": 40, "y": 46, "height": 500}}]}],
        }

    def test_reconstructs_bidirectional_bundle_and_point_relation(self):
        result = ANALYZER.analyze_model(self.model)
        bundle = result["topology"]["roadBundles"][0]
        self.assertEqual(set(bundle["laneIds"]), {"forward", "reverse"})
        self.assertEqual(bundle["directionalLaneIds"]["n1->n2"], ["forward"])
        self.assertEqual(bundle["directionalLaneIds"]["n2->n1"], ["reverse"])
        relation = result["imagePointRelations"][0]
        self.assertEqual(relation["imagePointId"], "p1")
        self.assertEqual(relation["renderedLaneId"], "reverse")
        self.assertEqual(relation["nearbyLaneIds"], ["reverse"])
        self.assertLess(relation["laneCandidates"][0]["distance"], relation["laneCandidates"][1]["distance"])

    def test_computes_grid_coverage_for_lanes_buildings_and_camera(self):
        result = ANALYZER.analyze_model(self.model)
        coverage = result["gridCoverage"]
        self.assertGreater(coverage["summary"]["laneCoveredCellCount"], 0)
        self.assertGreater(coverage["summary"]["buildingCoveredCellCount"], 0)
        self.assertGreater(coverage["summary"]["cameraFovCoveredCellCount"], 0)

    def test_explicit_point_binding_overrides_geometric_guessing(self):
        model = {**self.model, "cameras": [{**self.model["cameras"][0], "pointBindings": [{
            "imagePointId": "p1", "worldPoint": {"x": 40, "y": 46, "height": 500},
            "laneId": "forward", "buildingId": "b1", "nodeId": "n2"
        }]}]}
        relation = ANALYZER.map_image_points(model, ANALYZER.compute_grid_coverage(model))[0]
        self.assertEqual(relation["renderedLaneId"], "forward")
        self.assertEqual(relation["buildingIds"], ["b1"])
        self.assertEqual(relation["nearestNodeIds"][0], "n2")

    def test_replaces_data_url_with_capture_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            capture = Path(temp) / "frame.jpg"
            capture.write_bytes(b"not-a-real-jpeg")
            compact, changes = ANALYZER.externalize_calibration_images(self.model, Path(temp))
        image = compact["cameraCalibrations"][0]["image"]
        self.assertNotIn("dataUrl", image)
        self.assertEqual(image["src"], "captures/frame.jpg")
        self.assertEqual(changes[0]["status"], "externalized")

    def test_builds_algorithm_ready_graph_and_prunes_unused_calibrations(self):
        model = {**self.model, "cameraCalibrations": self.model["cameraCalibrations"] + [{"id": "unused", "points": [], "lines": []}]}
        graph = ANALYZER.build_road_graph(model)
        self.assertEqual(graph["summary"]["nodeCount"], 2)
        self.assertEqual(graph["summary"]["directedEdgeCount"], 2)
        self.assertEqual(graph["summary"]["weakComponentCount"], 1)
        compact, removed = ANALYZER.prune_unused_calibrations(model)
        self.assertEqual([item["id"] for item in compact["cameraCalibrations"]], ["cal1"])
        self.assertEqual(removed, ["unused"])

    def test_assigns_same_direction_merge_without_crossing_branch(self):
        model = {
            "world": {"width": 200, "height": 120, "gridSize": 20},
            "nodes": [
                {"id": "west_a", "x": 10, "y": 45},
                {"id": "west_b", "x": 10, "y": 55},
                {"id": "junction", "x": 100, "y": 50},
                {"id": "east", "x": 190, "y": 50},
                {"id": "south", "x": 100, "y": 110},
            ],
            "lanes": [
                {"id": "in_a", "endpoint1": "west_a", "endpoint2": "junction", "direction": "1-2", "width": 8},
                {"id": "in_b", "endpoint1": "west_b", "endpoint2": "junction", "direction": "1-2", "width": 8},
                {"id": "out_straight", "endpoint1": "junction", "endpoint2": "east", "direction": "1-2", "width": 10},
                {"id": "out_branch", "endpoint1": "junction", "endpoint2": "south", "direction": "1-2", "width": 10},
            ],
            "cameraCalibrations": [],
            "cameras": [],
            "buildings": [],
        }
        vector = ANALYZER.build_lane_vector_model(model)
        junction = next(item for item in vector["junctions"] if item["nodeId"] == "junction")
        pairs = {(item["fromLaneId"], item["toLaneId"]) for item in junction["assignments"]}
        self.assertEqual(pairs, {("in_a", "out_straight"), ("in_b", "out_straight")})
        corridors = {item["id"]: item for item in vector["corridors"]}
        self.assertEqual(len(corridors), 1)
        self.assertEqual(set(corridors["corridor_1"]["laneIds"]), {"in_a", "in_b", "out_straight"})

    def test_only_road_internal_nodes_drive_automatic_lane_branch_analysis(self):
        model = {
            "world": {"width": 300, "height": 160, "gridSize": 20},
            "nodes": [
                {"id": "west", "type": "boundary", "x": 10, "y": 80},
                {"id": "chaotic_crossing", "type": "junction", "x": 90, "y": 80},
                {"id": "fork", "type": "lane_point", "x": 170, "y": 80},
                {"id": "east", "type": "boundary", "x": 290, "y": 60},
                {"id": "exit", "type": "boundary", "x": 240, "y": 150},
            ],
            "lanes": [
                {"id": "before_crossing", "endpoint1": "west", "endpoint2": "chaotic_crossing", "direction": "1-2", "width": 8},
                {"id": "after_crossing", "endpoint1": "chaotic_crossing", "endpoint2": "fork", "direction": "1-2", "width": 8},
                {"id": "straight", "endpoint1": "fork", "endpoint2": "east", "direction": "1-2", "width": 8},
                {"id": "branch", "endpoint1": "fork", "endpoint2": "exit", "direction": "1-2", "width": 8},
            ],
            "laneEndpointGroups": [{"id": "fork_section", "nodeIds": ["fork"], "order": "auto"}],
            "cameraCalibrations": [], "cameras": [], "buildings": [],
        }

        vector = ANALYZER.build_lane_vector_model(model, direction_cosine_threshold=0.5)
        analyzed_node_ids = {item["nodeId"] for item in vector["junctions"]}

        self.assertNotIn("chaotic_crossing", analyzed_node_ids)
        self.assertIn("fork", analyzed_node_ids)

    def test_uses_image_line_to_resolve_an_ambiguous_lane_point(self):
        model = {**self.model}
        model["cameraCalibrations"] = [{"id": "cal1", "points": [{"id": "p1", "x": 100, "y": 100}, {"id": "p2", "x": 200, "y": 100}], "lines": [{"id": "line1", "fromPointId": "p1", "toPointId": "p2"}]}]
        model["cameras"] = [{**self.model["cameras"][0], "pointBindings": [
            {"imagePointId": "p1", "worldPoint": {"x": 40, "y": 46, "height": 500}},
            {"imagePointId": "p2", "worldPoint": {"x": 50, "y": 40, "height": 500}},
        ]}]
        vector = ANALYZER.build_lane_vector_model(model)
        line = vector["cameras"][0]["imageLineVectors"][0]
        self.assertEqual(line["kind"], "lane_segment")
        self.assertEqual(line["fromLaneId"], "reverse")
        self.assertEqual(line["toLaneId"], "reverse")

    def test_uses_target_arrow_to_connect_a_turning_lane(self):
        model = {
            "world": {"width": 100, "height": 100, "gridSize": 20},
            "nodes": [
                {"id": "north", "x": 50, "y": 10}, {"id": "junction", "x": 50, "y": 50},
                {"id": "west", "x": 10, "y": 50}, {"id": "south", "x": 50, "y": 90},
            ],
            "lanes": [
                {"id": "approach", "endpoint1": "north", "endpoint2": "junction", "direction": "1-2", "width": 8, "endpoint2Arrow": "forward_right"},
                {"id": "right_exit", "endpoint1": "junction", "endpoint2": "west", "direction": "1-2", "width": 8},
                {"id": "straight_exit", "endpoint1": "junction", "endpoint2": "south", "direction": "1-2", "width": 8},
            ],
            "cameraCalibrations": [], "cameras": [], "buildings": [],
        }
        vector = ANALYZER.build_lane_vector_model(model)
        transitions = {(item["fromLaneId"], item["toLaneId"], item["movement"]) for item in vector["laneTransitions"]}
        self.assertIn(("approach", "right_exit", "right"), transitions)
        self.assertIn(("approach", "straight_exit", "forward"), transitions)
        next_lanes = vector["laneFlowGraph"]["adjacency"]["approach"]
        self.assertEqual({item["toLaneId"] for item in next_lanes}, {"right_exit", "straight_exit"})

    def test_builds_baseline_lane_and_camera_mapping_exports_without_turn_inference(self):
        exports = ANALYZER.build_baseline_exports(self.model, "fixture.json", "fixture-sha256")
        self.assertEqual(exports["roadLane"]["schema"], "road_logic_modeler.road-lane.v1")
        self.assertEqual(exports["roadLane"]["summary"]["directedLaneCount"], 2)
        self.assertNotIn("laneTransitions", exports["roadLane"])
        lane = next(item for item in exports["roadLane"]["lanes"] if item["id"] == "forward")
        self.assertEqual(lane["traffic"], {"direction": "1-2", "sourceNodeId": "n1", "targetNodeId": "n2", "sourceArrow": None, "targetArrow": None})
        self.assertEqual(lane["markings"], {"leftBoundary": "solid", "rightBoundary": "dashed"})
        self.assertEqual(lane["geometry"]["width"], 12)
        self.assertNotIn("leftLineStyle", lane)
        self.assertEqual(exports["roadLane"]["buildings"][0]["id"], "b1")
        self.assertEqual(exports["cameraMapping"]["schema"], "road_logic_modeler.camera-mapping.v1")
        point = exports["cameraMapping"]["cameras"][0]["points"][0]
        self.assertEqual(point["laneId"], "reverse")
        self.assertNotIn("gridCell", point)
        self.assertEqual(exports["manifest"]["sourceSha256"], "fixture-sha256")


if __name__ == "__main__":
    unittest.main()
