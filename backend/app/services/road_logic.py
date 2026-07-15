from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.schemas.dashboard import AnalysisResult, TrafficEvent


ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "data" / "road_model"
ROAD_PATH = MODEL_DIR / "road-lane.v1.json"
CAMERA_PATH = MODEL_DIR / "camera-mapping.v1.json"
COMPACT_PATH = MODEL_DIR / "road-model.compact.json"
INTERSECTION_PATH = MODEL_DIR / "intersection-zones.v1.json"
CALIBRATION_WIDTH = 1920.0
CALIBRATION_HEIGHT = 1080.0
NO_STOP_DWELL_SECONDS = 30.0
# Congestion is a live lane state, not a historical accumulation.  Keep only a
# short diagnostic trail and derive the actual heatmap from active tracks.
HEAT_TTL_SECONDS = 8.0
CONGESTION_TRACK_TTL_SECONDS = 3.0
CONGESTION_CONFIRM_FRAMES = 2
CONGESTION_MIN_BOX_AREA = 700.0
CONGESTION_MIN_BOX_SIDE = 16.0
CONGESTION_MAX_ASPECT_RATIO = 3.6
VEHICLE_CLASSES = {
    "car", "van", "truck", "bus", "motor", "motorcycle", "motorbike",
    "tricycle", "awning-tricycle", "bicycle", "plate-derived vehicle",
}


def _distance_to_segment(point: tuple[float, float], first: dict[str, float], second: dict[str, float]) -> float:
    px, py = point
    ax, ay = float(first["x"]), float(first["y"])
    bx, by = float(second["x"]), float(second["y"])
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    ratio = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + ratio * dx), py - (ay + ratio * dy))


def _distance_to_path(point: tuple[float, float], path: list[dict[str, float]]) -> float:
    if len(path) < 2:
        return float("inf")
    return min(_distance_to_segment(point, path[index], path[index + 1]) for index in range(len(path) - 1))


def _point_in_polygon(point: tuple[float, float], polygon: list[dict[str, float]]) -> bool:
    """Ray-casting containment test for modeled junction areas."""
    if len(polygon) < 3:
        return False
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = float(current["x"]), float(current["y"])
        x2, y2 = float(previous["x"]), float(previous["y"])
        crosses = (y1 > y) != (y2 > y)
        if crosses and x < (x2 - x1) * (y - y1) / max(y2 - y1, 1e-9) + x1:
            inside = not inside
        previous = current
    return inside


class RoadLogicService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._heat_points: deque[dict[str, Any]] = deque(maxlen=1200)
        self._congestion_tracks: dict[str, dict[str, Any]] = {}
        self._stop_states: dict[str, dict[str, Any]] = {}
        self._road = self._load_json(ROAD_PATH)
        self._camera = self._load_json(CAMERA_PATH)
        self._compact = self._load_json(COMPACT_PATH)
        self._intersection_model = self._load_json(INTERSECTION_PATH)
        self._lanes = self._road.get("lanes", [])
        self._junction_zones = self._intersection_model.get("zones", [])
        self._homographies: dict[str, np.ndarray] = {}
        self._camera_quality: dict[str, dict[str, Any]] = {}
        self._build_homographies()

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _build_homographies_legacy(self) -> None:
        for camera in self._camera.get("cameras", []):
            camera_id = str(camera.get("id", ""))
            points = [item for item in camera.get("points", []) if item.get("imagePosition") and item.get("worldPoint")]
            live_id = camera_id.replace("cam_", "live")
            local_viewbox = self._local_viewbox(points)
            if len(points) < 4:
                self._camera_quality[live_id] = {"ready": False, "point_count": len(points), "reason": "标定点少于 4 个", "local_viewbox": local_viewbox}
                continue
            image_points = np.float32([[item["imagePosition"]["x"], item["imagePosition"]["y"]] for item in points])
            world_points = np.float32([[item["worldPoint"]["x"], item["worldPoint"]["y"]] for item in points])
            matrix, inliers = cv2.findHomography(image_points, world_points, cv2.RANSAC, 12.0)
            if matrix is None:
                self._camera_quality[live_id] = {"ready": False, "point_count": len(points), "reason": "无法拟合单应性", "local_viewbox": local_viewbox}
                continue
            self._homographies[live_id] = matrix
            inlier_count = int(inliers.sum()) if inliers is not None else len(points)
            self._camera_quality[live_id] = {
                "ready": True,
                "point_count": len(points),
                "inlier_count": inlier_count,
                "method": "homography_ransac",
                "local_viewbox": local_viewbox,
            }

    def _build_homographies(self) -> None:
        """Build frame-to-road transforms from explicit stream preset bindings."""
        compact_cameras = {
            str(camera.get("id", "")): camera
            for camera in self._compact.get("model", {}).get("cameras", [])
        }
        candidates: dict[str, list[tuple[dict[str, Any], list[dict[str, Any]]]]] = {}
        for camera in self._camera.get("cameras", []):
            camera_id = str(camera.get("id", ""))
            points = [item for item in camera.get("points", []) if item.get("imagePosition") and item.get("worldPoint")]
            stream_id = str(compact_cameras.get(camera_id, {}).get("streamPresetId", "")).strip()
            if not stream_id:
                self._camera_quality[f"unmapped:{camera_id}"] = {
                    "ready": False,
                    "point_count": len(points),
                    "reason": "Missing streamPresetId",
                    "source_camera_id": camera_id,
                    "candidate_camera_ids": [camera_id],
                    "ambiguous": False,
                    "local_viewbox": self._local_viewbox(points),
                }
                continue
            candidates.setdefault(stream_id, []).append((camera, points))

        for stream_id, stream_candidates in candidates.items():
            # One live stream may be represented by multiple physical camera
            # records. Prefer more control points, then camera id for a stable
            # tie-break, and surface the ambiguity to the UI/API.
            stream_candidates.sort(key=lambda item: (-len(item[1]), str(item[0].get("id", ""))))
            camera, points = stream_candidates[0]
            camera_id = str(camera.get("id", ""))
            candidate_ids = [str(item[0].get("id", "")) for item in stream_candidates]
            local_viewbox = self._local_viewbox(points)
            metadata = {
                "point_count": len(points),
                "local_viewbox": local_viewbox,
                "source_camera_id": camera_id,
                "candidate_camera_ids": candidate_ids,
                "ambiguous": len(candidate_ids) > 1,
            }
            if len(points) < 2:
                self._camera_quality[stream_id] = {
                    **metadata,
                    "ready": False,
                    "reason": "At least two calibration points are required.",
                }
                continue

            image_points = np.float32([[item["imagePosition"]["x"], item["imagePosition"]["y"]] for item in points])
            world_points = np.float32([[item["worldPoint"]["x"], item["worldPoint"]["y"]] for item in points])
            if len(points) >= 4:
                matrix, inliers = cv2.findHomography(image_points, world_points, cv2.RANSAC, 12.0)
                method = "homography_ransac"
            else:
                # Similarity transform: rotation, uniform scale and
                # translation. It is the valid, deterministic two-point
                # fallback for cameras such as live2/live9/live11.
                affine, inliers = cv2.estimateAffinePartial2D(image_points, world_points, method=cv2.LMEDS)
                matrix = None if affine is None else np.vstack([affine, [0.0, 0.0, 1.0]])
                method = "similarity_2point" if len(points) == 2 else "affine_partial"

            if matrix is None:
                self._camera_quality[stream_id] = {
                    **metadata,
                    "ready": False,
                    "reason": "Calibration transform could not be fitted.",
                }
                continue
            self._homographies[stream_id] = matrix
            inlier_count = int(inliers.sum()) if inliers is not None else len(points)
            self._camera_quality[stream_id] = {
                **metadata,
                "ready": True,
                "inlier_count": inlier_count,
                "method": method,
            }

    def _local_viewbox(self, points: list[dict[str, Any]]) -> dict[str, float]:
        world = self._road.get("world", {})
        world_width = float(world.get("width", 1200))
        world_height = float(world.get("height", 760))
        coordinates = [item["worldPoint"] for item in points if item.get("worldPoint")]
        if not coordinates:
            return {"x": 0.0, "y": 0.0, "width": world_width, "height": world_height}

        min_x = min(float(point["x"]) for point in coordinates)
        max_x = max(float(point["x"]) for point in coordinates)
        min_y = min(float(point["y"]) for point in coordinates)
        max_y = max(float(point["y"]) for point in coordinates)
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        # A calibration rectangle is usually much tighter than what a viewer perceives
        # as one road section. Keep enough adjacent lane context for the compact map.
        width = min(world_width, max(560.0, max_x - min_x + 220.0))
        height = min(world_height, max(315.0, max_y - min_y + 180.0))
        aspect = 16 / 9
        if width / height < aspect:
            width = min(world_width, height * aspect)
        else:
            height = min(world_height, width / aspect)
        x = max(0.0, min(world_width - width, center_x - width / 2))
        y = max(0.0, min(world_height - height, center_y - height / 2))
        return {"x": round(x, 2), "y": round(y, 2), "width": round(width, 2), "height": round(height, 2)}

    def model_snapshot(self) -> dict[str, Any]:
        compact_model = self._compact.get("model", {})
        compact_cameras = compact_model.get("cameras", [])
        camera_views = {}
        for camera in compact_cameras:
            stream_id = str(camera.get("streamPresetId", ""))
            if not stream_id:
                continue
            camera_views.setdefault(stream_id, []).append({
                "id": camera.get("id"),
                "name": camera.get("name"),
                "place": camera.get("place"),
                "x": camera.get("x"),
                "y": camera.get("y"),
                "direction": camera.get("direction"),
                "fov": camera.get("fov"),
                "range": camera.get("range"),
            })
        return {
            "status": "ready" if self._road and self._camera else "missing",
            "schema": self._road.get("schema"),
            "world": self._road.get("world", {"width": 1200, "height": 760, "unit": "cm"}),
            "lanes": [
                {
                    "id": lane.get("id"),
                    "name": lane.get("name"),
                    "width": lane.get("geometry", {}).get("width", 28),
                    "path": lane.get("geometry", {}).get("renderPath", []),
                    "no_stopping": True,
                    "direction": lane.get("traffic", {}).get("direction"),
                }
                for lane in self._lanes
            ],
            "nodes": [
                {
                    "id": node.get("id"),
                    "type": node.get("type"),
                    "x": node.get("position", {}).get("x"),
                    "y": node.get("position", {}).get("y"),
                }
                for node in self._road.get("nodes", [])
                if node.get("position")
            ],
            "intersections": [
                {
                    "id": zone.get("id"),
                    "node_id": zone.get("node_id"),
                    "name": zone.get("name"),
                    "type": zone.get("type"),
                    "flattened": bool(zone.get("flattened", True)),
                    "polygon": zone.get("polygon", []),
                }
                for zone in self._junction_zones
            ],
            "buildings": [
                {key: building.get(key) for key in ("id", "name", "x", "y", "width", "height")}
                for building in compact_model.get("buildings", [])
            ],
            "cameras": self._camera_quality,
            "camera_views": camera_views,
            "policy": {
                "no_stopping_scope": "all_modeled_traffic_lanes",
                "dwell_seconds": NO_STOP_DWELL_SECONDS,
                "stationary_distance_cm": 6.0,
            },
        }

    def heatmap_snapshot(self, camera_id: str | None = None) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            points = [dict(item) for item in self._heat_points if not camera_id or item["camera_id"] == camera_id]
            active_tracks = [
                dict(state)
                for state in self._congestion_tracks.values()
                if (not camera_id or state["camera_id"] == camera_id)
                and now - float(state["last_seen"]) <= CONGESTION_TRACK_TTL_SECONDS
                and int(state.get("seen_count", 0)) >= CONGESTION_CONFIRM_FRAMES
            ]
        lane_groups: dict[str, dict[str, Any]] = {}
        junction_groups: dict[str, dict[str, Any]] = {}
        for track in active_tracks:
            region_id = str(track.get("junction_id") or track.get("lane_id") or "")
            if not region_id:
                continue
            target_groups = junction_groups if track.get("junction_id") else lane_groups
            group = target_groups.setdefault(region_id, {"track_ids": set(), "speeds": []})
            group["track_ids"].add(str(track["track_id"]))
            speed = track.get("speed_cm_s")
            if isinstance(speed, (int, float)) and speed >= 0:
                group["speeds"].append(float(speed))

        def build_region_stats(groups: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
            region_stats: dict[str, dict[str, Any]] = {}
            for region_id, group in groups.items():
                track_count = len(group["track_ids"])
                avg_speed = sum(group["speeds"]) / len(group["speeds"]) if group["speeds"] else None
                # A lane with one or two sand-table cars should remain green or
                # amber. Congestion requires several confirmed tracks, rather
                # than repeated detections of the same car.
                count_score = min(1.0, track_count / 4.0)
                speed_score = 0.0 if avg_speed is None else max(0.0, 1.0 - min(avg_speed / 18.0, 1.0))
                score = round(0.85 * count_score + 0.15 * speed_score, 3)
                if score < 0.20:
                    level = "free"
                elif score < 0.42:
                    level = "smooth"
                elif score < 0.62:
                    level = "slow"
                elif score < 0.82:
                    level = "congested"
                else:
                    level = "severe"
                region_stats[region_id] = {
                    "track_count": track_count,
                    "avg_speed_cm_s": round(avg_speed, 2) if avg_speed is not None else None,
                    "score": score,
                    "level": level,
                }
            return region_stats

        lane_stats = build_region_stats(lane_groups)
        junction_stats = build_region_stats(junction_groups)
        vehicles = [
            {
                "camera_id": track["camera_id"],
                "track_id": track["track_id"],
                "x": track["x"],
                "y": track["y"],
                "lane_id": track.get("lane_id"),
                "junction_id": track.get("junction_id"),
                "speed_cm_s": track.get("speed_cm_s"),
                "age_ms": round(max(0.0, now - float(track["last_seen"])) * 1000),
            }
            for track in active_tracks
        ]
        return {
            "camera_id": camera_id,
            "world": self._road.get("world", {"width": 1200, "height": 760, "unit": "cm"}),
            "points": points,
            "point_count": len(points),
            "vehicles": vehicles,
            "active_track_count": len(active_tracks),
            "lane_stats": lane_stats,
            "junction_stats": junction_stats,
        }

    def enrich(self, result: AnalysisResult) -> AnalysisResult:
        camera_id = str(result.camera_id or "")
        matrix = self._homographies.get(camera_id)
        result = result.model_copy(deep=True)
        raw = dict(result.raw or {})
        if matrix is None:
            raw["road_model"] = {
                "projection_ready": False,
                "camera": self._camera_quality.get(camera_id, {"ready": False, "reason": "无相机映射"}),
                "observations": [],
            }
            result.raw = raw
            return result

        source_width = float(result.source_width or CALIBRATION_WIDTH)
        source_height = float(result.source_height or CALIBRATION_HEIGHT)
        now = time.monotonic()
        observations: list[dict[str, Any]] = []
        active_track_keys: set[str] = set()
        illegal_stop_track_ids: list[int | str] = []

        for detection in result.detections:
            class_name = str(detection.class_name).lower().replace("_", "-")
            if class_name not in VEHICLE_CLASSES or detection.predicted:
                continue
            x1, y1, x2, y2 = [float(value) for value in detection.bbox]
            contact_x = ((x1 + x2) / 2.0) * CALIBRATION_WIDTH / max(source_width, 1.0)
            contact_y = y2 * CALIBRATION_HEIGHT / max(source_height, 1.0)
            source = np.float32([[[contact_x, contact_y]]])
            projected = cv2.perspectiveTransform(source, matrix)[0][0]
            world_point = (float(projected[0]), float(projected[1]))
            if not self._inside_world(world_point):
                continue
            lane, distance = self._nearest_lane(world_point)
            on_lane = lane is not None and distance <= float(lane.get("geometry", {}).get("width", 28)) / 2.0 + 6.0
            junction = self._junction_for_point(world_point)
            in_junction = junction is not None
            on_modeled_road = on_lane or in_junction
            observation = {
                "camera_id": camera_id,
                "track_id": detection.track_id,
                "class_name": detection.class_name,
                "confidence": round(float(detection.confidence), 3),
                "bbox": [round(value, 1) for value in detection.bbox],
                "contact_pixel": {"x": round(contact_x, 1), "y": round(contact_y, 1)},
                "world_point": {"x": round(world_point[0], 2), "y": round(world_point[1], 2)},
                "lane_id": lane.get("id") if on_lane and not in_junction and lane else None,
                "lane_name": lane.get("name") if on_lane and not in_junction and lane else None,
                "lane_distance_cm": round(distance, 2),
                "on_traffic_lane": on_lane and not in_junction,
                "junction_id": junction.get("id") if junction else None,
                "junction_name": junction.get("name") if junction else None,
                "in_junction": in_junction,
                "on_modeled_road": on_modeled_road,
            }
            observations.append(observation)
            reliable_for_congestion = self._is_reliable_vehicle_box(detection.bbox)
            observation["reliable_for_congestion"] = reliable_for_congestion
            if on_modeled_road and reliable_for_congestion:
                with self._lock:
                    self._heat_points.append(
                        {
                            "camera_id": camera_id,
                            "track_id": detection.track_id,
                            "x": round(world_point[0], 2),
                            "y": round(world_point[1], 2),
                            "confidence": round(float(detection.confidence), 3),
                            "lane_id": lane.get("id") if on_lane and not in_junction else None,
                            "junction_id": junction.get("id") if junction else None,
                            "speed_cm_s": detection.speed_cm_s,
                            "timestamp": now,
                        }
                    )
                if detection.track_id is not None:
                    track_key = f"{camera_id}:{detection.track_id}"
                    active_track_keys.add(track_key)
                    if reliable_for_congestion:
                        self._update_congestion_track(
                            track_key=track_key,
                            camera_id=camera_id,
                            track_id=detection.track_id,
                            lane_id=str(lane.get("id")) if on_lane and not in_junction else None,
                            junction_id=str(junction.get("id")) if junction else None,
                            world_point=world_point,
                            speed_cm_s=detection.speed_cm_s,
                            now=now,
                        )
                    if on_lane and not in_junction:
                        event = self._update_stop_state(track_key, world_point, now, observation, detection.plate)
                        if event is not None:
                            result.events.append(event)
                            illegal_stop_track_ids.append(detection.track_id)

        with self._lock:
            self._prune(now, active_track_keys)
        raw["road_model"] = {
            "projection_ready": True,
            "camera": self._camera_quality.get(camera_id),
            "observations": observations,
            "illegal_stop_track_ids": illegal_stop_track_ids,
            "no_stopping_policy": {"dwell_seconds": NO_STOP_DWELL_SECONDS, "scope": "traffic_lanes"},
        }
        result.raw = raw
        return result

    def _inside_world(self, point: tuple[float, float]) -> bool:
        world = self._road.get("world", {})
        return 0 <= point[0] <= float(world.get("width", 1200)) and 0 <= point[1] <= float(world.get("height", 760))

    def _nearest_lane(self, point: tuple[float, float]) -> tuple[dict[str, Any] | None, float]:
        nearest = None
        best = float("inf")
        for lane in self._lanes:
            distance = _distance_to_path(point, lane.get("geometry", {}).get("renderPath", []))
            if distance < best:
                nearest, best = lane, distance
        return nearest, best

    def _junction_for_point(self, point: tuple[float, float]) -> dict[str, Any] | None:
        return next((zone for zone in self._junction_zones if _point_in_polygon(point, zone.get("polygon", []))), None)

    @staticmethod
    def _is_reliable_vehicle_box(bbox: list[float] | tuple[float, float, float, float]) -> bool:
        """Reject tiny or implausibly flat detections before they affect traffic state.

        Painted arrows and road markings can occasionally be classified as cars.
        They are often flat, very small boxes and must not change congestion even
        when the detector reports a confident one-frame result.
        """
        x1, y1, x2, y2 = [float(value) for value in bbox]
        width = max(0.0, x2 - x1)
        height = max(0.0, y2 - y1)
        if width < CONGESTION_MIN_BOX_SIDE or height < CONGESTION_MIN_BOX_SIDE:
            return False
        if width * height < CONGESTION_MIN_BOX_AREA:
            return False
        aspect_ratio = width / max(height, 1.0)
        return 0.22 <= aspect_ratio <= CONGESTION_MAX_ASPECT_RATIO

    def _update_congestion_track(
        self,
        *,
        track_key: str,
        camera_id: str,
        track_id: int | str,
        lane_id: str | None,
        junction_id: str | None,
        world_point: tuple[float, float],
        speed_cm_s: float | None,
        now: float,
    ) -> None:
        """Refresh one live vehicle state used by the congestion map."""
        with self._lock:
            state = self._congestion_tracks.get(track_key)
            if state is None or now - float(state.get("last_seen", 0.0)) > CONGESTION_TRACK_TTL_SECONDS:
                self._congestion_tracks[track_key] = {
                    "camera_id": camera_id,
                    "track_id": track_id,
                    "lane_id": lane_id,
                    "junction_id": junction_id,
                    "x": round(world_point[0], 2),
                    "y": round(world_point[1], 2),
                    "speed_cm_s": speed_cm_s,
                    "last_seen": now,
                    "seen_count": 1,
                }
                return
            state.update({
                "lane_id": lane_id,
                "junction_id": junction_id,
                "x": round(world_point[0], 2),
                "y": round(world_point[1], 2),
                "speed_cm_s": speed_cm_s,
                "last_seen": now,
                "seen_count": int(state.get("seen_count", 0)) + 1,
            })

    def _update_stop_state(
        self,
        track_key: str,
        world_point: tuple[float, float],
        now: float,
        observation: dict[str, Any],
        plate: str | None,
    ) -> TrafficEvent | None:
        with self._lock:
            state = self._stop_states.get(track_key)
            if state is None:
                self._stop_states[track_key] = {
                    "point": world_point,
                    "stationary_since": now,
                    "last_seen": now,
                    "alerted": False,
                }
                return None
            distance = math.hypot(world_point[0] - state["point"][0], world_point[1] - state["point"][1])
            state["last_seen"] = now
            if distance > 6.0:
                state["point"] = world_point
                state["stationary_since"] = now
                state["alerted"] = False
                return None
            dwell = now - float(state["stationary_since"])
            if dwell < NO_STOP_DWELL_SECONDS:
                return None
            if state.get("alerted"):
                return None
            state["alerted"] = True
        identity = plate or f"目标 {track_key.rsplit(':', 1)[-1]}"
        return TrafficEvent(
            type="illegal_stop",
            severity="warning",
            description=f"{identity} 在 {observation['lane_name']} 持续停留 {dwell:.1f} 秒，触发禁停告警。",
            camera_id=observation["camera_id"],
            bbox=observation["bbox"],
        )

    def _prune(self, now: float, active_track_keys: set[str] | None = None) -> None:
        while self._heat_points and now - float(self._heat_points[0]["timestamp"]) > HEAT_TTL_SECONDS:
            self._heat_points.popleft()
        expired = [
            key
            for key, state in self._stop_states.items()
            if now - float(state.get("last_seen", 0)) > 3.0 and (active_track_keys is None or key not in active_track_keys)
        ]
        for key in expired:
            self._stop_states.pop(key, None)
        expired_congestion = [
            key
            for key, state in self._congestion_tracks.items()
            if now - float(state.get("last_seen", 0.0)) > CONGESTION_TRACK_TTL_SECONDS
        ]
        for key in expired_congestion:
            self._congestion_tracks.pop(key, None)


road_logic_service = RoadLogicService()
