from __future__ import annotations

import math
import re
import time
from datetime import datetime
from numbers import Real
from pathlib import Path
from typing import Any, Callable, Generator

import cv2
import numpy as np
import torch
from ultralytics import YOLO

from app.schemas.dashboard import AnalysisResult, DetectionBox, TrafficEvent, TrafficStats
from app.services.whitelist import WhitelistDecision, decide_plate


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
AUTO_MODEL = DATA_DIR / "yolo11s.pt"
VISDRONE_MODEL = DATA_DIR / "yolov11s-visdrone.pt"
BYTETRACK_CONFIG = DATA_DIR / "bytetrack_sandtable.yaml"
PLATE_PATTERN = re.compile(r"^[\u4e00-\u9fa5][A-Z][A-Z0-9]{5,6}$")
PLATE_PREFIX_FIXES = {
    "äº¬": "京",
    "žŠ": "京",
}

VEHICLE_CLASS_NAMES = {
    "car",
    "van",
    "truck",
    "bus",
    "motorcycle",
    "motorbike",
    "motor",
    "tricycle",
    "awning-tricycle",
    "bicycle",
}

PERSON_CLASS_NAMES = {
    "person",
    "pedestrian",
    "people",
}

# The live3 road trapezoid was measured on the sandtable as 40 cm x 70 cm.
# Points are normalized from the original 1920 x 1080 frame so the calibration
# remains valid when the stream resolution changes.
REFERENCE_CAMERA_ID = "live3"
CALIBRATION_IMAGE_POINTS = np.float32(
    [
        [580 / 1920, 115 / 1080],
        [1145 / 1920, 115 / 1080],
        [1480 / 1920, 890 / 1080],
        [245 / 1920, 890 / 1080],
    ]
)
CALIBRATION_WORLD_POINTS_CM = np.float32(
    [
        [0.0, 0.0],
        [40.0, 0.0],
        [40.0, 70.0],
        [0.0, 70.0],
    ]
)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def is_vehicle_class(class_name: str) -> bool:
    return class_name.lower().replace("_", "-") in VEHICLE_CLASS_NAMES


def is_person_class(class_name: str) -> bool:
    return class_name.lower().replace("_", "-") in PERSON_CLASS_NAMES


def road_roi_polygon(camera_id: str, width: int, height: int) -> np.ndarray:
    """Return the drivable area used to suppress roadside false positives."""
    if camera_id == REFERENCE_CAMERA_ID:
        return np.array(
            [
                [int(width * 0.30), int(height * 0.11)],
                [int(width * 0.60), int(height * 0.11)],
                [int(width * 0.77), int(height * 0.82)],
                [int(width * 0.13), int(height * 0.82)],
            ],
            dtype=np.int32,
        )
    return np.array(
        [
            [int(width * 0.14), int(height * 0.07)],
            [int(width * 0.86), int(height * 0.07)],
            [int(width * 0.96), int(height * 0.96)],
            [int(width * 0.04), int(height * 0.96)],
        ],
        dtype=np.int32,
    )


def is_box_on_road(camera_id: str, bbox: list[int], width: int, height: int) -> bool:
    # The lower centre is a better road-contact point than the box centre for
    # perspective views, where a vehicle body can extend beyond the lane edge.
    x1, y1, x2, y2 = bbox
    contact_point = ((x1 + x2) / 2.0, y1 + (y2 - y1) * 0.82)
    polygon = road_roi_polygon(camera_id, width, height)
    polygon_float = polygon.astype(np.float32)
    if cv2.pointPolygonTest(polygon_float, contact_point, False) >= 0:
        return True
    # A close vehicle can be clipped by the lower frame boundary, placing its
    # synthetic contact point below the calibrated trapezoid even though the
    # visible body is clearly inside the lane. Use the centre only for these
    # boundary-clipped boxes; ordinary roadside boxes still require road contact.
    if y2 >= int(height * 0.95):
        center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
        return cv2.pointPolygonTest(polygon_float, center, False) >= 0
    return False


def clamp_box(box: list[int], width: int, height: int) -> list[int]:
    x1, y1, x2, y2 = box
    return [
        max(0, min(width - 1, x1)),
        max(0, min(height - 1, y1)),
        max(0, min(width - 1, x2)),
        max(0, min(height - 1, y2)),
    ]


def box_iou(a: list[int], b: list[int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1, inter_y1 = max(ax1, bx1), max(ay1, by1)
    inter_x2, inter_y2 = min(ax2, bx2), min(ay2, by2)
    inter_area = max(0, inter_x2 - inter_x1) * max(0, inter_y2 - inter_y1)
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter_area
    return inter_area / union if union else 0.0


def box_area(box: list[int]) -> int:
    x1, y1, x2, y2 = box
    return max(0, x2 - x1) * max(0, y2 - y1)


def box_overlap_of_smaller(a: list[int], b: list[int]) -> float:
    """Return the fraction of the smaller box covered by the other box."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    intersection = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
    smaller_area = min(box_area(a), box_area(b))
    return intersection / smaller_area if smaller_area else 0.0


def vehicle_visual_features(crop: np.ndarray) -> dict[str, float]:
    """Return inexpensive appearance evidence for a detector vehicle box.

    Smooth sandtable props such as an eraser can occasionally receive a weak
    COCO ``car`` label. Real model vehicles contain windows, racks, tyres and
    plate edges, so their crops retain noticeably more local structure even
    when the detector confidence is modest.
    """
    if crop.size == 0:
        return {"edge_density": 0.0, "contrast": 0.0, "entropy": 0.0}
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    max_side = max(gray.shape[:2])
    if max_side > 320:
        scale = 320.0 / max_side
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    edges = cv2.Canny(gray, 55, 145)
    histogram = cv2.calcHist([gray], [0], None, [32], [0, 256]).reshape(-1)
    probabilities = histogram / max(float(histogram.sum()), 1.0)
    probabilities = probabilities[probabilities > 0]
    entropy = float(-np.sum(probabilities * np.log2(probabilities)))
    return {
        "edge_density": float(np.count_nonzero(edges) / max(edges.size, 1)),
        "contrast": float(np.std(gray)),
        "entropy": entropy,
    }


def likely_same_vehicle_box(a: list[int], b: list[int]) -> bool:
    """Match duplicate detector/tracker boxes without merging queued cars."""
    if box_iou(a, b) >= 0.42 or box_overlap_of_smaller(a, b) >= 0.64:
        return True
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    aw, ah = max(1, ax2 - ax1), max(1, ay2 - ay1)
    bw, bh = max(1, bx2 - bx1), max(1, by2 - by1)
    area_ratio = max(aw * ah, bw * bh) / max(1, min(aw * ah, bw * bh))
    if area_ratio > 3.2:
        return False
    horizontal_overlap = max(0, min(ax2, bx2) - max(ax1, bx1)) / min(aw, bw)
    center_distance = math.hypot((ax1 + ax2 - bx1 - bx2) / 2, (ay1 + ay2 - by1 - by2) / 2)
    # A duplicate box tends to share the same lane centre and has only a small
    # vertical offset. Adjacent queued cars are normally farther apart.
    return horizontal_overlap >= 0.62 and center_distance <= min(ah, bh) * 0.46


def suppress_duplicate_vehicle_detections(detections: list[DetectionBox]) -> list[DetectionBox]:
    """Keep one target when detector and plate fallback describe the same car."""
    kept: list[DetectionBox] = []
    vehicles = [item for item in detections if is_vehicle_class(item.class_name) or "vehicle" in item.class_name]
    others = [item for item in detections if item not in vehicles]

    def priority(item: DetectionBox) -> tuple[int, int, int, float, float]:
        return (
            int(item.track_id is not None),
            int(bool(item.plate)),
            int(not item.predicted),
            float(item.confidence),
            float(box_area([int(value) for value in item.bbox])),
        )

    for candidate in sorted(vehicles, key=priority, reverse=True):
        candidate_box = [int(value) for value in candidate.bbox]
        duplicate_index = None
        for index, existing in enumerate(kept):
            existing_box = [int(value) for value in existing.bbox]
            same_plate = bool(candidate.plate and existing.plate and candidate.plate == existing.plate)
            same_track = candidate.track_id is not None and candidate.track_id == existing.track_id
            heavily_overlapped = likely_same_vehicle_box(candidate_box, existing_box)
            # Plate-derived boxes intentionally surround a plate. A tracked
            # vehicle that contains that plate must win, even when their IoU is
            # low because one box is much tighter than the other.
            if same_track or same_plate or heavily_overlapped:
                duplicate_index = index
                break
        if duplicate_index is None:
            kept.append(candidate)
        elif priority(candidate) > priority(kept[duplicate_index]):
            kept[duplicate_index] = candidate

    return others + kept


def plate_belongs_to_vehicle(plate_box: list[int], vehicle_box: list[int]) -> bool:
    px1, py1, px2, py2 = plate_box
    vx1, vy1, vx2, vy2 = vehicle_box
    center_x = (px1 + px2) / 2
    center_y = (py1 + py2) / 2
    margin_x = max(4, int((vx2 - vx1) * 0.08))
    margin_y = max(4, int((vy2 - vy1) * 0.08))
    return (
        vx1 - margin_x <= center_x <= vx2 + margin_x
        and vy1 - margin_y <= center_y <= vy2 + margin_y
    )


def plate_to_vehicle_box(plate_box: list[int], image_shape: tuple[int, int, int]) -> list[int]:
    height, width = image_shape[:2]
    x1, y1, x2, y2 = plate_box
    plate_w = max(1, x2 - x1)
    plate_h = max(1, y2 - y1)
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    vehicle_w = int(plate_w * 3.8)
    vehicle_h = int(plate_h * 5.2)
    return clamp_box(
        [
            cx - vehicle_w // 2,
            cy - int(vehicle_h * 0.62),
            cx + vehicle_w // 2,
            cy + int(vehicle_h * 0.38),
        ],
        width,
        height,
    )


def draw_label(image: np.ndarray, box: list[int], label: str, color: tuple[int, int, int]) -> None:
    x1, y1, x2, y2 = box
    cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
    cv2.putText(
        image,
        label,
        (x1, max(20, y1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        color,
        2,
        cv2.LINE_AA,
    )


def fix_plate_text(text: str) -> str:
    for broken, fixed in PLATE_PREFIX_FIXES.items():
        if text.startswith(broken):
            return fixed + text[len(broken):]
    return text


def whitelist_event(camera_id: str, bbox: list[int], plate_text: str, allowed: bool) -> TrafficEvent:
    return TrafficEvent(
        type="whitelist_pass" if allowed else "whitelist_block",
        severity="info" if allowed else "warning",
        description=f"白名单车辆 {plate_text}，可通过" if allowed else f"非白名单车辆 {plate_text}，建议拦截",
        camera_id=camera_id,
        bbox=[float(v) for v in bbox],
    )


class LocalModelService:
    def __init__(self) -> None:
        self._models: dict[str, YOLO] = {}
        self._device = "0" if torch.cuda.is_available() else "cpu"
        self._device_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
        self._plate_catcher: Any | None = None
        self._plate_error: str | None = None
        self._frame_id = 0
        self._last_stream_plates: dict[str, list[dict[str, Any]]] = {}
        self._stream_frame_ids: dict[str, int] = {}
        self._vehicle_gate_memory: dict[str, dict[str, Any]] = {}
        self._track_plate_memory: dict[str, dict[str, Any]] = {}
        self._track_motion_memory: dict[str, dict[str, Any]] = {}
        self._calibration_cache: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
        self._view_mode_memory: dict[str, dict[str, Any]] = {}
        self._visual_track_memory: dict[str, dict[str, Any]] = {}
        self._vehicle_count_history: dict[str, list[int]] = {}

    def health(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "mode": "local_sandtable_model",
            "models": {
                "auto": AUTO_MODEL.exists(),
                "visdrone": VISDRONE_MODEL.exists(),
            },
            "device": "cuda:0" if self._device != "cpu" else "cpu",
            "device_name": self._device_name,
            "plate": "ready" if self._plate_error is None else self._plate_error,
        }

    def _model_path(self, model_name: str = "auto") -> Path:
        if model_name == "visdrone" and VISDRONE_MODEL.exists():
            return VISDRONE_MODEL
        if AUTO_MODEL.exists():
            return AUTO_MODEL
        if VISDRONE_MODEL.exists():
            return VISDRONE_MODEL
        raise RuntimeError("No local YOLO weights found in backend/data.")

    def _load_model(self, model_name: str = "auto") -> YOLO:
        path = self._model_path(model_name)
        key = str(path.resolve())
        if key not in self._models:
            self._models[key] = YOLO(str(path))
        return self._models[key]

    def _load_plate_catcher(self) -> Any | None:
        if self._plate_catcher is not None or self._plate_error is not None:
            return self._plate_catcher
        try:
            import hyperlpr3 as lpr3

            self._plate_catcher = lpr3.LicensePlateCatcher()
        except Exception as exc:  # noqa: BLE001 - surfaced in health endpoint
            self._plate_error = str(exc)
        return self._plate_catcher

    def _normalize_plates(self, raw: Any) -> list[dict[str, Any]]:
        plates: list[dict[str, Any]] = []
        if not raw:
            return plates
        for item in raw:
            text = ""
            confidence = 0.0
            bbox: list[int] | None = None
            plate_type = ""
            if isinstance(item, (list, tuple)):
                text = fix_plate_text(str(item[0])) if len(item) > 0 else ""
                # HyperLPR returns ``numpy.float32``.  Restricting this check to
                # Python int/float silently turned a 0.99 OCR result into 0.0,
                # forcing every clear plate to wait for a second observation.
                confidence = float(item[1]) if len(item) > 1 and isinstance(item[1], Real) else 0.0
                if len(item) > 2 and isinstance(item[2], (list, tuple)):
                    bbox = [int(v) for v in item[2][:4]]
                elif len(item) > 2:
                    plate_type = str(item[2])
                if len(item) > 3 and isinstance(item[3], (list, tuple)):
                    bbox = [int(v) for v in item[3][:4]]
                elif len(item) > 3:
                    plate_type = str(item[3])
            else:
                text = fix_plate_text(str(item))
            if PLATE_PATTERN.match(text):
                plates.append({"text": text, "confidence": confidence, "bbox": bbox, "type": plate_type})
        return plates

    def detect_plates(self, frame: np.ndarray, upscale_small: bool = False) -> list[dict[str, Any]]:
        catcher = self._load_plate_catcher()
        if catcher is None:
            return []
        if frame.size == 0:
            return []

        def recognize(image: np.ndarray, scale: float = 1.0) -> list[dict[str, Any]]:
            try:
                plates = self._normalize_plates(catcher(image))
                if scale != 1.0:
                    for plate in plates:
                        if plate.get("bbox"):
                            plate["bbox"] = [int(round(value / scale)) for value in plate["bbox"]]
                return plates
            except Exception:
                return []

        scale = 1.0
        inference_frame = frame
        # Vehicle crops in the sandtable can be sharp enough for detection but
        # still too small for OCR. Prefer a larger OCR target than the general
        # detector needs, while keeping the expensive path crop-only.
        if upscale_small and frame.shape[1] < 480:
            scale = min(4.0, max(2.0, 480.0 / max(1, frame.shape[1])))
            inference_frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        plates = recognize(inference_frame, scale)
        if plates:
            return plates

        # A reflective blue plate may lose contrast in the original crop.
        # Retry once with luminance-only enhancement instead of lowering the
        # confirmation rule and risking a wrong whitelist decision.
        lab = cv2.cvtColor(inference_frame, cv2.COLOR_BGR2LAB)
        lightness, channel_a, channel_b = cv2.split(lab)
        enhanced_lightness = cv2.createCLAHE(clipLimit=2.4, tileGridSize=(6, 6)).apply(lightness)
        enhanced = cv2.cvtColor(cv2.merge((enhanced_lightness, channel_a, channel_b)), cv2.COLOR_LAB2BGR)
        sharpened = cv2.addWeighted(enhanced, 1.35, cv2.GaussianBlur(enhanced, (0, 0), 1.1), -0.35, 0)
        return recognize(sharpened, scale)

    def _detect_vehicle_crop_plate(self, crop: np.ndarray) -> list[dict[str, Any]]:
        if crop.size == 0:
            return []
        # A detector box includes roof racks, windshields and shadows. On the
        # sandtable the rear plate sits in the centre-lower area, so collect
        # OCR hypotheses from several plausible plate bands instead of taking
        # the first full-car result (which can be a confident-looking wrong
        # string).
        height, width = crop.shape[:2]
        regions = [
            (crop[int(height * 0.30):int(height * 0.98), int(width * 0.02):int(width * 0.98)], 1.30),
            (crop[int(height * 0.38):int(height * 0.84), int(width * 0.04):int(width * 0.96)], 1.15),
            (crop, 1.00),
        ]
        votes: dict[str, dict[str, Any]] = {}
        for region, weight in regions:
            if region.size == 0:
                continue
            for candidate in self.detect_plates(region, upscale_small=True):
                text = str(candidate.get("text", ""))
                if not text:
                    continue
                current = votes.setdefault(
                    text,
                    {**candidate, "_vote_score": 0.0, "_vote_count": 0},
                )
                current["_vote_score"] += weight
                current["_vote_count"] += 1
                if float(candidate.get("confidence", 0.0)) > float(current.get("confidence", 0.0)):
                    current.update(candidate)
        if not votes:
            return []
        return sorted(
            votes.values(),
            key=lambda item: (
                float(item.get("_vote_score", 0.0)),
                int(item.get("_vote_count", 0)),
                float(item.get("confidence", 0.0)),
            ),
            reverse=True,
        )

    def _memory_key(self, camera_id: str, track_id: int | None, bbox: list[int]) -> str:
        if track_id is not None:
            return f"{camera_id}:track:{track_id}"
        x1, y1, x2, y2 = bbox
        cx = int((x1 + x2) / 2 / 80)
        cy = int((y1 + y2) / 2 / 80)
        return f"{camera_id}:cell:{cx}:{cy}"

    def clear_gate_memory(self, plate_no: str | None = None) -> None:
        if not plate_no:
            self._vehicle_gate_memory.clear()
            self._track_plate_memory.clear()
            return
        normalized = decide_plate(plate_no, 1.0).plate_no or plate_no
        self._vehicle_gate_memory = {
            key: value
            for key, value in self._vehicle_gate_memory.items()
            if getattr(value.get("decision"), "plate_no", None) != normalized
        }
        self._track_plate_memory = {
            key: value
            for key, value in self._track_plate_memory.items()
            if (value.get("confirmed") or {}).get("text") != normalized
        }

    def _stable_track_plate(
        self,
        camera_id: str,
        bbox: list[int],
        track_id: int | None,
        crop: np.ndarray,
        stream_mode: bool,
        frame_counter: int,
        allow_ocr: bool = True,
    ) -> dict[str, Any] | None:
        key = self._memory_key(camera_id, track_id, bbox)
        state = self._track_plate_memory.setdefault(
            key,
            {"last_run": -100, "observations": [], "confirmed": None, "latest": None, "expires_at": 0, "candidate_expires_at": 0},
        )
        interval = 2 if stream_mode else 1
        should_run = allow_ocr and crop.size and frame_counter - int(state["last_run"]) >= interval
        if should_run:
            state["last_run"] = frame_counter
            candidates = self._detect_vehicle_crop_plate(crop)
            if candidates:
                candidate = max(
                    candidates,
                    key=lambda item: (
                        float(item.get("_vote_score", 0.0)),
                        int(item.get("_vote_count", 0)),
                        float(item.get("confidence", 0.0)),
                    ),
                )
                state["latest"] = candidate
                state["candidate_expires_at"] = frame_counter + 6
                observations = state["observations"]
                observations.append(candidate)
                del observations[:-6]
                same = [item for item in observations if item["text"] == candidate["text"]]
                best = max(same, key=lambda item: float(item.get("confidence", 0.0)))
                # A clear first reading may be accepted immediately. Once a
                # track owns a confirmed plate, however, one occluded/glared
                # frame must not replace it with a look-alike character.
                if len(same) >= 2 or (state.get("confirmed") is None and float(best.get("confidence", 0.0)) >= 0.88):
                    state["confirmed"] = best
                    state["expires_at"] = frame_counter + 75

        confirmed = state.get("confirmed")
        if confirmed and int(state.get("expires_at", 0)) >= frame_counter:
            return {**confirmed, "provisional": False}
        latest = state.get("latest")
        if latest and int(state.get("candidate_expires_at", 0)) >= frame_counter:
            # Show a valid OCR result immediately, but leave whitelist policy
            # undecided until it has been confirmed across frames.
            return {**latest, "provisional": True}
        return None

    def _prune_plate_memory(self, camera_id: str, frame_counter: int) -> None:
        prefix = f"{camera_id}:"
        self._track_plate_memory = {
            key: value
            for key, value in self._track_plate_memory.items()
            if not key.startswith(prefix)
            or int(value.get("expires_at", 0)) >= frame_counter
            or frame_counter - int(value.get("last_run", 0)) < 150
        }

    def _calibration(self, frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        height, width = frame.shape[:2]
        cache_key = (width, height)
        if cache_key not in self._calibration_cache:
            image_points = CALIBRATION_IMAGE_POINTS * np.float32([width, height])
            matrix = cv2.getPerspectiveTransform(image_points, CALIBRATION_WORLD_POINTS_CM)
            self._calibration_cache[cache_key] = (matrix, image_points)
        return self._calibration_cache[cache_key]

    def _track_speed_cm_s(
        self,
        camera_id: str,
        track_id: int | None,
        bbox: list[int],
        frame: np.ndarray,
        observed_at: float,
    ) -> float | None:
        if track_id is None:
            return None
        matrix, roi = self._calibration(frame)
        foot_point = np.float32([[(bbox[0] + bbox[2]) / 2.0, bbox[3]]])
        if cv2.pointPolygonTest(roi, tuple(foot_point[0]), False) < 0:
            return None
        world_point = cv2.perspectiveTransform(foot_point.reshape(1, 1, 2), matrix)[0, 0]
        key = f"{camera_id}:track:{track_id}"
        state = self._track_motion_memory.get(key)
        if state is None:
            self._track_motion_memory[key] = {
                "position": world_point,
                "image_position": foot_point[0],
                "observed_at": observed_at,
                "last_seen": observed_at,
                "samples": [],
                "speed": None,
                "stationary_hits": 0,
            }
            return None

        state["last_seen"] = observed_at
        elapsed = observed_at - float(state["observed_at"])
        if elapsed < 0.25:
            return state.get("speed")

        pixel_distance = float(np.linalg.norm(foot_point[0] - state["image_position"]))
        box_width = max(1, bbox[2] - bbox[0])
        box_height = max(1, bbox[3] - bbox[1])
        pixel_dead_zone = max(4.0, min(10.0, np.hypot(box_width, box_height) * 0.04))
        distance_cm = float(np.linalg.norm(world_point - state["position"]))
        is_stationary = pixel_distance < pixel_dead_zone or distance_cm < 1.5
        raw_speed = 0.0 if is_stationary else distance_cm / elapsed
        state["position"] = world_point
        state["image_position"] = foot_point[0]
        state["observed_at"] = observed_at
        if raw_speed > 200.0:
            return state.get("speed")

        samples = state["samples"]
        samples.append(raw_speed)
        del samples[:-5]
        state["stationary_hits"] = int(state.get("stationary_hits", 0)) + 1 if is_stationary else 0
        stable_speed = float(np.median(np.asarray(samples, dtype=np.float32)))
        if state["stationary_hits"] >= 2 or sum(value == 0.0 for value in samples[-3:]) >= 2:
            stable_speed = 0.0
        state["speed"] = round(stable_speed, 1)
        return state["speed"]

    def _prune_motion_memory(self, observed_at: float) -> None:
        self._track_motion_memory = {
            key: value
            for key, value in self._track_motion_memory.items()
            if observed_at - float(value.get("last_seen", 0.0)) < 5.0
        }

    def _stable_vehicle_count(self, camera_id: str, current_count: int) -> int:
        history = self._vehicle_count_history.setdefault(camera_id, [])
        history.append(current_count)
        del history[:-5]
        median_count = int(round(float(np.median(np.asarray(history, dtype=np.float32)))))
        # New vehicles must appear on the dashboard immediately. Keep the
        # median only on count decreases so one missed detector frame does not
        # make a stable vehicle disappear and reappear.
        return max(current_count, median_count)

    def _smooth_visual_box(
        self,
        camera_id: str,
        track_id: int | None,
        bbox: list[int],
        frame_counter: int,
        width: int,
        height: int,
    ) -> list[int]:
        if track_id is None:
            return bbox
        key = f"{camera_id}:track:{track_id}"
        current = np.asarray(bbox, dtype=np.float32)
        state = self._visual_track_memory.get(key)
        if state is None:
            self._visual_track_memory[key] = {
                "bbox": current,
                "velocity": np.zeros(4, dtype=np.float32),
                "last_frame": frame_counter,
                "metadata": {},
            }
            return bbox

        gap = max(1, frame_counter - int(state["last_frame"]))
        previous = state["bbox"]
        if float(np.max(np.abs(current - previous))) < 3.0:
            state["velocity"] *= 0.25
            corrected = current * 0.75 + previous * 0.25
            state["bbox"] = corrected
            state["last_frame"] = frame_counter
            return clamp_box([int(round(value)) for value in corrected], width, height)
        prediction = previous + state["velocity"] * gap
        corrected = current * 0.72 + prediction * 0.28
        measured_velocity = (corrected - previous) / gap
        state["velocity"] = state["velocity"] * 0.65 + measured_velocity * 0.35
        smoothed = corrected + state["velocity"] * 0.25
        state["bbox"] = corrected
        state["last_frame"] = frame_counter
        return clamp_box([int(round(value)) for value in smoothed], width, height)

    def _remember_visual_metadata(
        self,
        camera_id: str,
        track_id: int | None,
        **metadata: Any,
    ) -> None:
        if track_id is None:
            return
        state = self._visual_track_memory.get(f"{camera_id}:track:{track_id}")
        if state is not None:
            previous = dict(state.get("metadata") or {})
            observed_hits = int(previous.get("observed_hits", 0)) + 1
            state["metadata"] = {
                **previous,
                **metadata,
                "observed_hits": observed_hits,
                "credible_vehicle": bool(metadata.get("credible_vehicle", previous.get("credible_vehicle", False))),
            }

    def _visual_vehicle_is_credible(
        self,
        camera_id: str,
        track_id: int | None,
        crop: np.ndarray,
        bbox: list[int],
        frame_shape: tuple[int, int, int],
        confidence: float,
        plate_text: str | None = None,
    ) -> tuple[bool, dict[str, float]]:
        features = vehicle_visual_features(crop)
        height, width = frame_shape[:2]
        area_ratio = box_area(bbox) / max(float(width * height), 1.0)
        features["area_ratio"] = area_ratio
        state = self._visual_track_memory.get(f"{camera_id}:track:{track_id}") if track_id is not None else None
        metadata = dict((state or {}).get("metadata") or {})
        if plate_text or metadata.get("credible_vehicle"):
            return True, features

        edge_density = features["edge_density"]
        contrast = features["contrast"]
        entropy = features["entropy"]
        # Large, partly occluded near-field vehicles remain credible despite a
        # soft crop. Compact objects need stronger internal structure.
        if area_ratio >= 0.035 and contrast >= 25.0 and edge_density >= 0.022:
            return True, features
        if confidence >= 0.48 and contrast >= 23.0 and edge_density >= 0.032:
            return True, features
        if area_ratio >= 0.010:
            return edge_density >= 0.052 and contrast >= 24.0 and entropy >= 3.2, features
        return edge_density >= 0.075 and contrast >= 23.0 and entropy >= 3.25, features

    def _recover_visual_track_id(
        self,
        camera_id: str,
        bbox: list[int],
        seen_track_ids: set[int],
        frame_counter: int,
    ) -> int | None:
        prefix = f"{camera_id}:track:"
        best_track_id = None
        best_iou = 0.0
        for key, state in self._visual_track_memory.items():
            if not key.startswith(prefix):
                continue
            track_id = int(key.rsplit(":", 1)[-1])
            if track_id in seen_track_ids:
                continue
            missing = frame_counter - int(state["last_frame"])
            metadata = dict(state.get("metadata") or {})
            max_missing = 9 if metadata.get("plate") else 7 if metadata.get("credible_vehicle") else 3
            if missing < 1 or missing > max_missing:
                continue
            predicted_box = state["bbox"] + state["velocity"] * missing
            score = box_iou(
                bbox,
                [int(round(value)) for value in predicted_box],
            )
            if score > best_iou:
                best_iou = score
                best_track_id = track_id
        return best_track_id if best_iou >= 0.2 else None

    def _predicted_visual_tracks(
        self,
        camera_id: str,
        seen_track_ids: set[int],
        frame_counter: int,
        width: int,
        height: int,
        max_missing_frames: int = 7,
    ) -> list[dict[str, Any]]:
        prefix = f"{camera_id}:track:"
        predicted: list[dict[str, Any]] = []
        expired: list[str] = []
        for key, state in self._visual_track_memory.items():
            if not key.startswith(prefix):
                continue
            track_id = int(key.rsplit(":", 1)[-1])
            if track_id in seen_track_ids:
                continue
            missing = frame_counter - int(state["last_frame"])
            if missing <= 0:
                continue
            metadata = dict(state.get("metadata") or {})
            allowed_missing = 9 if metadata.get("plate") else max_missing_frames if metadata.get("credible_vehicle") else 3
            if missing > allowed_missing:
                if missing > 30:
                    expired.append(key)
                continue
            bbox = state["bbox"] + state["velocity"] * missing
            predicted.append(
                {
                    "track_id": track_id,
                    "bbox": clamp_box([int(round(value)) for value in bbox], width, height),
                    "confidence_decay": 0.91**missing,
                    **metadata,
                }
            )
        for key in expired:
            self._visual_track_memory.pop(key, None)
        return predicted

    def _auto_small_target_mode(
        self,
        camera_id: str,
        frame: np.ndarray,
        model: YOLO,
        frame_counter: int,
    ) -> bool:
        height, width = frame.shape[:2]
        if not camera_id.startswith("custom") or width / max(1, height) < 1.5:
            return False

        state = self._view_mode_memory.setdefault(
            camera_id,
            {"mode": "far", "last_probe": -100, "near_votes": 0, "far_votes": 0},
        )
        if frame_counter - int(state["last_probe"]) < 20:
            return state["mode"] == "far"

        state["last_probe"] = frame_counter
        probe = model.predict(
            frame,
            conf=0.15,
            imgsz=640,
            verbose=False,
            device=self._device,
        )[0]
        frame_area = float(width * height)
        large_vehicle_found = False
        if probe.boxes is not None and len(probe.boxes) > 0:
            probe_boxes = probe.boxes.xyxy.cpu().numpy()
            probe_classes = probe.boxes.cls.cpu().numpy().astype(int)
            for box, cls_id in zip(probe_boxes, probe_classes):
                class_name = probe.names.get(int(cls_id), str(cls_id))
                if not is_vehicle_class(class_name):
                    continue
                x1, y1, x2, y2 = box
                if max(0.0, x2 - x1) * max(0.0, y2 - y1) / frame_area >= 0.015:
                    large_vehicle_found = True
                    break

        if large_vehicle_found:
            state["near_votes"] += 1
            state["far_votes"] = 0
            if state["near_votes"] >= 1:
                state["mode"] = "near"
        else:
            state["far_votes"] += 1
            state["near_votes"] = 0
            if state["far_votes"] >= 2 or frame_counter == 1:
                state["mode"] = "far"
        return state["mode"] == "far"

    def _reset_camera_tracking_memory(self, camera_id: str, model: YOLO) -> None:
        prefix = f"{camera_id}:"
        self._track_plate_memory = {
            key: value for key, value in self._track_plate_memory.items() if not key.startswith(prefix)
        }
        self._track_motion_memory = {
            key: value for key, value in self._track_motion_memory.items() if not key.startswith(prefix)
        }
        self._vehicle_gate_memory = {
            key: value for key, value in self._vehicle_gate_memory.items() if not key.startswith(prefix)
        }
        self._visual_track_memory = {
            key: value for key, value in self._visual_track_memory.items() if not key.startswith(prefix)
        }
        self._vehicle_count_history.pop(camera_id, None)
        predictor = getattr(model, "predictor", None)
        for tracker in getattr(predictor, "trackers", []) or []:
            reset = getattr(tracker, "reset", None)
            if callable(reset):
                reset()

    def _stable_decision(
        self,
        camera_id: str,
        bbox: list[int],
        track_id: int | None,
        plate_text: str | None,
        confidence: float,
    ) -> WhitelistDecision | None:
        key = self._memory_key(camera_id, track_id, bbox)
        remembered = self._vehicle_gate_memory.get(key)
        if plate_text:
            decision = decide_plate(plate_text, confidence)
            if decision.whitelist_status:
                self._vehicle_gate_memory[key] = {
                    "decision": decision,
                    "bbox": bbox,
                    "expires_at": self._frame_id + 45,
                }
                return decision
            if remembered and remembered.get("expires_at", 0) >= self._frame_id:
                old_box = remembered.get("bbox") or bbox
                if box_iou(old_box, bbox) > 0.2 or track_id is not None:
                    return remembered["decision"]
            return decision
        if remembered and remembered.get("expires_at", 0) >= self._frame_id:
            old_box = remembered.get("bbox") or bbox
            if box_iou(old_box, bbox) > 0.2 or track_id is not None:
                return remembered["decision"]
        return None

    def infer_jpeg(
        self,
        camera_id: str,
        jpeg: bytes,
        model_name: str = "auto",
        conf: float = 0.30,
        imgsz: int = 1280,
        annotate: bool = False,
        stream_mode: bool = False,
        include_people: bool = False,
        fast_entry_recovery: bool = False,
    ) -> tuple[AnalysisResult, bytes | None]:
        data = np.frombuffer(jpeg, np.uint8)
        frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if frame is None:
            return AnalysisResult(timestamp=now_iso(), camera_id=camera_id, error="Invalid JPEG frame."), None
        return self.infer_frame(
            camera_id,
            frame,
            model_name=model_name,
            conf=conf,
            imgsz=imgsz,
            annotate=annotate,
            stream_mode=stream_mode,
            include_people=include_people,
            fast_entry_recovery=fast_entry_recovery,
        )

    def infer_frame(
        self,
        camera_id: str,
        frame: np.ndarray,
        model_name: str = "auto",
        conf: float = 0.30,
        imgsz: int = 1280,
        annotate: bool = False,
        stream_mode: bool = False,
        include_people: bool = False,
        fast_entry_recovery: bool = False,
    ) -> tuple[AnalysisResult, bytes | None]:
        self._frame_id += 1
        frame_counter = self._stream_frame_ids.get(camera_id, 0) + 1
        self._stream_frame_ids[camera_id] = frame_counter
        started = time.perf_counter()
        model = self._load_model(model_name)
        height, width = frame.shape[:2]
        previous_view_mode = (self._view_mode_memory.get(camera_id) or {}).get("mode")
        small_target_mode = self._auto_small_target_mode(camera_id, frame, model, frame_counter)
        current_view_mode = "far" if small_target_mode else "near"
        if previous_view_mode and previous_view_mode != current_view_mode:
            self._reset_camera_tracking_memory(camera_id, model)
        roi_x1 = int(width * 0.22) if small_target_mode else 0
        roi_x2 = int(width * 0.55) if small_target_mode else width
        inference_frame = frame[:, roi_x1:roi_x2] if small_target_mode else frame
        inference_size = max(imgsz, 960) if small_target_mode else imgsz
        detector_confidence = (
            min(conf, 0.08)
            if small_target_mode
            else min(conf, 0.10 if fast_entry_recovery else 0.18)
        )
        results = model.track(
            inference_frame,
            # The sandtable vehicles are often partly hidden by model trees or
            # another queued car. Keep detector recall high, then let the road,
            # appearance and temporal gates below reject weak false positives.
            conf=detector_confidence,
            imgsz=inference_size,
            tracker=str(BYTETRACK_CONFIG),
            persist=True,
            agnostic_nms=True,
            verbose=False,
            device=self._device,
        )
        result = results[0]
        observed_at = time.monotonic()
        detections: list[DetectionBox] = []
        events: list[TrafficEvent] = []
        vehicle_boxes: list[list[int]] = []
        measured_speeds: list[float] = []
        seen_track_ids: set[int] = set()
        unresolved_plate_targets = 0
        annotated = frame.copy()

        names = result.names
        boxes = result.boxes
        if boxes is not None and len(boxes) > 0:
            xyxy = boxes.xyxy.cpu().numpy()
            classes = boxes.cls.cpu().numpy().astype(int)
            confs = boxes.conf.cpu().numpy()
            ids = boxes.id.cpu().numpy().astype(int) if boxes.id is not None else [None] * len(xyxy)
            records = list(zip(xyxy, classes, confs, ids))
            if stream_mode and len(records) > 1:
                # Rotate OCR priority each inference cycle so a vehicle at the
                # back of a queue does not wait behind the first detection.
                offset = frame_counter % len(records)
                records = records[offset:] + records[:offset]
            # Two crop OCR attempts per cycle keep the second queued vehicle
            # from waiting behind the first while remaining much cheaper than
            # full-frame OCR on every frame.
            plate_ocr_budget = 2 if stream_mode else len(records)
            for box, cls_id, det_conf, track_id in records:
                x1, y1, x2, y2 = [int(v) for v in box]
                x1 += roi_x1
                x2 += roi_x1
                bbox = [x1, y1, x2, y2]
                class_name = names.get(int(cls_id), str(cls_id))
                is_vehicle = is_vehicle_class(class_name)
                is_person = is_person_class(class_name)
                if not is_vehicle and not is_person:
                    continue
                # Vehicle monitoring only emits road vehicles. Pedestrians are
                # handled by the independent road-anomaly task, so lane arrows
                # and zebra markings cannot appear as pedestrian boxes here.
                if is_person and not include_people:
                    continue
                if not is_box_on_road(camera_id, bbox, width, height):
                    continue
                area = box_area(bbox)
                if area < (280 if is_person else 600):
                    continue

                stable_track_id = None if track_id is None else int(track_id)
                if stable_track_id is None:
                    stable_track_id = self._recover_visual_track_id(
                        camera_id,
                        bbox,
                        seen_track_ids,
                        frame_counter,
                    )
                if stable_track_id is not None:
                    seen_track_ids.add(stable_track_id)
                bbox = self._smooth_visual_box(
                    camera_id,
                    stable_track_id,
                    bbox,
                    frame_counter,
                    width,
                    height,
                )
                x1, y1, x2, y2 = bbox
                area = box_area(bbox)

                # Low-confidence detections are useful for a moving vehicle
                # entering at the frame boundary and for associating an
                # existing track. Do not promote an untracked weak detection
                # in the middle of the road, where lane markings are the main
                # false-positive source.
                is_entry_candidate = y1 <= int(height * 0.18) or y2 >= int(height * 0.82)
                if (
                    fast_entry_recovery
                    and is_vehicle
                    and float(det_conf) < 0.18
                    and stable_track_id is None
                    and not is_entry_candidate
                ):
                    continue

                if is_person:
                    detections.append(
                        DetectionBox(
                            bbox=[float(v) for v in bbox],
                            class_name="pedestrian",
                            confidence=float(det_conf),
                            track_id=stable_track_id,
                            camera_id=camera_id,
                        )
                    )
                    events.append(
                        TrafficEvent(
                            type="road_pedestrian",
                            severity="warning",
                            description="检测到道路区域内有行人，请注意避让。",
                            camera_id=camera_id,
                            bbox=[float(v) for v in bbox],
                        )
                    )
                    continue

                crop = frame[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
                credible_before_ocr, visual_features = self._visual_vehicle_is_credible(
                    camera_id,
                    stable_track_id,
                    crop,
                    bbox,
                    frame.shape,
                    float(det_conf),
                )
                # Reject a weak, smooth compact object before spending OCR
                # time on it. A known track is never rejected by this gate.
                if not credible_before_ocr and float(det_conf) < 0.22:
                    continue
                plate_key = self._memory_key(camera_id, stable_track_id, bbox)
                plate_state = self._track_plate_memory.get(plate_key, {})
                plate_ocr_due = crop.size and frame_counter - int(plate_state.get("last_run", -100)) >= 2
                allow_plate_ocr = not stream_mode or (plate_ocr_budget > 0 and plate_ocr_due)
                if stream_mode and allow_plate_ocr:
                    plate_ocr_budget -= 1
                stable_plate = self._stable_track_plate(
                    camera_id,
                    bbox,
                    stable_track_id,
                    crop,
                    stream_mode,
                    frame_counter,
                    allow_ocr=allow_plate_ocr,
                )
                plate_text = stable_plate["text"] if stable_plate else None
                plate_is_provisional = bool(stable_plate and stable_plate.get("provisional"))
                credible_vehicle, visual_features = self._visual_vehicle_is_credible(
                    camera_id,
                    stable_track_id,
                    crop,
                    bbox,
                    frame.shape,
                    float(det_conf),
                    plate_text,
                )
                if not credible_vehicle:
                    continue
                if not plate_text:
                    unresolved_plate_targets += 1
                minimum_unplated_area = 900 if small_target_mode else 5200
                if not plate_text and area < minimum_unplated_area:
                    continue
                plate_confidence = float(stable_plate.get("confidence", 0.0)) if stable_plate else float(det_conf)
                decision = None if plate_is_provisional else self._stable_decision(
                    camera_id,
                    bbox,
                    stable_track_id,
                    plate_text,
                    plate_confidence,
                )
                speed_cm_s = self._track_speed_cm_s(
                    camera_id,
                    stable_track_id,
                    bbox,
                    frame,
                    observed_at,
                )
                if speed_cm_s is not None:
                    measured_speeds.append(speed_cm_s)
                self._remember_visual_metadata(
                    camera_id,
                    stable_track_id,
                    class_name=class_name,
                    confidence=float(det_conf),
                    plate=decision.plate_no if decision else plate_text,
                    whitelist_status=decision.whitelist_status if decision else None,
                    gate_action=decision.gate_action if decision else None,
                    gate_reason=decision.reason if decision else None,
                    speed_cm_s=speed_cm_s,
                    credible_vehicle=True,
                    visual_features=visual_features,
                )
                detections.append(
                    DetectionBox(
                        bbox=[float(v) for v in bbox],
                        class_name=class_name,
                        confidence=float(det_conf),
                        track_id=stable_track_id,
                        plate=decision.plate_no if decision else plate_text,
                        whitelist_status=decision.whitelist_status if decision else None,
                        gate_action=decision.gate_action if decision else None,
                        gate_reason=decision.reason if decision else None,
                        speed_cm_s=speed_cm_s,
                        camera_id=camera_id,
                    )
                )
                vehicle_boxes.append(bbox)
                if plate_text and decision:
                    events.append(whitelist_event(camera_id, bbox, decision.plate_no or plate_text, decision.whitelist_status))

        for predicted_track in self._predicted_visual_tracks(
            camera_id,
            seen_track_ids,
            frame_counter,
            width,
            height,
        ):
            bbox = predicted_track["bbox"]
            if not is_box_on_road(camera_id, bbox, width, height):
                continue
            if any(box_iou(bbox, current_box) >= 0.2 for current_box in vehicle_boxes):
                continue
            confidence = max(
                0.01,
                float(predicted_track.get("confidence", 0.0))
                * float(predicted_track["confidence_decay"]),
            )
            # Keep a short prediction only for visually credible tracks. Very
            # low-confidence extrapolations are usually roadside false positives
            # (trees, lamp posts, reflective edges), not real traffic targets.
            if not predicted_track.get("credible_vehicle"):
                continue
            minimum_prediction_confidence = 0.10 if predicted_track.get("plate") else 0.16
            if confidence < minimum_prediction_confidence:
                continue
            class_name = str(predicted_track.get("class_name", "vehicle"))
            plate = predicted_track.get("plate")
            whitelist_status = predicted_track.get("whitelist_status")
            speed_cm_s = predicted_track.get("speed_cm_s")
            detections.append(
                DetectionBox(
                    bbox=[float(value) for value in bbox],
                    class_name=class_name,
                    confidence=confidence,
                    track_id=predicted_track["track_id"],
                    plate=plate,
                    whitelist_status=whitelist_status,
                    gate_action=predicted_track.get("gate_action"),
                    gate_reason=predicted_track.get("gate_reason"),
                    speed_cm_s=speed_cm_s,
                    predicted=True,
                    camera_id=camera_id,
                )
            )
            vehicle_boxes.append(bbox)
            if speed_cm_s is not None:
                measured_speeds.append(float(speed_cm_s))

        # Full-frame OCR can attach a plate when a detector box is slightly
        # off. Run it often enough for a clear rear plate to appear promptly,
        # while vehicle-crop OCR keeps the usual path inexpensive.
        if not stream_mode or (unresolved_plate_targets and frame_counter % 4 == 1):
            self._last_stream_plates[camera_id] = self.detect_plates(frame)
        full_plates = self._last_stream_plates.get(camera_id, [])
        for plate in full_plates:
            plate_box = plate.get("bbox")
            if not plate_box:
                continue
            plate_box = [int(v) for v in plate_box]
            matched_index = next(
                (
                    index
                    for index, detection in enumerate(detections)
                    if plate_belongs_to_vehicle(
                        plate_box,
                        [int(value) for value in detection.bbox],
                    )
                ),
                None,
            )
            if matched_index is not None:
                matched = detections[matched_index]
                matched_box = [int(value) for value in matched.bbox]
                matched_track_id = int(matched.track_id) if isinstance(matched.track_id, int) else None
                decision = self._stable_decision(
                    camera_id,
                    matched_box,
                    matched_track_id,
                    plate["text"],
                    float(plate.get("confidence", 0.0)),
                ) or decide_plate(plate["text"], float(plate.get("confidence", 0.0)))
                detections[matched_index] = matched.model_copy(
                    update={
                        "plate": decision.plate_no,
                        "whitelist_status": decision.whitelist_status,
                        "gate_action": decision.gate_action,
                        "gate_reason": decision.reason,
                    }
                )
                self._remember_visual_metadata(
                    camera_id,
                    matched_track_id,
                    class_name=matched.class_name,
                    confidence=matched.confidence,
                    plate=decision.plate_no,
                    whitelist_status=decision.whitelist_status,
                    gate_action=decision.gate_action,
                    gate_reason=decision.reason,
                    speed_cm_s=matched.speed_cm_s,
                )
                events.append(
                    whitelist_event(
                        camera_id,
                        matched_box,
                        decision.plate_no or plate["text"],
                        decision.whitelist_status,
                    )
                )
                continue
            derived_box = plate_to_vehicle_box(plate_box, frame.shape)
            if not is_box_on_road(camera_id, derived_box, width, height):
                continue
            decision = self._stable_decision(camera_id, derived_box, None, plate["text"], float(plate.get("confidence", 0.0))) or decide_plate(
                plate["text"],
                float(plate.get("confidence", 0.0)),
            )
            detections.append(
                DetectionBox(
                    bbox=[float(v) for v in derived_box],
                    class_name="plate-derived vehicle",
                    confidence=float(plate.get("confidence", 0.0)),
                    track_id=None,
                    plate=decision.plate_no,
                    whitelist_status=decision.whitelist_status,
                    gate_action=decision.gate_action,
                    gate_reason=decision.reason,
                    camera_id=camera_id,
                )
            )
            vehicle_boxes.append(derived_box)
            events.append(whitelist_event(camera_id, derived_box, decision.plate_no or plate["text"], decision.whitelist_status))

        # A close sandtable vehicle can be returned once by YOLO and again by
        # plate fallback (or by two highly-overlapping classes). Suppress that
        # duplicate before rendering, counting, heat-map updates and reports.
        detections = suppress_duplicate_vehicle_detections(detections)
        vehicle_boxes = [
            [int(value) for value in item.bbox]
            for item in detections
            if is_vehicle_class(item.class_name) or "vehicle" in item.class_name
        ]
        measured_speeds = [
            float(item.speed_cm_s)
            for item in detections
            if (is_vehicle_class(item.class_name) or "vehicle" in item.class_name)
            and item.speed_cm_s is not None
        ]

        if annotate:
            for detection in detections:
                bbox = [int(value) for value in detection.bbox]
                track_prefix = f"id:{detection.track_id} " if detection.track_id is not None else ""
                label = f"{track_prefix}{detection.class_name} {detection.confidence:.2f}"
                if detection.plate:
                    if detection.whitelist_status is True:
                        label += f" {detection.plate} PASS"
                    elif detection.whitelist_status is False:
                        label += f" {detection.plate} BLOCK"
                    else:
                        label += f" {detection.plate} OCR"
                if detection.speed_cm_s is not None:
                    label += f" {detection.speed_cm_s:.1f}cm/s"
                color = (36, 107, 253)
                if detection.whitelist_status is True:
                    color = (22, 163, 74)
                elif detection.whitelist_status is False:
                    color = (38, 38, 220)
                draw_label(annotated, bbox, label, color)

        if frame_counter % 60 == 0:
            self._prune_plate_memory(camera_id, frame_counter)
            self._prune_motion_memory(observed_at)

        inference_ms = round((time.perf_counter() - started) * 1000, 2)
        raw_vehicle_count = len([item for item in detections if "vehicle" in item.class_name or is_vehicle_class(item.class_name)])
        vehicle_count = self._stable_vehicle_count(camera_id, raw_vehicle_count)
        density = min(1.0, vehicle_count / 8.0)
        avg_speed = round(float(np.mean(measured_speeds)), 1) if measured_speeds else None
        congestion = "high" if density >= 0.75 else "medium" if density >= 0.4 else "low" if vehicle_count else "unknown"
        if vehicle_count >= 6:
            events.append(
                TrafficEvent(
                    type="congestion",
                    severity="warning",
                    description=f"Current view has {vehicle_count} vehicle targets.",
                    camera_id=camera_id,
                )
            )
        reviewable_vehicles = [
            item
            for item in detections
            if ("vehicle" in item.class_name or is_vehicle_class(item.class_name))
            and not item.predicted
            and item.confidence >= 0.45
        ]
        plate_count = len([item for item in reviewable_vehicles if item.plate])
        if reviewable_vehicles and plate_count < len(reviewable_vehicles):
            events.append(
                TrafficEvent(
                    type="plate_review",
                    severity="info",
                    description=f"当前画面 {vehicle_count - plate_count} 个车辆目标未稳定识别车牌，建议人工复核。",
                    camera_id=camera_id,
                )
            )
        analysis = AnalysisResult(
            frame_id=self._frame_id,
            timestamp=now_iso(),
            camera_id=camera_id,
            source_width=int(frame.shape[1]),
            source_height=int(frame.shape[0]),
            inference_ms=inference_ms,
            model_id=self._model_path(model_name).name,
            detections=detections,
            traffic_stats=TrafficStats(
                vehicle_count=vehicle_count,
                current_count=vehicle_count,
                density=round(density, 3),
                avg_speed=avg_speed,
                avg_speed_unit="cm/s",
                speed_estimated=camera_id != REFERENCE_CAMERA_ID,
                congestion_level=congestion,
            ),
            events=events,
            raw={
                "plates": full_plates,
                "mode": "local_sandtable_model",
                "device": "cuda:0" if self._device != "cpu" else "cpu",
                "device_name": self._device_name,
                "speed_calibration": {
                    "reference_camera_id": REFERENCE_CAMERA_ID,
                    "current_camera_id": camera_id,
                    "mode": "measured" if camera_id == REFERENCE_CAMERA_ID else "estimated",
                    "region_width_cm": 40.0,
                    "region_length_cm": 70.0,
                },
                "small_target_mode": {
                    "enabled": small_target_mode,
                    "selected_automatically": camera_id.startswith("custom"),
                    "view_mode": current_view_mode,
                    "roi": [roi_x1, 0, roi_x2, height],
                    "inference_size": inference_size,
                },
                "raw_vehicle_count": raw_vehicle_count,
            },
        )
        annotated_jpeg = None
        if annotate:
            ok, buffer = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
            if ok:
                annotated_jpeg = buffer.tobytes()
        return analysis, annotated_jpeg

    def annotated_mjpeg_frames(
        self,
        camera_id: str,
        frame_source,
        model_name: str = "auto",
        conf: float = 0.30,
        imgsz: int = 1280,
        sleep_seconds: float = 0.03,
        on_result: Callable[[AnalysisResult, bytes], None] | None = None,
        should_continue: Callable[[], bool] | None = None,
        policy_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> Generator[bytes, None, None]:
        while should_continue is None or should_continue():
            cycle_started = time.perf_counter()
            jpeg = frame_source()
            if jpeg is None:
                time.sleep(0.05)
                continue
            policy = policy_provider() if policy_provider is not None else {}
            analysis, annotated = self.infer_jpeg(
                camera_id,
                jpeg,
                model_name=str(policy.get("model_name", model_name)),
                conf=float(policy.get("confidence", conf)),
                imgsz=int(policy.get("inference_size", imgsz)),
                annotate=True,
                stream_mode=True,
                fast_entry_recovery=True,
            )
            if should_continue is not None and not should_continue():
                break
            if on_result is not None:
                on_result(analysis, jpeg)
            if annotated is None:
                time.sleep(0.05)
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Cache-Control: no-cache\r\n\r\n" + annotated + b"\r\n"
            )
            elapsed = time.perf_counter() - cycle_started
            target_sleep = float(policy.get("detection_interval_ms", sleep_seconds * 1000)) / 1000
            time.sleep(max(0.0, target_sleep - elapsed))
