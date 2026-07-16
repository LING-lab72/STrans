"""Compile a logical junction node into a non-overlapping physical road surface."""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import orjson
from PIL import Image, ImageDraw
from shapely.geometry import LineString, MultiPoint, Polygon, mapping, shape
from shapely.ops import unary_union


def distance(a: dict[str, float], b: dict[str, float]) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def unit(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    length = math.hypot(dx, dy) or 1.0
    return {"x": dx / length, "y": dy / length}


def traffic_path(lane: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> list[dict[str, float]]:
    path = lane["geometry"]["renderPath"]
    source = nodes[lane["traffic"]["sourceNodeId"]]["position"]
    return path if distance(path[0], source) <= distance(path[-1], source) else list(reversed(path))


def cubic(a: dict[str, float], c1: dict[str, float], c2: dict[str, float], b: dict[str, float], count: int = 32) -> list[dict[str, float]]:
    return [{"x": (1-t)**3*a["x"] + 3*(1-t)**2*t*c1["x"] + 3*(1-t)*t*t*c2["x"] + t**3*b["x"], "y": (1-t)**3*a["y"] + 3*(1-t)**2*t*c1["y"] + 3*(1-t)*t*t*c2["y"] + t**3*b["y"]} for t in (index / count for index in range(count + 1))]


def rectangle(center: dict[str, float], along: dict[str, float], half_length: float, half_width: float) -> Polygon:
    normal = {"x": -along["y"], "y": along["x"]}
    return Polygon([(
        center["x"] + along["x"] * along_sign * half_length + normal["x"] * normal_sign * half_width,
        center["y"] + along["y"] * along_sign * half_length + normal["y"] * normal_sign * half_width,
    ) for along_sign, normal_sign in ((-1, -1), (1, -1), (1, 1), (-1, 1))])


def compile_junction(road: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    nodes = {item["id"]: item for item in road["nodes"]}
    lanes = {item["id"]: item for item in road["lanes"]}
    node_id = rules["nodeId"]
    node = nodes[node_id]["position"]
    cutback = float(rules.get("cutback", 90))
    incident = [lane for lane in lanes.values() if node_id in (lane["traffic"]["sourceNodeId"], lane["traffic"]["targetNodeId"])]
    if len(incident) < 2:
        raise ValueError(f"Node {node_id} does not have enough incident lanes")

    lane_ports: dict[str, dict[str, Any]] = {}
    approaches: dict[str, list[dict[str, Any]]] = defaultdict(list)
    approach_surfaces = []
    for lane in incident:
        path = traffic_path(lane, nodes)
        incoming = lane["traffic"]["targetNodeId"] == node_id
        if incoming:
            tangent = unit(path[-2], path[-1])
            node_end, far_end = path[-1], path[0]
            port = {"x": node_end["x"] - tangent["x"] * cutback, "y": node_end["y"] - tangent["y"] * cutback}
            travel = tangent
        else:
            tangent = unit(path[0], path[1])
            node_end, far_end = path[0], path[-1]
            port = {"x": node_end["x"] + tangent["x"] * cutback, "y": node_end["y"] + tangent["y"] * cutback}
            travel = tangent
        width = float(lane["geometry"]["width"])
        lane_ports[lane["id"]] = {"laneId": lane["id"], "point": port, "travelDirection": travel, "incoming": incoming, "width": width, "roadBundleId": lane.get("roadBundleId")}
        approaches[lane.get("roadBundleId") or lane["id"]].append(lane_ports[lane["id"]])
        approach_surfaces.append(LineString([(far_end["x"], far_end["y"]), (port["x"], port["y"])]).buffer(width / 2, cap_style="flat", join_style="round"))

    port_points = [(port["point"]["x"], port["point"]["y"]) for port in lane_ports.values()]
    max_width = max(port["width"] for port in lane_ports.values())
    junction_core = MultiPoint(port_points).convex_hull.buffer(max_width * 0.7, join_style="round")
    surface = unary_union([junction_core, *approach_surfaces]).buffer(0)

    approach_items, crosswalks, stop_lines = [], [], []
    for bundle_id, ports in sorted(approaches.items()):
        outward_vectors = []
        for port in ports:
            direction = port["travelDirection"]
            outward_vectors.append({"x": -direction["x"], "y": -direction["y"]} if port["incoming"] else direction)
        outward = {"x": sum(item["x"] for item in outward_vectors) / len(outward_vectors), "y": sum(item["y"] for item in outward_vectors) / len(outward_vectors)}
        outward = unit({"x": 0, "y": 0}, outward)
        center = {"x": sum(item["point"]["x"] for item in ports) / len(ports), "y": sum(item["point"]["y"] for item in ports) / len(ports)}
        normal = {"x": -outward["y"], "y": outward["x"]}
        lateral = [port["point"]["x"] * normal["x"] + port["point"]["y"] * normal["y"] for port in ports]
        half_width = (max(lateral) - min(lateral)) / 2 + max(port["width"] for port in ports) / 2
        stripe_polygons = []
        for index in range(6):
            stripe_center = {"x": center["x"] + outward["x"] * (9 + index * 5), "y": center["y"] + outward["y"] * (9 + index * 5)}
            stripe_polygons.append(rectangle(stripe_center, outward, 1.5, half_width - 2))
        crosswalks.append({"approachId": bundle_id, "polygons": [mapping(polygon) for polygon in stripe_polygons]})
        stop_center = {"x": center["x"] + outward["x"] * 42, "y": center["y"] + outward["y"] * 42}
        stop_lines.append({"approachId": bundle_id, "polygon": mapping(rectangle(stop_center, outward, 1.2, half_width))})
        approach_items.append({"id": bundle_id, "lanePortIds": [port["laneId"] for port in ports], "outwardDirection": outward, "boundaryCenter": center, "roadHalfWidth": round(half_width, 3)})

    connections = []
    for index, item in enumerate(rules.get("connections", []), start=1):
        source = lane_ports.get(item["fromLaneId"])
        target = lane_ports.get(item["toLaneId"])
        if not source or not target or not source["incoming"] or target["incoming"]:
            raise ValueError(f"Invalid lane connection: {item}")
        a, b = source["point"], target["point"]
        inbound, outbound = source["travelDirection"], target["travelDirection"]
        handle = min(cutback * 0.72, max(20.0, distance(a, b) * 0.42))
        path = cubic(a, {"x": a["x"] + inbound["x"] * handle, "y": a["y"] + inbound["y"] * handle}, {"x": b["x"] - outbound["x"] * handle, "y": b["y"] - outbound["y"] * handle}, b)
        line = LineString([(point["x"], point["y"]) for point in path])
        if not surface.buffer(0.01).covers(line):
            surface = unary_union([surface, line.buffer(min(source["width"], target["width"]) / 2, cap_style="flat", join_style="round")]).buffer(0)
        connections.append({"id": item.get("id", f"connection_{index}"), "fromLaneId": source["laneId"], "toLaneId": target["laneId"], "path": path})

    return {
        "schema": "road_logic_modeler.compiled-junction.v1",
        "sourceNodeId": node_id,
        "surface": mapping(surface),
        "approaches": approach_items,
        "lanePorts": list(lane_ports.values()),
        "laneConnections": connections,
        "crosswalks": crosswalks,
        "stopLines": stop_lines,
        "summary": {"approachCount": len(approach_items), "lanePortCount": len(lane_ports), "connectionCount": len(connections), "crosswalkCount": len(crosswalks)},
    }


def polygon_rings(geometry: dict[str, Any]) -> list[list[tuple[float, float]]]:
    value = shape(geometry)
    polygons = list(value.geoms) if value.geom_type == "MultiPolygon" else [value]
    return [list(polygon.exterior.coords) for polygon in polygons]


def render_compiled(compiled: dict[str, Any], output_path: Path, debug: bool = False) -> None:
    surface = shape(compiled["surface"])
    min_x, min_y, max_x, max_y = surface.bounds
    margin = max(max_x - min_x, max_y - min_y) * 0.08
    canvas = Image.new("RGB", (1400, 1000), "#101820")
    draw = ImageDraw.Draw(canvas)
    scale = min(1240 / max(max_x - min_x + margin * 2, 1), 840 / max(max_y - min_y + margin * 2, 1))
    def screen(point: tuple[float, float] | dict[str, float]) -> tuple[float, float]:
        x, y = (point["x"], point["y"]) if isinstance(point, dict) else point
        return 80 + (x - min_x + margin) * scale, 80 + (y - min_y + margin) * scale
    for ring in polygon_rings(compiled["surface"]):
        draw.polygon([screen(point) for point in ring], fill="#445f68", outline="#9fb4bd")
    for item in compiled["crosswalks"]:
        for geometry in item["polygons"]:
            for ring in polygon_rings(geometry):
                draw.polygon([screen(point) for point in ring], fill="#f8fafc")
    for item in compiled["stopLines"]:
        for ring in polygon_rings(item["polygon"]):
            draw.polygon([screen(point) for point in ring], fill="#f8fafc")
    if debug:
        palette = ("#22d3ee", "#fbbf24", "#c084fc", "#34d399", "#fb7185")
        for index, connection in enumerate(compiled["laneConnections"]):
            points = [screen(point) for point in connection["path"]]
            draw.line(points, fill=palette[index % len(palette)], width=4, joint="curve")
            draw.text(points[len(points) // 2], f"{connection['fromLaneId']}->{connection['toLaneId']}", fill=palette[index % len(palette)])
        for port in compiled["lanePorts"]:
            x, y = screen(port["point"])
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill="#ffffff")
            draw.text((x + 7, y - 12), port["laneId"], fill="#e2e8f0")
    draw.text((80, 26), "Compiled physical junction" + (" - connectivity debug" if debug else " - road surface"), fill="#e2e8f0")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--road", required=True, type=Path)
    parser.add_argument("--rules", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--surface-image", required=True, type=Path)
    parser.add_argument("--debug-image", required=True, type=Path)
    args = parser.parse_args()
    compiled = compile_junction(orjson.loads(args.road.read_bytes()), orjson.loads(args.rules.read_bytes()))
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_bytes(orjson.dumps(compiled, option=orjson.OPT_INDENT_2))
    render_compiled(compiled, args.surface_image)
    render_compiled(compiled, args.debug_image, debug=True)
    print(orjson.dumps({"compiled": str(args.output_json), "surfaceImage": str(args.surface_image), "debugImage": str(args.debug_image), "summary": compiled["summary"]}).decode())


if __name__ == "__main__":
    main()
