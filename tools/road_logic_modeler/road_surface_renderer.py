"""Trace directed lanes into continuous road-surface geometry and render it."""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import orjson
from PIL import Image, ImageDraw


def distance(a: dict[str, float], b: dict[str, float]) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def unit(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    size = math.hypot(dx, dy) or 1.0
    return {"x": dx / size, "y": dy / size}


def dot(a: dict[str, float], b: dict[str, float]) -> float:
    return a["x"] * b["x"] + a["y"] * b["y"]


def traffic_path(lane: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> list[dict[str, float]]:
    path = lane["geometry"]["renderPath"]
    source = nodes[lane["traffic"]["sourceNodeId"]]["position"]
    return path if distance(path[0], source) <= distance(path[-1], source) else list(reversed(path))


def sample_cubic(a: dict[str, float], c1: dict[str, float], c2: dict[str, float], b: dict[str, float], count: int = 12) -> list[dict[str, float]]:
    return [{"x": (1-t)**3*a["x"] + 3*(1-t)**2*t*c1["x"] + 3*(1-t)*t*t*c2["x"] + t**3*b["x"], "y": (1-t)**3*a["y"] + 3*(1-t)**2*t*c1["y"] + 3*(1-t)*t*t*c2["y"] + t**3*b["y"]} for t in (i / count for i in range(count + 1))]


def build_lane_traces(road: dict[str, Any], cosine_threshold: float = 0.96) -> list[dict[str, Any]]:
    nodes = {item["id"]: item for item in road["nodes"]}
    lanes = {item["id"]: item for item in road["lanes"]}
    paths = {lane_id: traffic_path(lane, nodes) for lane_id, lane in lanes.items()}
    incoming, outgoing = defaultdict(list), defaultdict(list)
    for lane_id, lane in lanes.items():
        incoming[lane["traffic"]["targetNodeId"]].append(lane_id)
        outgoing[lane["traffic"]["sourceNodeId"]].append(lane_id)
    next_lane, previous_lane, continuities = {}, {}, {}
    for node_id in set(incoming) | set(outgoing):
        candidates = []
        for source_id in incoming[node_id]:
            source_path = paths[source_id]
            source_direction = unit(source_path[-2], source_path[-1])
            for target_id in outgoing[node_id]:
                target_path = paths[target_id]
                target_direction = unit(target_path[0], target_path[1])
                cosine = dot(source_direction, target_direction)
                if cosine >= cosine_threshold:
                    candidates.append((distance(source_path[-1], target_path[0]) + (1 - cosine) * 500, source_id, target_id, cosine))
        used_source, used_target = set(), set()
        for _, source_id, target_id, cosine in sorted(candidates):
            if source_id in used_source or target_id in used_target:
                continue
            used_source.add(source_id)
            used_target.add(target_id)
            next_lane[source_id], previous_lane[target_id] = target_id, source_id
            continuities[(source_id, target_id)] = {"atNodeId": node_id, "directionCosine": round(cosine, 4)}
    traces, visited = [], set()
    starts = [lane_id for lane_id in lanes if lane_id not in previous_lane]
    for start in starts + [lane_id for lane_id in lanes if lane_id not in starts]:
        if start in visited:
            continue
        lane_ids, sections, path, links = [], [], [], []
        current = start
        while current not in visited:
            visited.add(current)
            current_path = paths[current]
            lane_ids.append(current)
            sections.append({"laneId": current, "path": current_path, "width": lanes[current]["geometry"]["width"], "markings": lanes[current]["markings"]})
            path.extend(current_path if not path else current_path[1:])
            following = next_lane.get(current)
            if not following:
                break
            a, b = current_path[-1], paths[following][0]
            exit_direction, entry_direction = unit(current_path[-2], a), unit(b, paths[following][1])
            handle = min(38.0, max(8.0, distance(a, b) * 0.55))
            connector = sample_cubic(a, {"x": a["x"] + exit_direction["x"] * handle, "y": a["y"] + exit_direction["y"] * handle}, {"x": b["x"] - entry_direction["x"] * handle, "y": b["y"] - entry_direction["y"] * handle}, b)
            path.extend(connector[1:])
            links.append({"fromLaneId": current, "toLaneId": following, **continuities[(current, following)], "path": connector})
            current = following
        traces.append({"id": f"trace_{len(traces)+1}", "laneIds": lane_ids, "path": path, "sections": sections, "continuities": links})
    return traces


def offset_path(points: list[dict[str, float]], offset: float) -> list[dict[str, float]]:
    result = []
    for index, point in enumerate(points):
        a, b = points[max(0, index - 1)], points[min(len(points) - 1, index + 1)]
        direction = unit(a, b)
        result.append({"x": point["x"] - direction["y"] * offset, "y": point["y"] + direction["x"] * offset})
    return result


def draw_styled_line(draw: ImageDraw.ImageDraw, points: list[tuple[float, float]], style: str, color: str, width: int) -> None:
    if style != "dashed":
        draw.line(points, fill=color, width=width, joint="curve")
        return
    for a, b in zip(points, points[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy) or 1.0
        for start in range(0, int(length), 18):
            end = min(start + 10, length)
            draw.line((a[0] + dx * start / length, a[1] + dy * start / length, a[0] + dx * end / length, a[1] + dy * end / length), fill=color, width=width)


def render_surface(road: dict[str, Any], traces: list[dict[str, Any]], output_path: Path, heatmap: dict[str, Any] | None = None) -> None:
    world = road["world"]
    canvas = Image.new("RGB", (1800, 1180), "#101820")
    draw = ImageDraw.Draw(canvas)
    pad, scale = 70, min(1660 / world["width"], 1040 / world["height"])
    def screen(point: dict[str, float]) -> tuple[float, float]: return pad + point["x"] * scale, pad + point["y"] * scale
    for building in road.get("buildings", []):
        center = building["center"]
        x1, y1 = screen({"x": center["x"] - building["width"] / 2, "y": center["y"] - building["height"] / 2})
        x2, y2 = screen({"x": center["x"] + building["width"] / 2, "y": center["y"] + building["height"] / 2})
        draw.rectangle((x1, y1, x2, y2), fill="#566b80", outline="#a5b4c5", width=2)
    for trace in traces:
        widths = [section["width"] for section in trace["sections"]]
        draw.line([screen(point) for point in trace["path"]], fill="#445f68", width=max(5, int(sum(widths) / len(widths) * scale * 0.9)), joint="curve")
        for section in trace["sections"]:
            half = section["width"] / 2
            left = offset_path(section["path"], -half)
            right = offset_path(section["path"], half)
            draw_styled_line(draw, [screen(point) for point in left], section["markings"].get("leftBoundary", "solid"), "#e2e8f0", 2)
            draw_styled_line(draw, [screen(point) for point in right], section["markings"].get("rightBoundary", "solid"), "#e2e8f0", 2)
    if heatmap:
        cells = heatmap.get("cells", [])
        maximum = max((item["count"] for item in cells), default=1)
        step = float(heatmap["gridSize"])
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay, "RGBA")
        for cell in cells:
            intensity = cell["count"] / maximum
            x, y = cell["cell"][0] * step, cell["cell"][1] * step
            x1, y1 = screen({"x": x, "y": y})
            x2, y2 = screen({"x": x + step, "y": y + step})
            overlay_draw.rectangle((x1, y1, x2, y2), fill=(255, int(190 * (1 - intensity)), 25, int(70 + intensity * 120)))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(canvas)
    draw.text((pad, 26), "Continuous lane-surface base: traces join only same-direction lane geometry", fill="#e2e8f0")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--road", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--traces-output", type=Path)
    parser.add_argument("--traffic-analysis", type=Path, help="Optional traffic-analysis.v1.json to draw as a heatmap overlay")
    args = parser.parse_args()
    road = orjson.loads(args.road.read_bytes())
    traces = build_lane_traces(road)
    heatmap = orjson.loads(args.traffic_analysis.read_bytes()).get("heatmap") if args.traffic_analysis else None
    render_surface(road, traces, args.output, heatmap)
    if args.traces_output:
        args.traces_output.parent.mkdir(parents=True, exist_ok=True)
        args.traces_output.write_bytes(orjson.dumps({"schema": "road_logic_modeler.lane-surface-traces.v1", "traces": traces, "summary": {"traceCount": len(traces), "laneCount": len(road["lanes"])}}, option=orjson.OPT_INDENT_2))
    print(orjson.dumps({"image": str(args.output), "traceCount": len(traces)}).decode())


if __name__ == "__main__":
    main()
