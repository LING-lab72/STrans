"""Classify road-bundle arms at nodes and emit conservative manual flow templates."""

from __future__ import annotations

import argparse
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import orjson


def angular_separation(a: float, b: float) -> float:
    difference = abs(a - b) % 360
    return min(difference, 360 - difference)


def arm_for_bundle(bundle: dict[str, Any], node_id: str, nodes: dict[str, dict[str, Any]], lanes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    other_node_id = next(item for item in bundle["endpointIds"] if item != node_id)
    node, other = nodes[node_id]["position"], nodes[other_node_id]["position"]
    angle = (math.degrees(math.atan2(other["y"] - node["y"], other["x"] - node["x"])) + 360) % 360
    lane_ids = [lane_id for lane_id in bundle.get("laneIds", []) if lane_id in lanes]
    direction = {"x": math.cos(math.radians(angle)), "y": math.sin(math.radians(angle))}
    normal = {"x": -direction["y"], "y": direction["x"]}
    def lateral_position(lane_id: str) -> float:
        path = lanes[lane_id].get("geometry", {}).get("renderPath", [])
        if not path:
            return float(lane_ids.index(lane_id))
        endpoint = min((path[0], path[-1]), key=lambda point: math.hypot(point["x"] - node["x"], point["y"] - node["y"]))
        return endpoint["x"] * normal["x"] + endpoint["y"] * normal["y"]
    lane_ids.sort(key=lateral_position)
    return {
        "roadBundleId": bundle["id"],
        "otherNodeId": other_node_id,
        "angleDegrees": round(angle, 3),
        "laneIds": lane_ids,
        "incomingLaneIds": [lane_id for lane_id in lane_ids if lanes[lane_id]["traffic"]["targetNodeId"] == node_id],
        "outgoingLaneIds": [lane_id for lane_id in lane_ids if lanes[lane_id]["traffic"]["sourceNodeId"] == node_id],
    }


def suggested_mode(incoming_count: int, outgoing_count: int) -> str:
    if incoming_count > outgoing_count:
        return "merge"
    if incoming_count < outgoing_count:
        return "split"
    return "continue"


def classify_nodes(road: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = {item["id"]: item for item in road.get("nodes", [])}
    lanes = {item["id"]: item for item in road.get("lanes", [])}
    bundles_by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bundle in road.get("roadBundles", []):
        for node_id in bundle.get("endpointIds", []):
            if node_id in nodes:
                bundles_by_node[node_id].append(bundle)
    results = []
    for node_id, node in nodes.items():
        arms = [arm_for_bundle(bundle, node_id, nodes, lanes) for bundle in bundles_by_node.get(node_id, [])]
        arms.sort(key=lambda item: item["angleDegrees"])
        arm_count = len(arms)
        trunk_ids: list[str] = []
        max_separation = 0.0
        if arm_count >= 2:
            _, first, second = max(((angular_separation(a["angleDegrees"], b["angleDegrees"]), a, b) for index, a in enumerate(arms) for b in arms[index + 1:]), key=lambda item: item[0])
            max_separation = angular_separation(first["angleDegrees"], second["angleDegrees"])
            if max_separation >= 135:
                trunk_ids = [first["roadBundleId"], second["roadBundleId"]]
        if arm_count == 0:
            classification, policy = "isolated", "none"
        elif arm_count == 1:
            classification, policy = "terminal", "road_port_only"
        elif arm_count == 2:
            classification = "simple_continuation" if max_separation >= 135 else "simple_corner"
            policy = "manual_road_bundle_mapping"
        elif arm_count == 3 and trunk_ids:
            classification, policy = "simple_branch", "manual_road_bundle_mapping"
        elif arm_count == 3:
            classification, policy = "three_way_complex", "road_port_only"
        else:
            classification, policy = "chaotic_intersection", "road_port_only"
        assignments = []
        if policy == "manual_road_bundle_mapping":
            for source in arms:
                for target in arms:
                    if source is target or not source["incomingLaneIds"] or not target["outgoingLaneIds"]:
                        continue
                    relation = "trunk_continuation" if source["roadBundleId"] in trunk_ids and target["roadBundleId"] in trunk_ids else "branch_merge_or_split"
                    assignments.append({
                        "id": f"{source['roadBundleId']}->{target['roadBundleId']}",
                        "status": "needs_review",
                        "relation": relation,
                        "fromRoadBundleId": source["roadBundleId"],
                        "toRoadBundleId": target["roadBundleId"],
                        "incomingLaneIds": source["incomingLaneIds"],
                        "outgoingLaneIds": target["outgoingLaneIds"],
                        "suggestedMode": suggested_mode(len(source["incomingLaneIds"]), len(target["outgoingLaneIds"])),
                        "laneAssignments": [],
                    })
        results.append({
            "nodeId": node_id,
            "nodeType": node.get("type"),
            "position": node["position"],
            "classification": classification,
            "assignmentPolicy": policy,
            "armCount": arm_count,
            "maximumArmSeparationDegrees": round(max_separation, 3),
            "trunkRoadBundleIds": trunk_ids,
            "arms": arms,
            "roadBundleAssignments": assignments,
        })
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--road", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    nodes = classify_nodes(orjson.loads(args.road.read_bytes()))
    counts = Counter(item["classification"] for item in nodes)
    payload = {
        "schema": "road_logic_modeler.node-flow-template.v1",
        "nodes": nodes,
        "summary": {"nodeCount": len(nodes), "classificationCounts": dict(sorted(counts.items())), "manualReviewNodeCount": sum(item["assignmentPolicy"] == "manual_road_bundle_mapping" for item in nodes), "chaoticNodeCount": sum(item["assignmentPolicy"] == "road_port_only" and item["armCount"] >= 3 for item in nodes)},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2))
    print(orjson.dumps({"output": str(args.output), "summary": payload["summary"]}).decode())


if __name__ == "__main__":
    main()
