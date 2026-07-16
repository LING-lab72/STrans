"""Analyze world-mapped vehicle tracks against the fixed road-lane baseline."""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import orjson
from PIL import Image, ImageDraw


def distance_to_segment(point: dict[str, float], a: dict[str, float], b: dict[str, float]) -> tuple[float, dict[str, float]]:
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    length_sq = dx * dx + dy * dy
    if not length_sq:
        return math.hypot(point["x"] - a["x"], point["y"] - a["y"]), {"x": 1.0, "y": 0.0}
    t = max(0.0, min(1.0, ((point["x"] - a["x"]) * dx + (point["y"] - a["y"]) * dy) / length_sq))
    length = math.sqrt(length_sq)
    return math.hypot(point["x"] - (a["x"] + t * dx), point["y"] - (a["y"] + t * dy)), {"x": dx / length, "y": dy / length}


def traffic_path(lane: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> list[dict[str, float]]:
    path = lane["geometry"]["renderPath"]
    source = nodes[lane["traffic"]["sourceNodeId"]]["position"]
    first, last = path[0], path[-1]
    first_distance = math.hypot(first["x"] - source["x"], first["y"] - source["y"])
    last_distance = math.hypot(last["x"] - source["x"], last["y"] - source["y"])
    return path if first_distance <= last_distance else list(reversed(path))


def assign_lane(point: dict[str, float], lanes: list[dict[str, Any]], nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    candidates = []
    for lane in lanes:
        path = traffic_path(lane, nodes)
        distance, tangent = min((distance_to_segment(point, a, b) for a, b in zip(path, path[1:])), key=lambda item: item[0])
        candidates.append({"lane": lane, "distance": distance, "tangent": tangent, "inside": distance <= float(lane["geometry"]["width"]) / 2})
    candidates.sort(key=lambda item: item["distance"])
    inside = [item for item in candidates if item["inside"]]
    selected = inside[0] if inside else None
    return {"laneId": selected["lane"]["id"] if selected else None, "status": "single_lane" if len(inside) == 1 else ("ambiguous_lane_band" if inside else "free_space"), "candidateLaneIds": [item["lane"]["id"] for item in inside], "tangent": selected["tangent"] if selected else None}


def analyze_observations(road: dict[str, Any], observations: list[dict[str, Any]], reverse_distance: float = 20.0) -> dict[str, Any]:
    nodes = {node["id"]: node for node in road["nodes"]}
    lanes = road["lanes"]
    lane_by_id = {lane["id"]: lane for lane in lanes}
    annotated = []
    tracks: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        point = observation.get("worldPoint")
        if not point:
            continue
        assignment = assign_lane(point, lanes, nodes)
        item = {**observation, "lane": assignment}
        annotated.append(item)
        tracks[(str(item.get("cameraId", "")), str(item.get("trackId", "")))].append(item)
    lane_flow = {lane["id"]: {"observationCount": 0, "trackIds": set(), "signedDistance": 0.0} for lane in lanes}
    events = []
    heat_cells: dict[tuple[int, int], int] = defaultdict(int)
    grid_size = float(road["world"].get("gridSize", 20))
    for item in annotated:
        lane_id = item["lane"]["laneId"]
        if lane_id:
            lane_flow[lane_id]["observationCount"] += 1
            lane_flow[lane_id]["trackIds"].add(str(item.get("trackId")))
        point = item["worldPoint"]
        heat_cells[(int(point["x"] // grid_size), int(point["y"] // grid_size))] += 1
    for (camera_id, track_id), entries in tracks.items():
        entries.sort(key=lambda item: item.get("timestampMs", 0))
        signed_by_lane: dict[str, float] = defaultdict(float)
        for previous, current in zip(entries, entries[1:]):
            previous_lane, current_lane = previous["lane"]["laneId"], current["lane"]["laneId"]
            dx = current["worldPoint"]["x"] - previous["worldPoint"]["x"]
            dy = current["worldPoint"]["y"] - previous["worldPoint"]["y"]
            if previous_lane and previous_lane == current_lane:
                tangent = current["lane"]["tangent"] or previous["lane"]["tangent"]
                signed = dx * tangent["x"] + dy * tangent["y"]
                signed_by_lane[previous_lane] += signed
                lane_flow[previous_lane]["signedDistance"] += signed
            if previous_lane and current_lane and previous_lane != current_lane:
                source, target = lane_by_id[previous_lane], lane_by_id[current_lane]
                if source["roadBundleId"] == target["roadBundleId"]:
                    tangent = previous["lane"]["tangent"] or {"x": 1.0, "y": 0.0}
                    lateral = dx * -tangent["y"] + dy * tangent["x"]
                    boundary = "rightBoundary" if lateral > 0 else "leftBoundary"
                    if source["markings"].get(boundary) == "solid":
                        events.append({"type": "solid_boundary_crossing_candidate", "cameraId": camera_id, "trackId": track_id, "timestampMs": current.get("timestampMs"), "fromLaneId": previous_lane, "toLaneId": current_lane, "boundary": boundary})
        for lane_id, signed_distance in signed_by_lane.items():
            if len(entries) >= 3 and signed_distance <= -reverse_distance:
                events.append({"type": "reverse_direction_candidate", "cameraId": camera_id, "trackId": track_id, "laneId": lane_id, "startTimestampMs": entries[0].get("timestampMs"), "endTimestampMs": entries[-1].get("timestampMs"), "signedDistance": round(signed_distance, 3)})
        if len(entries) >= 3:
            first_point = entries[0]["worldPoint"]
            max_displacement = max(math.hypot(item["worldPoint"]["x"] - first_point["x"], item["worldPoint"]["y"] - first_point["y"]) for item in entries)
            duration_ms = entries[-1].get("timestampMs", 0) - entries[0].get("timestampMs", 0)
            if duration_ms >= 5000 and max_displacement <= 5:
                events.append({"type": "stopped_on_lane_candidate", "cameraId": camera_id, "trackId": track_id, "laneId": entries[-1]["lane"]["laneId"], "startTimestampMs": entries[0].get("timestampMs"), "endTimestampMs": entries[-1].get("timestampMs"), "maxDisplacement": round(max_displacement, 3)})
    output_flow = {lane_id: {"observationCount": item["observationCount"], "uniqueTrackCount": len(item["trackIds"]), "signedDistance": round(item["signedDistance"], 3)} for lane_id, item in lane_flow.items()}
    return {"schema": "road_logic_modeler.traffic-analysis.v1", "observations": annotated, "laneFlow": output_flow, "heatmap": {"gridSize": grid_size, "cells": [{"cell": list(cell), "count": count} for cell, count in sorted(heat_cells.items())]}, "events": events, "summary": {"observationCount": len(annotated), "trackedVehicleCount": len(tracks), "eventCount": len(events)}}


def _road_canvas(road: dict[str, Any]) -> tuple[Image.Image, ImageDraw.ImageDraw, float, Any]:
    world = road["world"]
    canvas = Image.new("RGB", (1400, 900), "#101820")
    draw = ImageDraw.Draw(canvas)
    pad, scale = 50, min(1300 / world["width"], 800 / world["height"])
    def screen(point: dict[str, float]) -> tuple[float, float]: return pad + point["x"] * scale, pad + point["y"] * scale
    for building in road.get("buildings", []):
        center, width, height = building["center"], building["width"], building["height"]
        x1, y1 = screen({"x": center["x"] - width / 2, "y": center["y"] - height / 2})
        x2, y2 = screen({"x": center["x"] + width / 2, "y": center["y"] + height / 2})
        draw.rectangle((x1, y1, x2, y2), fill="#52657a", outline="#9fb0c2", width=2)
    for lane in road["lanes"]:
        path = [screen(point) for point in lane["geometry"]["renderPath"]]
        draw.line(path, fill="#3e5b65", width=max(5, int(lane["geometry"]["width"] * scale * 0.72)))
        style = lane.get("markings", {}).get("leftBoundary", "solid")
        if style == "dashed":
            for a, b in zip(path, path[1:]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                length = math.hypot(dx, dy) or 1
                for start in range(0, int(length), 18):
                    end = min(start + 10, length)
                    draw.line((a[0] + dx * start / length, a[1] + dy * start / length, a[0] + dx * end / length, a[1] + dy * end / length), fill="#cbd5e1", width=2)
        else:
            draw.line(path, fill="#cbd5e1", width=2)
    for node in road.get("nodes", []):
        x, y = screen(node["position"])
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="#f8fafc", outline="#17212b")
    return canvas, draw, scale, screen


def render_road_base(road: dict[str, Any], output_path: Path) -> None:
    canvas, draw, _, _ = _road_canvas(road)
    draw.text((50, 18), "Road model base: lanes, markings, nodes, and buildings", fill="#e2e8f0")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)


def render_heatmap(road: dict[str, Any], analysis: dict[str, Any], output_path: Path) -> None:
    canvas, draw, _, screen = _road_canvas(road)
    maximum = max((cell["count"] for cell in analysis["heatmap"]["cells"]), default=1)
    step = analysis["heatmap"]["gridSize"]
    for cell in analysis["heatmap"]["cells"]:
        alpha = cell["count"] / maximum
        x, y = cell["cell"][0] * step, cell["cell"][1] * step
        color = (int(255 * alpha), int(180 * (1 - alpha)), 30)
        draw.rectangle((*screen({"x": x, "y": y}), *screen({"x": x + step, "y": y + step})), fill=color)
    draw.text((50, 18), "Traffic heatmap: yellow/red cells have more mapped observations", fill="#e2e8f0")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--road", required=True, type=Path)
    parser.add_argument("--observations", required=True, type=Path, help="JSONL records with cameraId, trackId, timestampMs, and worldPoint")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    road = orjson.loads(args.road.read_bytes())
    observations = [orjson.loads(line) for line in args.observations.read_bytes().splitlines() if line.strip()]
    analysis = analyze_observations(road, observations)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "traffic-analysis.v1.json"
    heatmap = args.output_dir / "traffic-heatmap.png"
    base = args.output_dir / "road-heatmap-base.png"
    output.write_bytes(orjson.dumps(analysis, option=orjson.OPT_INDENT_2))
    render_road_base(road, base)
    render_heatmap(road, analysis, heatmap)
    print(orjson.dumps({"analysis": str(output), "base": str(base), "heatmap": str(heatmap), "summary": analysis["summary"]}).decode())


if __name__ == "__main__":
    main()
