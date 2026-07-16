"""Offline parser and topology analyzer for Road Logic Modeler JSON exports."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import orjson
from PIL import Image, ImageDraw


def distance(a: dict[str, float], b: dict[str, float]) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def distance_to_segment(point: dict[str, float], a: dict[str, float], b: dict[str, float]) -> float:
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    length_sq = dx * dx + dy * dy
    if not length_sq:
        return distance(point, a)
    t = max(0.0, min(1.0, ((point["x"] - a["x"]) * dx + (point["y"] - a["y"]) * dy) / length_sq))
    return distance(point, {"x": a["x"] + dx * t, "y": a["y"] + dy * t})


def lane_path(lane: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> list[dict[str, float]]:
    a, b = nodes.get(lane.get("endpoint1")), nodes.get(lane.get("endpoint2"))
    if not a or not b:
        return []
    controls = [{"x": float(p[0]), "y": float(p[1])} for p in lane.get("controlPoints", []) if isinstance(p, list) and len(p) >= 2]
    points = [{"x": float(a["x"]), "y": float(a["y"])}] + controls + [{"x": float(b["x"]), "y": float(b["y"])}]
    if lane.get("interpolation") == "quadratic" and len(points) >= 3:
        return sample_quadratic(points[0], points[1], points[-1])
    if lane.get("interpolation") == "cubic" and len(points) >= 4:
        return sample_cubic(points[0], points[1], points[2], points[-1])
    return points


def sample_quadratic(a: dict[str, float], control: dict[str, float], b: dict[str, float], count: int = 24) -> list[dict[str, float]]:
    return [{"x": (1 - t) ** 2 * a["x"] + 2 * (1 - t) * t * control["x"] + t ** 2 * b["x"], "y": (1 - t) ** 2 * a["y"] + 2 * (1 - t) * t * control["y"] + t ** 2 * b["y"]} for t in (i / count for i in range(count + 1))]


def sample_cubic(a: dict[str, float], c1: dict[str, float], c2: dict[str, float], b: dict[str, float], count: int = 32) -> list[dict[str, float]]:
    return [{"x": (1 - t) ** 3 * a["x"] + 3 * (1 - t) ** 2 * t * c1["x"] + 3 * (1 - t) * t ** 2 * c2["x"] + t ** 3 * b["x"], "y": (1 - t) ** 3 * a["y"] + 3 * (1 - t) ** 2 * t * c1["y"] + 3 * (1 - t) * t ** 2 * c2["y"] + t ** 3 * b["y"]} for t in (i / count for i in range(count + 1))]


def offset_polyline(points: list[dict[str, float]], offset: float) -> list[dict[str, float]]:
    if not offset or len(points) < 2:
        return [{"x": point["x"], "y": point["y"]} for point in points]
    shifted = []
    for index, point in enumerate(points):
        previous, following = points[max(0, index - 1)], points[min(len(points) - 1, index + 1)]
        dx, dy = following["x"] - previous["x"], following["y"] - previous["y"]
        length = math.hypot(dx, dy) or 1.0
        shifted.append({"x": point["x"] + (-dy / length) * offset, "y": point["y"] + (dx / length) * offset})
    return shifted


def rendered_lane_layouts(model: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = {node["id"]: node for node in model.get("nodes", []) if node.get("id")}
    bundles: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for lane in model.get("lanes", []):
        if lane.get("endpoint1") in nodes and lane.get("endpoint2") in nodes:
            bundles[tuple(sorted((lane["endpoint1"], lane["endpoint2"])))].append(lane)
    layouts = []
    for endpoint_ids, lanes in bundles.items():
        ordered = sorted(lanes, key=lambda item: (item.get("renderOrder", 0), item.get("id", "")))
        canonical_start = endpoint_ids[0]
        for index, lane in enumerate(ordered):
            path = lane_path(lane, nodes)
            if lane.get("endpoint1") != canonical_start:
                path = list(reversed(path))
            offset_index = index - (len(ordered) - 1) / 2
            width = float(lane.get("width", 28))
            layouts.append({"lane": lane, "roadBundleId": f"road::{endpoint_ids[0]}::{endpoint_ids[1]}", "canonicalStart": canonical_start, "path": offset_polyline(path, offset_index * width), "width": width, "offsetIndex": offset_index})
    return layouts


def distance_to_polyline(point: dict[str, float], path: list[dict[str, float]]) -> float:
    if len(path) < 2:
        return math.inf
    return min(distance_to_segment(point, a, b) for a, b in zip(path, path[1:]))


def side_from(node: dict[str, Any], other: dict[str, float]) -> str:
    degrees = (math.degrees(math.atan2(other["y"] - node["y"], other["x"] - node["x"])) + 360) % 360
    if degrees < 45 or degrees >= 315:
        return "east"
    if degrees < 135:
        return "south"
    if degrees < 225:
        return "west"
    return "north"


def directed_endpoints(lane: dict[str, Any]) -> tuple[str, str]:
    first, second = lane.get("endpoint1", ""), lane.get("endpoint2", "")
    return (first, second) if lane.get("direction", "1-2") == "1-2" else (second, first)


def point_in_camera_fov(point: dict[str, float], camera: dict[str, Any]) -> bool:
    dx, dy = point["x"] - camera["x"], point["y"] - camera["y"]
    radius = math.hypot(dx, dy)
    if radius > float(camera.get("range", 0)):
        return False
    if radius == 0:
        return True
    angle = (math.degrees(math.atan2(dy, dx)) + 360) % 360
    delta = abs((angle - float(camera.get("direction", 0)) + 180) % 360 - 180)
    return delta <= float(camera.get("fov", 60)) / 2


def reconstruct_topology(model: dict[str, Any]) -> dict[str, Any]:
    nodes = {node["id"]: node for node in model.get("nodes", []) if node.get("id")}
    lanes = model.get("lanes", [])
    bundles: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    invalid_lanes = []
    node_sides: dict[str, dict[str, list[str]]] = {node_id: {side: [] for side in ("north", "east", "south", "west")} for node_id in nodes}
    for lane in lanes:
        a_id, b_id = lane.get("endpoint1"), lane.get("endpoint2")
        if a_id not in nodes or b_id not in nodes or a_id == b_id:
            invalid_lanes.append(lane.get("id"))
            continue
        bundles[tuple(sorted((a_id, b_id)))].append(lane)
        path = lane_path(lane, nodes)
        for node_id, other_index in ((a_id, 1), (b_id, -2)):
            nearby = path[other_index] if len(path) > 2 else nodes[b_id if node_id == a_id else a_id]
            node_sides[node_id][side_from(nodes[node_id], nearby)].append(lane.get("id"))

    road_bundles = []
    for (a_id, b_id), bundle_lanes in sorted(bundles.items()):
        directions: dict[str, list[str]] = {f"{a_id}->{b_id}": [], f"{b_id}->{a_id}": []}
        for lane in sorted(bundle_lanes, key=lambda item: (item.get("renderOrder", 0), item.get("id", ""))):
            source, target = directed_endpoints(lane)
            directions.setdefault(f"{source}->{target}", []).append(lane.get("id"))
        road_bundles.append({
            "id": f"road::{a_id}::{b_id}",
            "endpointIds": [a_id, b_id],
            "laneIds": [lane.get("id") for lane in bundle_lanes],
            "directionalLaneIds": directions,
            "laneStyles": [{"laneId": lane.get("id"), "left": lane.get("leftLineStyle"), "right": lane.get("rightLineStyle")} for lane in bundle_lanes],
        })
    return {"roadBundles": road_bundles, "nodeSides": node_sides, "invalidLaneIds": invalid_lanes}


def compute_grid_coverage(model: dict[str, Any]) -> dict[str, Any]:
    world = model.get("world", {})
    width, height, step = float(world.get("width", 0)), float(world.get("height", 0)), float(world.get("gridSize", 20))
    layouts = rendered_lane_layouts(model)
    occupied = []
    lane_cells = building_cells = camera_cells = 0
    for row in range(math.ceil(height / step)):
        for col in range(math.ceil(width / step)):
            center = {"x": (col + 0.5) * step, "y": (row + 0.5) * step}
            lane_ids = [layout["lane"].get("id") for layout in layouts if distance_to_polyline(center, layout["path"]) <= max(step * 0.72, layout["width"] / 2)]
            building_ids = [building.get("id") for building in model.get("buildings", []) if abs(center["x"] - building.get("x", 0)) <= building.get("width", 0) / 2 and abs(center["y"] - building.get("y", 0)) <= building.get("height", 0) / 2]
            camera_ids = [camera.get("id") for camera in model.get("cameras", []) if point_in_camera_fov(center, camera)]
            manual_camera_ids = [camera.get("id") for camera in model.get("cameras", []) if [col, row] in camera.get("coverage", {}).get("gridCells", [])]
            if lane_ids or building_ids or camera_ids or manual_camera_ids:
                occupied.append({"id": f"grid_{col}_{row}", "cell": [col, row], "center": center, "laneIds": lane_ids, "buildingIds": building_ids, "cameraFovIds": camera_ids, "cameraManualIds": manual_camera_ids})
            lane_cells += bool(lane_ids)
            building_cells += bool(building_ids)
            camera_cells += bool(camera_ids)
    return {"summary": {"gridSize": step, "totalCellCount": math.ceil(width / step) * math.ceil(height / step), "occupiedCellCount": len(occupied), "laneCoveredCellCount": lane_cells, "buildingCoveredCellCount": building_cells, "cameraFovCoveredCellCount": camera_cells}, "cells": occupied}


def map_image_points(model: dict[str, Any], grid_coverage: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = {node["id"]: node for node in model.get("nodes", []) if node.get("id")}
    layouts = rendered_lane_layouts(model)
    calibrations = {item.get("id"): item for item in model.get("cameraCalibrations", [])}
    cell_by_id = {cell["id"]: cell for cell in grid_coverage["cells"]}
    relations = []
    for camera in model.get("cameras", []):
        calibration = calibrations.get(camera.get("calibrationId"), {})
        image_points = {point.get("id"): point for point in calibration.get("points", [])}
        for binding in camera.get("pointBindings", []):
            world_point = binding.get("worldPoint")
            if not world_point:
                continue
            point = {"x": float(world_point["x"]), "y": float(world_point["y"])}
            col, row = int(point["x"] // model["world"]["gridSize"]), int(point["y"] // model["world"]["gridSize"])
            grid_id = f"grid_{col}_{row}"
            lane_candidates = sorted(({
                "laneId": layout["lane"].get("id"),
                "roadBundleId": layout["roadBundleId"],
                "distance": round(distance_to_polyline(point, layout["path"]), 3),
                "laneHalfWidth": layout["width"] / 2,
                "insideLane": distance_to_polyline(point, layout["path"]) <= layout["width"] / 2,
            } for layout in layouts), key=lambda item: item["distance"])
            nearby_lanes = [item["laneId"] for item in lane_candidates if item["insideLane"]]
            rendered_lane_id = nearby_lanes[0] if nearby_lanes else None
            explicit_lane_id = binding.get("laneId")
            if explicit_lane_id and any(item["laneId"] == explicit_lane_id for item in lane_candidates):
                rendered_lane_id = explicit_lane_id
                nearby_lanes = [explicit_lane_id]
            buildings = [building.get("id") for building in model.get("buildings", []) if abs(point["x"] - building.get("x", 0)) <= building.get("width", 0) / 2 and abs(point["y"] - building.get("y", 0)) <= building.get("height", 0) / 2]
            if binding.get("buildingId") and any(item.get("id") == binding["buildingId"] for item in model.get("buildings", [])):
                buildings = [binding["buildingId"]]
            nearest_nodes = sorted(((distance(point, node), node_id) for node_id, node in nodes.items()), key=lambda item: item[0])[:2]
            nearest_node_ids = [node_id for _, node_id in nearest_nodes]
            if binding.get("nodeId") in nodes:
                nearest_node_ids = [binding["nodeId"], *[item for item in nearest_node_ids if item != binding["nodeId"]]]
            relations.append({"cameraId": camera.get("id"), "calibrationId": camera.get("calibrationId"), "imagePointId": binding.get("imagePointId"), "image": image_points.get(binding.get("imagePointId")), "worldPoint": world_point, "gridCellId": grid_id, "gridCell": cell_by_id.get(grid_id), "renderedLaneId": rendered_lane_id, "nearbyLaneIds": nearby_lanes, "laneCandidates": lane_candidates[:4], "buildingIds": buildings, "nearestNodeIds": nearest_node_ids, "insideCameraFov": point_in_camera_fov(point, camera)})
    return relations


def unit_vector(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    length = math.hypot(dx, dy) or 1.0
    return {"x": dx / length, "y": dy / length}


def dot(a: dict[str, float], b: dict[str, float]) -> float:
    return a["x"] * b["x"] + a["y"] * b["y"]


def traffic_path(layout: dict[str, Any]) -> list[dict[str, float]]:
    source, _ = directed_endpoints(layout["lane"])
    return layout["path"] if source == layout["canonicalStart"] else list(reversed(layout["path"]))


def lane_vector_records(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = {}
    for layout in rendered_lane_layouts(model):
        lane = layout["lane"]
        path = traffic_path(layout)
        if len(path) < 2:
            continue
        source, target = directed_endpoints(lane)
        records[lane["id"]] = {
            "id": lane["id"],
            "roadBundleId": layout["roadBundleId"],
            "sourceNodeId": source,
            "targetNodeId": target,
            "width": layout["width"],
            "renderOffsetIndex": layout["offsetIndex"],
            "path": path,
            "startDirection": unit_vector(path[0], path[1]),
            "endDirection": unit_vector(path[-2], path[-1]),
            "markings": {"left": lane.get("leftLineStyle"), "right": lane.get("rightLineStyle")},
            "arrows": {"source": lane.get("endpoint1Arrow") if source == lane.get("endpoint1") else lane.get("endpoint2Arrow"), "target": lane.get("endpoint2Arrow") if target == lane.get("endpoint2") else lane.get("endpoint1Arrow")},
        }
    return records


def rank_at_node(items: list[dict[str, Any]], node_id: str, direction: dict[str, float], incoming: bool) -> list[dict[str, Any]]:
    normal = {"x": -direction["y"], "y": direction["x"]}
    def position(item: dict[str, Any]) -> float:
        point = item["path"][-1] if incoming else item["path"][0]
        return dot(point, normal)
    return sorted(items, key=position)


def allocate_continuations(incoming: list[dict[str, Any]], outgoing: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Pair lane ranks monotonically; differing counts express merge or split without crossings."""
    if not incoming or not outgoing:
        return []
    direction = unit_vector({"x": 0, "y": 0}, {"x": sum(item["endDirection"]["x"] for item in incoming) + sum(item["startDirection"]["x"] for item in outgoing), "y": sum(item["endDirection"]["y"] for item in incoming) + sum(item["startDirection"]["y"] for item in outgoing)})
    incoming = rank_at_node(incoming, incoming[0]["targetNodeId"], direction, incoming=True)
    outgoing = rank_at_node(outgoing, outgoing[0]["sourceNodeId"], direction, incoming=False)
    total = max(len(incoming), len(outgoing))
    pairs = []
    for index in range(total):
        source = incoming[round(index * (len(incoming) - 1) / max(total - 1, 1))]
        target = outgoing[round(index * (len(outgoing) - 1) / max(total - 1, 1))]
        if not pairs or (pairs[-1][0]["id"], pairs[-1][1]["id"]) != (source["id"], target["id"]):
            pairs.append((source, target))
    return pairs


def movement_between(source: dict[str, Any], target: dict[str, Any]) -> str:
    """Classify a movement in screen coordinates, where a positive cross product is a right turn."""
    cosine = dot(source["endDirection"], target["startDirection"])
    cross = source["endDirection"]["x"] * target["startDirection"]["y"] - source["endDirection"]["y"] * target["startDirection"]["x"]
    if cosine <= -0.7:
        return "back"
    if cosine >= 0.7:
        return "forward"
    return "right" if cross > 0 else "left"


def arrow_movements(arrow: Any) -> set[str]:
    value = str(arrow or "none").lower()
    if value in {"forward", "straight"}:
        return {"forward"}
    if value in {"forward_left", "straight_left"}:
        return {"forward", "left"}
    if value in {"forward_right", "straight_right"}:
        return {"forward", "right"}
    if value in {"left", "right", "back"}:
        return {value}
    return set()


def allocate_turn_lanes(incoming: list[dict[str, Any]], outgoing: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Choose monotonic, nearest node-edge connections for an allowed turning movement."""
    if not incoming or not outgoing:
        return []
    remaining = list(outgoing)
    pairs = []
    for source in sorted(incoming, key=lambda item: item["id"]):
        choices = remaining or outgoing
        target = min(choices, key=lambda item: distance(source["path"][-1], item["path"][0]))
        pairs.append((source, target))
        if target in remaining:
            remaining.remove(target)
    return pairs


def build_lane_vector_model(model: dict[str, Any], direction_cosine_threshold: float = 0.82) -> dict[str, Any]:
    """Derive directed lane corridors and camera point/line vectors without changing the source model."""
    lanes = lane_vector_records(model)
    node_types = {item["id"]: item.get("type") for item in model.get("nodes", [])}
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for lane in lanes.values():
        incoming[lane["targetNodeId"]].append(lane)
        outgoing[lane["sourceNodeId"]].append(lane)

    assignments = []
    junctions = []
    for node_id in sorted(set(incoming) | set(outgoing)):
        if node_types.get(node_id) == "junction":
            continue
        eligible: dict[str, set[str]] = defaultdict(set)
        for source in incoming[node_id]:
            for target in outgoing[node_id]:
                cosine = dot(source["endDirection"], target["startDirection"])
                if cosine >= direction_cosine_threshold:
                    eligible[source["id"]].add(target["id"])
                    eligible[target["id"]].add(source["id"])
        visited = set()
        node_assignments = []
        for lane_id in sorted(eligible):
            if lane_id in visited:
                continue
            stack, component = [lane_id], set()
            while stack:
                item = stack.pop()
                if item in visited:
                    continue
                visited.add(item)
                component.add(item)
                stack.extend(eligible[item] - visited)
            component_in = [lane for lane in incoming[node_id] if lane["id"] in component]
            component_out = [lane for lane in outgoing[node_id] if lane["id"] in component]
            for source, target in allocate_continuations(component_in, component_out):
                cosine = dot(source["endDirection"], target["startDirection"])
                record = {"nodeId": node_id, "fromLaneId": source["id"], "toLaneId": target["id"], "kind": "merge" if len(component_in) > len(component_out) else ("split" if len(component_out) > len(component_in) else "through"), "directionCosine": round(cosine, 4)}
                assignments.append(record)
                node_assignments.append(record)
        if node_assignments:
            junctions.append({"nodeId": node_id, "incomingLaneIds": [item["id"] for item in incoming[node_id]], "outgoingLaneIds": [item["id"] for item in outgoing[node_id]], "assignments": node_assignments})

    # A corridor is strictly a same-heading relation. Marked turns are added as
    # transitions afterwards so vehicle flow can traverse an intersection without
    # pretending that a left/right movement belongs to the same road corridor.
    lane_transitions = [{**item, "movement": "forward", "transitionKind": "continuous"} for item in assignments]
    existing_transitions = {(item["fromLaneId"], item["toLaneId"], item["movement"]) for item in lane_transitions}
    marked_turns_by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node_id, source_lanes in incoming.items():
        if node_types.get(node_id) == "junction":
            continue
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for source in source_lanes:
            allowed = arrow_movements(source["arrows"]["target"])
            for target in outgoing[node_id]:
                movement = movement_between(source, target)
                if movement in allowed:
                    groups[(source["roadBundleId"], movement, target["targetNodeId"])].append(source)
        for (_, movement, target_node_id), sources in groups.items():
            targets = [item for item in outgoing[node_id] if item["targetNodeId"] == target_node_id and movement_between(sources[0], item) == movement]
            for source, target in allocate_turn_lanes(list({item["id"]: item for item in sources}.values()), targets):
                key = (source["id"], target["id"], movement)
                if key in existing_transitions:
                    continue
                record = {"nodeId": node_id, "fromLaneId": source["id"], "toLaneId": target["id"], "movement": movement, "transitionKind": "marked_turn", "sourceArrow": source["arrows"]["target"], "directionCosine": round(dot(source["endDirection"], target["startDirection"]), 4)}
                lane_transitions.append(record)
                marked_turns_by_node[node_id].append(record)
                existing_transitions.add(key)
    for junction in junctions:
        junction["markedTurnTransitions"] = marked_turns_by_node[junction["nodeId"]]
    lane_flow_adjacency = {lane_id: [] for lane_id in lanes}
    for transition in lane_transitions:
        lane_flow_adjacency[transition["fromLaneId"]].append({"toLaneId": transition["toLaneId"], "nodeId": transition["nodeId"], "movement": transition["movement"], "transitionKind": transition["transitionKind"]})
    for transitions in lane_flow_adjacency.values():
        transitions.sort(key=lambda item: (item["movement"], item["toLaneId"]))

    parent = {lane_id: lane_id for lane_id in lanes}
    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item
    def join(a: str, b: str) -> None:
        a, b = find(a), find(b)
        if a != b:
            parent[b] = a
    for item in assignments:
        join(item["fromLaneId"], item["toLaneId"])
    groups: dict[str, list[str]] = defaultdict(list)
    for lane_id in sorted(lanes):
        groups[find(lane_id)].append(lane_id)
    corridors = []
    lane_to_corridor = {}
    for index, lane_ids in enumerate(sorted((members for members in groups.values() if len(members) > 1), key=lambda members: members[0]), start=1):
        corridor_id = f"corridor_{index}"
        corridors.append({"id": corridor_id, "laneIds": lane_ids})
        lane_to_corridor.update({lane_id: corridor_id for lane_id in lane_ids})
    for lane_id, lane in lanes.items():
        lane["corridorId"] = lane_to_corridor.get(lane_id)

    coverage = compute_grid_coverage(model)
    relations = map_image_points(model, coverage)
    relation_by_camera_point = {(item["cameraId"], item["imagePointId"]): item for item in relations}
    cameras = []
    calibrations = {item.get("id"): item for item in model.get("cameraCalibrations", [])}
    for camera in model.get("cameras", []):
        camera_relations = [item for item in relations if item["cameraId"] == camera.get("id")]
        for relation in camera_relations:
            candidates = relation["nearbyLaneIds"]
            relation["laneStatus"] = "single_lane" if len(candidates) == 1 else ("ambiguous_lane_band" if candidates else ("building_anchor" if relation["buildingIds"] else "free_space"))
            relation["corridorId"] = lane_to_corridor.get(relation["renderedLaneId"])
        point_vectors = [{
            "imagePointId": item["imagePointId"],
            "imagePosition": {"x": item["image"].get("x"), "y": item["image"].get("y")} if item.get("image") else None,
            "worldPoint": item["worldPoint"],
            "gridCellId": item["gridCellId"],
            "laneStatus": item["laneStatus"],
            "laneId": item["renderedLaneId"],
            "corridorId": item["corridorId"],
            "candidateLaneIds": item["nearbyLaneIds"],
            "laneCandidates": item["laneCandidates"],
            "buildingIds": item["buildingIds"],
            "insideCameraFov": item["insideCameraFov"],
        } for item in camera_relations]
        image_lines = []
        for line in calibrations.get(camera.get("calibrationId"), {}).get("lines", []):
            source = relation_by_camera_point.get((camera.get("id"), line.get("fromPointId")))
            target = relation_by_camera_point.get((camera.get("id"), line.get("toPointId")))
            if not source or not target:
                continue
            source_options = source["nearbyLaneIds"] or ([source["renderedLaneId"]] if source.get("renderedLaneId") else [])
            target_options = target["nearbyLaneIds"] or ([target["renderedLaneId"]] if target.get("renderedLaneId") else [])
            common_lanes = sorted(set(source_options) & set(target_options))
            source_lane, target_lane, continuation, kind = source.get("renderedLaneId"), target.get("renderedLaneId"), None, "unresolved"
            if common_lanes:
                source_lane = target_lane = common_lanes[0]
                kind = "lane_segment"
            else:
                continuation = next((item for item in lane_transitions if item["fromLaneId"] in source_options and item["toLaneId"] in target_options), None)
                if continuation:
                    source_lane, target_lane, kind = continuation["fromLaneId"], continuation["toLaneId"], "directed_continuation"
                else:
                    source_corridors = {lane_to_corridor.get(lane_id) for lane_id in source_options} - {None}
                    target_corridors = {lane_to_corridor.get(lane_id) for lane_id in target_options} - {None}
                    shared_corridors = sorted(source_corridors & target_corridors)
                    if shared_corridors:
                        corridor_id = shared_corridors[0]
                        source_lane = next(lane_id for lane_id in source_options if lane_to_corridor.get(lane_id) == corridor_id)
                        target_lane = next(lane_id for lane_id in target_options if lane_to_corridor.get(lane_id) == corridor_id)
                        kind = "corridor_segment"
            image_lines.append({"id": line.get("id"), "fromImagePointId": line.get("fromPointId"), "toImagePointId": line.get("toPointId"), "fromLaneId": source_lane, "toLaneId": target_lane, "kind": kind, "junctionNodeId": continuation.get("nodeId") if continuation else None})
        cameras.append({"id": camera.get("id"), "calibrationId": camera.get("calibrationId"), "visibleLaneIds": sorted({item["renderedLaneId"] for item in camera_relations if item["renderedLaneId"]}), "visibleCorridorIds": sorted({item["corridorId"] for item in camera_relations if item.get("corridorId")}), "imagePointVectors": point_vectors, "imageLineVectors": image_lines})
    return {"schema": "road_logic_modeler.lane-vector.v1", "parameters": {"directionCosineThreshold": direction_cosine_threshold}, "lanes": [lanes[lane_id] for lane_id in sorted(lanes)], "corridors": corridors, "junctions": junctions, "laneTransitions": lane_transitions, "laneFlowGraph": {"nodes": sorted(lanes), "adjacency": lane_flow_adjacency}, "cameras": cameras, "summary": {"laneCount": len(lanes), "corridorCount": len(corridors), "junctionAssignmentCount": len(assignments), "laneTransitionCount": len(lane_transitions), "markedTurnTransitionCount": sum(item["transitionKind"] == "marked_turn" for item in lane_transitions), "cameraCount": len(cameras), "imagePointCount": len(relations), "singleLaneImagePointCount": sum(item.get("laneStatus") == "single_lane" for camera in cameras for item in camera["imagePointVectors"]), "ambiguousLaneImagePointCount": sum(item.get("laneStatus") == "ambiguous_lane_band" for camera in cameras for item in camera["imagePointVectors"])}}


def analyze_model(model: dict[str, Any]) -> dict[str, Any]:
    topology = reconstruct_topology(model)
    coverage = compute_grid_coverage(model)
    return {"schema": "road_logic_modeler.analysis.v1", "topology": topology, "gridCoverage": coverage, "imagePointRelations": map_image_points(model, coverage)}


def build_road_graph(model: dict[str, Any]) -> dict[str, Any]:
    topology = reconstruct_topology(model)
    nodes = {node["id"]: node for node in model.get("nodes", []) if node.get("id")}
    edge_items = []
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    incoming: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    undirected: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    bundle_by_pair = {tuple(bundle["endpointIds"]): bundle["id"] for bundle in topology["roadBundles"]}
    layout_by_lane = {layout["lane"].get("id"): layout for layout in rendered_lane_layouts(model)}
    for lane in model.get("lanes", []):
        source, target = directed_endpoints(lane)
        if source not in nodes or target not in nodes:
            continue
        bundle_id = bundle_by_pair.get(tuple(sorted((source, target))))
        layout = layout_by_lane.get(lane.get("id"), {})
        edge_items.append({"id": lane.get("id"), "source": source, "target": target, "roadBundleId": bundle_id, "width": lane.get("width", 28), "height": lane.get("height"), "interpolation": lane.get("interpolation", "line"), "leftLineStyle": lane.get("leftLineStyle"), "rightLineStyle": lane.get("rightLineStyle"), "renderOffsetIndex": layout.get("offsetIndex"), "renderPath": layout.get("path", []), "arrows": {"endpoint1": lane.get("endpoint1Arrow"), "endpoint2": lane.get("endpoint2Arrow")}})
        outgoing[source].append(lane.get("id"))
        incoming[target].append(lane.get("id"))
        undirected[source].add(target)
        undirected[target].add(source)
    components, visited = [], set()
    for root in nodes:
        if root in visited:
            continue
        queue, component = [root], []
        visited.add(root)
        while queue:
            node_id = queue.pop()
            component.append(node_id)
            for neighbor in undirected[node_id]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        components.append(sorted(component))
    graph_nodes = [{"id": node_id, "name": node.get("name", node_id), "type": node.get("type"), "position": {"x": node.get("x"), "y": node.get("y"), "z": node.get("z", 0)}, "inDegree": len(incoming[node_id]), "outDegree": len(outgoing[node_id]), "sides": topology["nodeSides"].get(node_id, {})} for node_id, node in nodes.items()]
    return {"schema": "road_logic_modeler.graph.v1", "nodes": graph_nodes, "edges": edge_items, "roadBundles": topology["roadBundles"], "adjacency": {node_id: {"outgoingLaneIds": outgoing[node_id], "incomingLaneIds": incoming[node_id], "neighborNodeIds": sorted(undirected[node_id])} for node_id in nodes}, "weakComponents": components, "summary": {"nodeCount": len(graph_nodes), "directedEdgeCount": len(edge_items), "roadBundleCount": len(topology["roadBundles"]), "weakComponentCount": len(components)}}


def build_baseline_exports(model: dict[str, Any], source_name: str, source_sha256: str) -> dict[str, Any]:
    """Create stable, inference-free inputs for downstream camera/YOLO analysis."""
    graph = build_road_graph(model)
    coverage = compute_grid_coverage(model)
    relations = map_image_points(model, coverage)
    raw_lanes = {lane.get("id"): lane for lane in model.get("lanes", [])}
    baseline_lanes = []
    for edge in graph["edges"]:
        raw_lane = raw_lanes[edge["id"]]
        source_is_endpoint1 = edge["source"] == raw_lane.get("endpoint1")
        baseline_lanes.append({
            "id": edge["id"],
            "name": raw_lane.get("name", edge["id"]),
            "endpoints": {"endpoint1NodeId": raw_lane.get("endpoint1"), "endpoint2NodeId": raw_lane.get("endpoint2")},
            "traffic": {
                "direction": raw_lane.get("direction", "1-2"),
                "sourceNodeId": edge["source"], "targetNodeId": edge["target"],
                "sourceArrow": edge["arrows"]["endpoint1"] if source_is_endpoint1 else edge["arrows"]["endpoint2"],
                "targetArrow": edge["arrows"]["endpoint2"] if source_is_endpoint1 else edge["arrows"]["endpoint1"],
            },
            "markings": {"leftBoundary": edge["leftLineStyle"], "rightBoundary": edge["rightLineStyle"]},
            "geometry": {
                "width": edge["width"], "height": edge["height"], "interpolation": edge["interpolation"],
                "renderOffsetIndex": edge["renderOffsetIndex"], "renderPath": edge["renderPath"],
            },
            "roadBundleId": edge["roadBundleId"],
        })
    baseline_bundles = [{
        "id": bundle["id"], "endpointIds": bundle["endpointIds"], "laneIds": bundle["laneIds"],
        "directionalLaneIds": bundle["directionalLaneIds"],
    } for bundle in graph["roadBundles"]]
    road_lane = {
        "schema": "road_logic_modeler.road-lane.v1",
        "source": {"name": source_name, "sha256": source_sha256},
        "world": model.get("world", {}),
        "nodes": graph["nodes"],
        "buildings": [{"id": item.get("id"), "name": item.get("name", item.get("id")), "center": {"x": item.get("x"), "y": item.get("y")}, "width": item.get("width"), "height": item.get("height")} for item in model.get("buildings", [])],
        "lanes": baseline_lanes,
        "roadBundles": baseline_bundles,
        "adjacency": graph["adjacency"],
        "summary": {"nodeCount": graph["summary"]["nodeCount"], "directedLaneCount": graph["summary"]["directedEdgeCount"], "roadBundleCount": graph["summary"]["roadBundleCount"]},
    }
    points_by_camera: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for relation in relations:
        points_by_camera[relation["cameraId"]].append({
            "imagePointId": relation["imagePointId"],
            "imagePosition": {"x": relation["image"].get("x"), "y": relation["image"].get("y")} if relation.get("image") else None,
            "worldPoint": relation["worldPoint"],
            "gridCellId": relation["gridCellId"],
            "laneId": relation["renderedLaneId"],
            "candidateLaneIds": relation["nearbyLaneIds"],
            "laneCandidates": relation["laneCandidates"],
            "buildingIds": relation["buildingIds"],
            "nearestNodeIds": relation["nearestNodeIds"],
            "insideCameraFov": relation["insideCameraFov"],
        })
    camera_mapping = {
        "schema": "road_logic_modeler.camera-mapping.v1",
        "source": {"name": source_name, "sha256": source_sha256},
        "world": {"width": model.get("world", {}).get("width"), "height": model.get("world", {}).get("height"), "gridSize": model.get("world", {}).get("gridSize")},
        "cameras": [{
            "id": camera.get("id"), "calibrationId": camera.get("calibrationId"),
            "position": {"x": camera.get("x"), "y": camera.get("y")},
            "direction": camera.get("direction"), "fov": camera.get("fov"), "range": camera.get("range"),
            "points": points_by_camera[camera.get("id")],
        } for camera in model.get("cameras", [])],
        "summary": {"cameraCount": len(model.get("cameras", [])), "mappedImagePointCount": len(relations)},
    }
    manifest = {
        "schema": "road_logic_modeler.baseline-manifest.v1",
        "sourceName": source_name,
        "sourceSha256": source_sha256,
        "exports": ["road-lane.v1", "camera-mapping.v1"],
        "summary": {**road_lane["summary"], **camera_mapping["summary"]},
    }
    return {"roadLane": road_lane, "cameraMapping": camera_mapping, "manifest": manifest}


def baseline_format_markdown() -> str:
    return """# YOLO Analysis Baseline

Use these two files as the fixed input pair:

- `*.road-lane.v1.json`: road and lane definition only.
- `*.camera-mapping.v1.json`: camera image-point to world-point mapping only.

Do not use `*.lane-vector.json` for the first YOLO pass. It includes experimental inferred transitions.

## Road Lane

- `nodes`: endpoint nodes with position and degree.
- `lanes[].endpoints`: source export endpoint IDs before traffic direction is applied.
- `lanes[].traffic.direction`: original editor direction, `1-2` or `2-1`.
- `lanes[].traffic.sourceNodeId` / `targetNodeId`: resolved vehicle travel direction.
- `lanes[].traffic.sourceArrow` / `targetArrow`: arrow marking at the resolved travel ends.
- `lanes[].markings.leftBoundary` / `rightBoundary`: lane boundary line styles.
- `lanes[].geometry.renderPath`: rendered center path for the individual lane, including its bundle offset.
- `roadBundles`: parallel lanes that share two endpoint nodes; no turn inference is included.

## Camera Mapping

- `cameras[].points[].imagePosition`: annotation location in the calibration image.
- `worldPoint`: matching point on the road model.
- `laneId`: nearest rendered lane when the point is inside a lane band.
- `candidateLaneIds` and `laneCandidates`: retain overlaps near junctions for later YOLO disambiguation.
- `buildingIds`, `nearestNodeIds`, and `gridCellId`: supplementary world references.

## Version Control

The manifest stores the SHA-256 of the source model. Regenerate both files together whenever the original road model changes.
"""


def prune_unused_calibrations(model: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    compact = copy.deepcopy(model)
    used = {camera.get("calibrationId") for camera in compact.get("cameras", []) if camera.get("calibrationId")}
    removed = [item.get("id") for item in compact.get("cameraCalibrations", []) if item.get("id") not in used]
    compact["cameraCalibrations"] = [item for item in compact.get("cameraCalibrations", []) if item.get("id") in used]
    return compact, removed


def render_world_map(model: dict[str, Any], analysis: dict[str, Any], output_path: Path, show_relations: bool, camera_id: str | None = None) -> None:
    world = model["world"]
    canvas = Image.new("RGBA", (1800, 1180), "#101820")
    draw = ImageDraw.Draw(canvas, "RGBA")
    pad = 80
    scale = min((canvas.width - pad * 2) / world["width"], (canvas.height - pad * 2) / world["height"])
    def screen(point: dict[str, Any]) -> tuple[float, float]:
        return pad + point["x"] * scale, pad + point["y"] * scale
    draw.rectangle((pad, pad, pad + world["width"] * scale, pad + world["height"] * scale), outline="#7f8b95", width=2)
    cameras = [camera for camera in model.get("cameras", []) if camera_id is None or camera.get("id") == camera_id]
    fov_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    fov_draw = ImageDraw.Draw(fov_layer, "RGBA")
    for camera in cameras:
        center = screen(camera)
        radius = camera.get("range", 0) * scale
        start = camera.get("direction", 0) - camera.get("fov", 60) / 2
        end = camera.get("direction", 0) + camera.get("fov", 60) / 2
        fov_draw.pieslice((center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius), start=start, end=end, fill=(245, 158, 11, 34))
    canvas = Image.alpha_composite(canvas, fov_layer)
    draw = ImageDraw.Draw(canvas, "RGBA")
    for building in model.get("buildings", []):
        x, y = screen({"x": building["x"] - building["width"] / 2, "y": building["y"] - building["height"] / 2})
        x2, y2 = screen({"x": building["x"] + building["width"] / 2, "y": building["y"] + building["height"] / 2})
        draw.rectangle((x, y, x2, y2), fill=(100, 116, 139, 80), outline="#94a3b8", width=2)
    for layout in rendered_lane_layouts(model):
        if len(layout["path"]) > 1:
            draw.line([screen(point) for point in layout["path"]], fill="#43616b", width=max(3, int(layout["width"] * scale * 0.28)), joint="curve")
    for node in model.get("nodes", []):
        x, y = screen(node)
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill="#e2e8f0", outline="#111820")
        draw.text((x + 7, y + 5), node.get("id"), fill="#e2e8f0")
    for camera in cameras:
        x, y = screen(camera)
        draw.regular_polygon((x, y, 10), 3, rotation=camera.get("direction", 0), fill="#f59e0b")
        draw.text((x + 9, y - 10), camera.get("id"), fill="#fbbf24")
    if show_relations:
        for relation in analysis["imagePointRelations"]:
            if camera_id is not None and relation["cameraId"] != camera_id:
                continue
            x, y = screen(relation["worldPoint"])
            color = "#22d3ee" if relation["nearbyLaneIds"] else ("#fb7185" if relation["buildingIds"] else "#c084fc")
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=color, outline="#ffffff", width=2)
            draw.text((x + 8, y - 18), f"{relation['cameraId']}:{relation['imagePointId']}", fill=color)
    legend = "cyan: road-mapped point | pink: building point | purple: free-space point | orange: camera FOV"
    draw.text((pad, canvas.height - 38), legend, fill="#e2e8f0")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, quality=92)


def render_camera_vector_map(model: dict[str, Any], lane_vector: dict[str, Any], camera_id: str, output_path: Path) -> None:
    """Render a camera-local verification image for lane point and line assignments."""
    world = model["world"]
    camera = next(item for item in model.get("cameras", []) if item.get("id") == camera_id)
    vector_camera = next(item for item in lane_vector["cameras"] if item["id"] == camera_id)
    padding_world = 70
    radius = float(camera.get("range", 0)) + padding_world
    left, top = max(0, camera["x"] - radius), max(0, camera["y"] - radius)
    right, bottom = min(world["width"], camera["x"] + radius), min(world["height"], camera["y"] + radius)
    canvas = Image.new("RGBA", (1600, 1000), "#101820")
    draw = ImageDraw.Draw(canvas, "RGBA")
    pad = 64
    scale = min((canvas.width - pad * 2) / max(right - left, 1), (canvas.height - pad * 2) / max(bottom - top, 1))
    def screen(point: dict[str, Any]) -> tuple[float, float]:
        return pad + (point["x"] - left) * scale, pad + (point["y"] - top) * scale
    draw.rectangle((pad, pad, pad + (right - left) * scale, pad + (bottom - top) * scale), outline="#7f8b95", width=2)
    for building in model.get("buildings", []):
        x, y = screen({"x": building["x"] - building["width"] / 2, "y": building["y"] - building["height"] / 2})
        x2, y2 = screen({"x": building["x"] + building["width"] / 2, "y": building["y"] + building["height"] / 2})
        draw.rectangle((x, y, x2, y2), fill=(100, 116, 139, 80), outline="#94a3b8", width=2)
    for layout in rendered_lane_layouts(model):
        path = layout["path"]
        if len(path) < 2:
            continue
        draw.line([screen(point) for point in path], fill="#496974", width=max(4, int(layout["width"] * scale * 0.28)), joint="curve")
        directed = traffic_path(layout)
        middle = len(directed) // 2
        if middle + 1 < len(directed):
            a, b = screen(directed[middle]), screen(directed[middle + 1])
            direction = unit_vector({"x": a[0], "y": a[1]}, {"x": b[0], "y": b[1]})
            normal = {"x": -direction["y"], "y": direction["x"]}
            tip = (a[0] + direction["x"] * 13, a[1] + direction["y"] * 13)
            base = (a[0] - direction["x"] * 7, a[1] - direction["y"] * 7)
            draw.polygon([tip, (base[0] + normal["x"] * 5, base[1] + normal["y"] * 5), (base[0] - normal["x"] * 5, base[1] - normal["y"] * 5)], fill="#b9dbe5")
    center = screen(camera)
    radius_px = camera.get("range", 0) * scale
    draw.pieslice((center[0] - radius_px, center[1] - radius_px, center[0] + radius_px, center[1] + radius_px), start=camera.get("direction", 0) - camera.get("fov", 60) / 2, end=camera.get("direction", 0) + camera.get("fov", 60) / 2, fill=(245, 158, 11, 26))
    point_by_id = {item["imagePointId"]: item for item in vector_camera["imagePointVectors"]}
    line_colors = {"lane_segment": "#34d399", "directed_continuation": "#fbbf24", "corridor_segment": "#fb923c", "unresolved": "#fb7185"}
    for line in vector_camera["imageLineVectors"]:
        source, target = point_by_id.get(line["fromImagePointId"]), point_by_id.get(line["toImagePointId"])
        if source and target:
            draw.line([screen(source["worldPoint"]), screen(target["worldPoint"])], fill=line_colors[line["kind"]], width=4)
    point_colors = {"single_lane": "#22d3ee", "ambiguous_lane_band": "#c084fc", "building_anchor": "#fb7185", "free_space": "#f8fafc"}
    for point in vector_camera["imagePointVectors"]:
        x, y = screen(point["worldPoint"])
        color = point_colors[point["laneStatus"]]
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=color, outline="#ffffff", width=2)
        lane_label = point["laneId"] or point["laneStatus"]
        draw.text((x + 10, y - 20), f"{point['imagePointId']} -> {lane_label}", fill=color)
    draw.regular_polygon((center[0], center[1], 12), 3, rotation=camera.get("direction", 0), fill="#f59e0b")
    draw.text((pad, 20), f"{camera_id} | cyan: single lane | purple: ambiguous lane band | green: same lane | yellow: directed continuation | orange: corridor | pink: unresolved", fill="#e2e8f0")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, quality=93)


def render_junction_flow_map(model: dict[str, Any], lane_vector: dict[str, Any], node_id: str, output_path: Path) -> None:
    """Render lane-to-lane transitions around one junction for topology review."""
    nodes = {item["id"]: item for item in model.get("nodes", [])}
    node = nodes[node_id]
    transitions = [item for item in lane_vector["laneTransitions"] if item["nodeId"] == node_id]
    extent = 220.0
    canvas = Image.new("RGBA", (1500, 1000), "#101820")
    draw = ImageDraw.Draw(canvas, "RGBA")
    pad, map_size, scale = 70, 860, 860 / (extent * 2)
    def screen(point: dict[str, Any]) -> tuple[float, float]:
        return pad + (point["x"] - (node["x"] - extent)) * scale, pad + (point["y"] - (node["y"] - extent)) * scale
    for lane in lane_vector["lanes"]:
        if lane["sourceNodeId"] != node_id and lane["targetNodeId"] != node_id:
            continue
        draw.line([screen(point) for point in lane["path"]], fill="#526f78", width=max(5, int(lane["width"] * scale * 0.24)))
    colors = {"forward": "#22d3ee", "left": "#c084fc", "right": "#fbbf24", "back": "#fb7185"}
    lane_by_id = {lane["id"]: lane for lane in lane_vector["lanes"]}
    for index, transition in enumerate(transitions):
        source, target = lane_by_id[transition["fromLaneId"]], lane_by_id[transition["toLaneId"]]
        a, b, control = source["path"][-1], target["path"][0], {"x": node["x"], "y": node["y"]}
        path = sample_quadratic(a, control, b, count=16)
        color = colors[transition["movement"]]
        draw.line([screen(point) for point in path], fill=color, width=4, joint="curve")
        label_point = path[8]
        x, y = screen(label_point)
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=color, outline="#ffffff")
        draw.text((x - 3, y - 5), str(index + 1), fill="#101820")
    x, y = screen(node)
    draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill="#f8fafc", outline="#111820")
    draw.text((pad, 24), f"{node_id} lane flow | cyan: forward | purple: left | yellow: right | pink: back", fill="#e2e8f0")
    draw.rectangle((970, 55, 1450, 945), outline="#64748b", width=2)
    draw.text((995, 80), "Lane transitions", fill="#e2e8f0")
    for index, transition in enumerate(transitions):
        color = colors[transition["movement"]]
        y = 116 + index * 36
        if y > 910:
            break
        draw.ellipse((995, y + 3, 1009, y + 17), fill=color)
        draw.text((1020, y), f"{index + 1}. {transition['fromLaneId']} -> {transition['toLaneId']} [{transition['movement']}]", fill=color)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, quality=94)


def externalize_calibration_images(model: dict[str, Any], captures_dir: Path, reference_prefix: str = "captures") -> tuple[dict[str, Any], list[dict[str, str]]]:
    compact = copy.deepcopy(model)
    files = {path.name.lower(): path for path in captures_dir.glob("*") if path.is_file()}
    changes = []
    for calibration in compact.get("cameraCalibrations", []):
        image = calibration.get("image") or {}
        name = Path(image.get("name") or "").name
        capture = files.get(name.lower())
        if capture and image.get("dataUrl"):
            image.pop("dataUrl", None)
            image.pop("url", None)
            image["src"] = f"{reference_prefix.rstrip('/')}/{capture.name}"
            calibration["image"] = image
            changes.append({"calibrationId": calibration.get("id", ""), "status": "externalized", "src": image["src"]})
        elif image.get("dataUrl"):
            changes.append({"calibrationId": calibration.get("id", ""), "status": "capture_not_found", "src": name})
    return compact, changes


def markdown_report(model: dict[str, Any], analysis: dict[str, Any]) -> str:
    topology = analysis["topology"]
    coverage = analysis["gridCoverage"]["summary"]
    relations = analysis["imagePointRelations"]
    lane_points = sum(bool(item["nearbyLaneIds"]) for item in relations)
    building_points = sum(bool(item["buildingIds"]) for item in relations)
    out_of_fov = sum(not item["insideCameraFov"] for item in relations)
    externalized = sum(item["status"] == "externalized" for item in analysis["imageExternalization"])
    missing = [item for item in analysis["imageExternalization"] if item["status"] != "externalized"]
    return "\n".join([
        "# Road Logic Model Analysis",
        "",
        "## Model",
        f"- Nodes: {len(model.get('nodes', []))}",
        f"- Lanes: {len(model.get('lanes', []))}",
        f"- Road bundles: {len(topology['roadBundles'])}",
        f"- Buildings: {len(model.get('buildings', []))}",
        f"- Cameras: {len(model.get('cameras', []))}",
        f"- Invalid lane references: {len(topology['invalidLaneIds'])}",
        "",
        "## Image Externalization",
        f"- Externalized calibrations: {externalized}",
        f"- Missing capture files: {len(missing)}",
        "",
        "## Grid Coverage",
        f"- Grid size: {coverage['gridSize']}",
        f"- Total cells: {coverage['totalCellCount']}",
        f"- Occupied cells: {coverage['occupiedCellCount']}",
        f"- Lane-covered cells: {coverage['laneCoveredCellCount']}",
        f"- Building-covered cells: {coverage['buildingCoveredCellCount']}",
        f"- Camera-FOV-covered cells: {coverage['cameraFovCoveredCellCount']}",
        "",
        "## Image Point Relations",
        f"- World-mapped image points: {len(relations)}",
        f"- Points near lane geometry: {lane_points}",
        f"- Points inside buildings: {building_points}",
        f"- Points outside owning camera FOV: {out_of_fov}",
        "",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--captures", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    input_bytes = args.input.read_bytes()
    payload = orjson.loads(input_bytes)
    model = payload.get("model", payload)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    compact_path = args.output_dir / f"{args.input.stem}.compact.json"
    reference_prefix = Path(os.path.relpath(args.captures, compact_path.parent)).as_posix()
    active_model, removed_calibrations = prune_unused_calibrations(model)
    compact_model, image_changes = externalize_calibration_images(active_model, args.captures, reference_prefix)
    compact_payload = copy.deepcopy(payload)
    if "model" in compact_payload:
        compact_payload["model"] = compact_model
    else:
        compact_payload = compact_model
    analysis = analyze_model(compact_model)
    analysis["imageExternalization"] = image_changes
    analysis["removedUnusedCalibrationIds"] = removed_calibrations
    graph = build_road_graph(compact_model)
    lane_vector = build_lane_vector_model(compact_model)
    baseline_exports = build_baseline_exports(model, args.input.name, hashlib.sha256(input_bytes).hexdigest())
    analysis_path = args.output_dir / f"{args.input.stem}.analysis.json"
    report_path = args.output_dir / f"{args.input.stem}.analysis.md"
    graph_path = args.output_dir / f"{args.input.stem}.road-graph.json"
    lane_vector_path = args.output_dir / f"{args.input.stem}.lane-vector.json"
    baseline_dir = args.output_dir / "baseline"
    baseline_road_lane_path = baseline_dir / f"{args.input.stem}.road-lane.v1.json"
    baseline_camera_mapping_path = baseline_dir / f"{args.input.stem}.camera-mapping.v1.json"
    baseline_manifest_path = baseline_dir / f"{args.input.stem}.baseline-manifest.v1.json"
    road_map_path = args.output_dir / f"{args.input.stem}.road-map.png"
    mapping_map_path = args.output_dir / f"{args.input.stem}.camera-point-map.png"
    camera_map_dir = args.output_dir / "camera-maps"
    camera_vector_map_dir = args.output_dir / "camera-vector-maps"
    junction_flow_map_dir = args.output_dir / "junction-flow-maps"
    compact_path.write_bytes(orjson.dumps(compact_payload, option=orjson.OPT_INDENT_2))
    analysis_path.write_bytes(orjson.dumps(analysis, option=orjson.OPT_INDENT_2))
    graph_path.write_bytes(orjson.dumps(graph, option=orjson.OPT_INDENT_2))
    lane_vector_path.write_bytes(orjson.dumps(lane_vector, option=orjson.OPT_INDENT_2))
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline_road_lane_path.write_bytes(orjson.dumps(baseline_exports["roadLane"], option=orjson.OPT_INDENT_2))
    baseline_camera_mapping_path.write_bytes(orjson.dumps(baseline_exports["cameraMapping"], option=orjson.OPT_INDENT_2))
    baseline_manifest_path.write_bytes(orjson.dumps(baseline_exports["manifest"], option=orjson.OPT_INDENT_2))
    report_path.write_text(markdown_report(compact_model, analysis), encoding="utf-8")
    render_world_map(compact_model, analysis, road_map_path, show_relations=False)
    render_world_map(compact_model, analysis, mapping_map_path, show_relations=True)
    camera_map_paths = []
    camera_vector_map_paths = []
    for camera in compact_model.get("cameras", []):
        path = camera_map_dir / f"{camera['id']}.png"
        render_world_map(compact_model, analysis, path, show_relations=True, camera_id=camera["id"])
        camera_map_paths.append(str(path))
        vector_path = camera_vector_map_dir / f"{camera['id']}.png"
        render_camera_vector_map(compact_model, lane_vector, camera["id"], vector_path)
        camera_vector_map_paths.append(str(vector_path))
    junction_flow_map_paths = []
    for junction in lane_vector["junctions"]:
        path = junction_flow_map_dir / f"{junction['nodeId']}.png"
        render_junction_flow_map(compact_model, lane_vector, junction["nodeId"], path)
        junction_flow_map_paths.append(str(path))
    print(orjson.dumps({"compact": str(compact_path), "analysis": str(analysis_path), "report": str(report_path), "roadGraph": str(graph_path), "laneVector": str(lane_vector_path), "baselineRoadLane": str(baseline_road_lane_path), "baselineCameraMapping": str(baseline_camera_mapping_path), "baselineManifest": str(baseline_manifest_path), "roadMap": str(road_map_path), "cameraPointMap": str(mapping_map_path), "cameraPointMaps": camera_map_paths, "cameraVectorMaps": camera_vector_map_paths, "junctionFlowMaps": junction_flow_map_paths, "removedUnusedCalibrationIds": removed_calibrations, "imageChanges": image_changes, "summary": analysis["gridCoverage"]["summary"], "laneVectorSummary": lane_vector["summary"]}).decode())


if __name__ == "__main__":
    main()
