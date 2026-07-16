from __future__ import annotations

import argparse
import csv
import json
import math
import platform
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import cv2

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.local_model import LocalModelService


VIDEO_SUFFIXES = {".mp4", ".mkv", ".avi", ".mov"}


def normalize_output_path(path: Path, base_directory: Path | None = None) -> Path:
    base = base_directory or Path.cwd()
    return path.expanduser().resolve() if path.is_absolute() else (base / path).resolve()


def sample_timestamps(duration_seconds: float, sample_count: int) -> list[float]:
    if duration_seconds <= 0 or sample_count <= 0:
        return []
    step = duration_seconds / sample_count
    return [round(step * (index + 0.5), 3) for index in range(sample_count)]


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return round(float(ordered[rank - 1]), 2)


def summarize_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(records)
    successful = [item for item in items if not item.get("error")]
    inference_times = [float(item["inference_ms"]) for item in successful if item.get("inference_ms") is not None]
    plates = sorted({str(plate) for item in successful for plate in item.get("plates", []) if plate})
    return {
        "sampled_frames": len(items),
        "successful_frames": len(successful),
        "error_frames": len(items) - len(successful),
        "frames_with_detections": sum(int(item.get("detection_count", 0) > 0) for item in successful),
        "detection_count": sum(int(item.get("detection_count", 0)) for item in successful),
        "vehicle_count_sum": sum(int(item.get("vehicle_count", 0)) for item in successful),
        "unique_plates": plates,
        "event_count": sum(int(item.get("event_count", 0)) for item in successful),
        "inference_ms_mean": round(statistics.fmean(inference_times), 2) if inference_times else None,
        "inference_ms_p50": round(statistics.median(inference_times), 2) if inference_times else None,
        "inference_ms_p95": _nearest_rank(inference_times, 0.95),
        "inference_ms_max": round(max(inference_times), 2) if inference_times else None,
    }


def discover_videos(exports_root: Path, extra_inputs: list[Path]) -> list[tuple[str, Path]]:
    discovered: list[tuple[str, Path]] = []
    if exports_root.exists():
        for path in sorted(exports_root.rglob("*_000.mp4")):
            discovered.append((path.parent.name, path))
    for index, path in enumerate(extra_inputs, start=1):
        if path.suffix.lower() not in VIDEO_SUFFIXES:
            continue
        discovered.append((f"custom_eval_{index}", path))
    return discovered


def video_metadata(path: Path) -> dict[str, Any]:
    capture = cv2.VideoCapture(str(path))
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = frame_count / fps if fps > 0 else 0.0
        return {
            "fps": round(fps, 3),
            "frame_count": frame_count,
            "duration_seconds": round(duration, 3),
            "width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
            "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
            "readable": capture.isOpened(),
        }
    finally:
        capture.release()


def evaluate_video(
    service: LocalModelService,
    camera_id: str,
    source: Path,
    output_dir: Path,
    sample_count: int,
    confidence: float,
    inference_size: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metadata = video_metadata(source)
    records: list[dict[str, Any]] = []
    annotated_dir = output_dir / "annotated"
    annotated_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(source))
    try:
        for timestamp in sample_timestamps(float(metadata["duration_seconds"]), sample_count):
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
            ok, frame = capture.read()
            if not ok or frame is None:
                records.append(
                    {
                        "camera_id": camera_id,
                        "source_file": str(source),
                        "sample_time_seconds": timestamp,
                        "error": "unreadable frame",
                        "detection_count": 0,
                        "vehicle_count": 0,
                        "plates": [],
                        "event_count": 0,
                        "inference_ms": None,
                    }
                )
                continue

            result, annotated_jpeg = service.infer_frame(
                camera_id,
                frame,
                model_name="auto",
                conf=confidence,
                imgsz=inference_size,
                annotate=True,
                stream_mode=False,
                include_people=camera_id == "live3",
            )
            plates = sorted({item.plate for item in result.detections if item.plate})
            event_types = Counter(item.type for item in result.events)
            annotation_path = None
            if annotated_jpeg:
                annotation_path = annotated_dir / f"{camera_id}_{timestamp:07.2f}s.jpg"
                annotation_path.write_bytes(annotated_jpeg)
            records.append(
                {
                    "camera_id": camera_id,
                    "source_file": str(source),
                    "sample_time_seconds": timestamp,
                    "error": result.error,
                    "model_id": result.model_id,
                    "device": (result.raw or {}).get("device"),
                    "inference_ms": result.inference_ms,
                    "detection_count": len(result.detections),
                    "vehicle_count": result.traffic_stats.vehicle_count,
                    "raw_vehicle_count": (result.raw or {}).get("raw_vehicle_count"),
                    "plates": plates,
                    "event_count": len(result.events),
                    "event_types": dict(sorted(event_types.items())),
                    "detections": [item.model_dump(mode="json") for item in result.detections],
                    "traffic_stats": result.traffic_stats.model_dump(mode="json"),
                    "annotation_file": str(annotation_path) if annotation_path else None,
                }
            )
    finally:
        capture.release()
    return metadata, records


def write_outputs(output_dir: Path, manifest: dict[str, Any], records: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (output_dir / "frame_results.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    fieldnames = [
        "camera_id",
        "source_file",
        "sample_time_seconds",
        "error",
        "model_id",
        "device",
        "inference_ms",
        "detection_count",
        "vehicle_count",
        "raw_vehicle_count",
        "plates",
        "event_count",
        "event_types",
        "annotation_file",
    ]
    with (output_dir / "frame_results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["plates"] = "|".join(record.get("plates", []))
            row["event_types"] = json.dumps(record.get("event_types", {}), ensure_ascii=False)
            writer.writerow(row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate fixed samples from real STrans sandtable videos.")
    parser.add_argument("--exports-root", type=Path, default=Path(r"F:\STrans_exports"))
    parser.add_argument("--input", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=640)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output = normalize_output_path(args.output)
    videos = discover_videos(args.exports_root, args.input)
    if not videos:
        print("No videos found.", file=sys.stderr)
        return 2

    service = LocalModelService()
    all_records: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for camera_id, source in videos:
        print(f"Evaluating {camera_id}: {source}", flush=True)
        metadata, records = evaluate_video(
            service,
            camera_id,
            source,
            args.output,
            args.samples,
            args.conf,
            args.imgsz,
        )
        all_records.extend(records)
        sources.append(
            {
                "camera_id": camera_id,
                "source_file": str(source),
                "metadata": metadata,
                "summary": summarize_records(records),
            }
        )

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "model_health": service.health(),
        "settings": {
            "samples_per_video": args.samples,
            "confidence": args.conf,
            "inference_size": args.imgsz,
        },
        "sources": sources,
        "overall_summary": summarize_records(all_records),
    }
    write_outputs(args.output, manifest, all_records)
    print(json.dumps(manifest["overall_summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
