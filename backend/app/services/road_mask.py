from __future__ import annotations

import base64
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from huggingface_hub import snapshot_download
from transformers import AutoImageProcessor, AutoModelForSemanticSegmentation


ROOT = Path(__file__).resolve().parents[2]
MODEL_ID = "nvidia/segformer-b0-finetuned-cityscapes-1024-1024"
MODEL_DIR = ROOT / "data" / "models" / "segformer-b0-cityscapes"
MASK_MAX_WIDTH = 256
MASK_CACHE_SECONDS = 0.5


def road_class_ids(id2label: dict[int | str, str]) -> set[int]:
    return {int(index) for index, label in id2label.items() if str(label).strip().lower() == "road"}


def encode_mask_data_url(mask: np.ndarray) -> str:
    ok, encoded = cv2.imencode(".png", mask)
    if not ok:
        raise ValueError("Unable to encode road mask.")
    return "data:image/png;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")


def render_road_schematic(mask: np.ndarray) -> np.ndarray:
    """Render a clean heatmap base from semantic road geometry only."""
    binary = np.where(mask > 0, 255, 0).astype(np.uint8)
    canvas = np.full((*binary.shape, 3), (25, 39, 52), dtype=np.uint8)
    canvas[binary > 0] = (72, 93, 104)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(canvas, contours, -1, (117, 209, 224), max(1, round(min(binary.shape) / 90)))
    return canvas


class RoadMaskService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model: Any | None = None
        self._processor: Any | None = None
        self._road_ids: set[int] = set()
        self._load_error: str | None = None
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._device = "cuda:0" if torch.cuda.is_available() else "cpu"

    def download_model(self) -> Path:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id=MODEL_ID, local_dir=MODEL_DIR)
        return MODEL_DIR

    def ensure_model_available(self) -> None:
        if not (MODEL_DIR / "config.json").exists():
            self.download_model()

    def health(self) -> dict[str, Any]:
        return {
            "model_id": MODEL_ID,
            "model_path": str(MODEL_DIR),
            "installed": (MODEL_DIR / "config.json").exists(),
            "loaded": self._model is not None,
            "device": self._device,
            "error": self._load_error,
        }

    def _load_model(self) -> None:
        if self._model is not None:
            return
        self.ensure_model_available()
        try:
            processor = AutoImageProcessor.from_pretrained(MODEL_DIR, local_files_only=True)
            model = AutoModelForSemanticSegmentation.from_pretrained(MODEL_DIR, local_files_only=True)
            labels = road_class_ids(model.config.id2label)
            if not labels:
                raise RuntimeError("The configured segmentation model does not define a road label.")
            model.to(self._device)
            model.eval()
            self._processor = processor
            self._model = model
            self._road_ids = labels
            self._load_error = None
        except Exception as error:
            self._load_error = str(error)
            raise RuntimeError("Unable to load the local road mask model.") from error

    def snapshot(self, camera_id: str, jpeg: bytes | None) -> dict[str, Any]:
        if jpeg is None:
            return {"camera_id": camera_id, "status": "unavailable", "error": "No frame available. Start the camera stream first."}
        now = time.monotonic()
        cached = self._cache.get(camera_id)
        if cached and now - cached[0] < MASK_CACHE_SECONDS:
            return {**cached[1], "cached": True}
        with self._lock:
            cached = self._cache.get(camera_id)
            if cached and now - cached[0] < MASK_CACHE_SECONDS:
                return {**cached[1], "cached": True}
            self._load_model()
            frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                return {"camera_id": camera_id, "status": "unavailable", "error": "Invalid camera frame."}
            height, width = frame.shape[:2]
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            started = time.perf_counter()
            inputs = self._processor(images=frame_rgb, return_tensors="pt")
            inputs = {key: value.to(self._device) for key, value in inputs.items()}
            with torch.inference_mode():
                logits = self._model(**inputs).logits
                logits = torch.nn.functional.interpolate(logits, size=(height, width), mode="bilinear", align_corners=False)
                labels = logits.argmax(dim=1)[0].detach().cpu().numpy()
            binary_mask = np.where(np.isin(labels, list(self._road_ids)), 255, 0).astype(np.uint8)
            mask_width = min(width, MASK_MAX_WIDTH)
            mask_height = max(1, round(height * mask_width / width))
            binary_mask = cv2.resize(binary_mask, (mask_width, mask_height), interpolation=cv2.INTER_NEAREST)
            schematic = render_road_schematic(binary_mask)
            result = {
                "camera_id": camera_id,
                "status": "ready",
                "width": width,
                "height": height,
                "mask_data_url": encode_mask_data_url(binary_mask),
                "schematic_data_url": encode_mask_data_url(schematic),
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "inference_ms": round((time.perf_counter() - started) * 1000, 1),
                "cached": False,
            }
            self._cache[camera_id] = (now, result)
            return result


road_mask_service = RoadMaskService()
