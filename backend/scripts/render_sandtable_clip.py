from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.local_model import LocalModelService
from scripts.evaluate_sandtable_videos import normalize_output_path, summarize_records
from scripts.record_sandtable_rtsp import available_video_encoders


def clip_timestamps(start_seconds: float, duration_seconds: float, sample_fps: float) -> list[float]:
    if duration_seconds <= 0 or sample_fps <= 0:
        return []
    frame_count = int(duration_seconds * sample_fps)
    return [round(start_seconds + index / sample_fps, 3) for index in range(frame_count)]


def inference_device_label(raw_result: dict[str, Any] | None) -> str:
    return str((raw_result or {}).get("device") or "unknown").upper()


def build_clip_ffmpeg_command(
    ffmpeg: str,
    frames_pattern: Path,
    sample_fps: float,
    output_video: Path,
    available_encoders: set[str],
) -> list[str]:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-framerate",
        str(sample_fps),
        "-i",
        str(frames_pattern),
    ]
    if "libx264" in available_encoders:
        command.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "20"])
    elif "h264_mf" in available_encoders:
        command.extend(["-c:v", "h264_mf", "-b:v", "5M"])
    else:
        raise RuntimeError("FFmpeg has no H.264 encoder (libx264 or h264_mf).")
    command.extend(["-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output_video)])
    return command


def render_clip(
    source: Path,
    camera_id: str,
    start_seconds: float,
    duration_seconds: float,
    sample_fps: float,
    output_video: Path,
    confidence: float,
    inference_size: int,
    ffmpeg: str,
) -> dict[str, Any]:
    output_video.parent.mkdir(parents=True, exist_ok=True)
    frames_dir = output_video.parent / f"{output_video.stem}_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    service = LocalModelService()
    capture = cv2.VideoCapture(str(source))
    records: list[dict[str, Any]] = []
    try:
        for index, timestamp in enumerate(clip_timestamps(start_seconds, duration_seconds, sample_fps)):
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
            ok, frame = capture.read()
            if not ok or frame is None:
                raise RuntimeError(f"Cannot read {source} at {timestamp:.3f}s")
            result, annotated_jpeg = service.infer_frame(
                camera_id,
                frame,
                model_name="auto",
                conf=confidence,
                imgsz=inference_size,
                annotate=True,
                stream_mode=True,
                include_people=camera_id == "live3",
            )
            annotated = frame
            if annotated_jpeg:
                annotated = cv2.imdecode(
                    np.frombuffer(annotated_jpeg, dtype=np.uint8),
                    cv2.IMREAD_COLOR,
                )
            status_text = (
                f"{camera_id}  t={timestamp:.2f}s  targets={len(result.detections)}  "
                f"vehicles={result.traffic_stats.vehicle_count}  infer={result.inference_ms:.0f}ms  "
                f"{inference_device_label(result.raw)}"
            )
            cv2.rectangle(annotated, (0, 0), (annotated.shape[1], 44), (18, 28, 46), -1)
            cv2.putText(
                annotated,
                status_text,
                (18, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.72,
                (245, 248, 255),
                2,
                cv2.LINE_AA,
            )
            frame_path = frames_dir / f"{index:04d}.jpg"
            if not cv2.imwrite(str(frame_path), annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 90]):
                raise RuntimeError(f"Cannot write frame: {frame_path}")
            records.append(
                {
                    "camera_id": camera_id,
                    "source_file": str(source),
                    "sample_time_seconds": timestamp,
                    "error": result.error,
                    "inference_ms": result.inference_ms,
                    "detection_count": len(result.detections),
                    "vehicle_count": result.traffic_stats.vehicle_count,
                    "plates": sorted({item.plate for item in result.detections if item.plate}),
                    "event_count": len(result.events),
                    "event_types": dict(sorted(Counter(item.type for item in result.events).items())),
                    "frame_file": str(frame_path),
                }
            )
            print(
                f"{camera_id} frame {index + 1}/{int(duration_seconds * sample_fps)} "
                f"t={timestamp:.2f}s targets={len(result.detections)} infer={result.inference_ms:.2f}ms",
                flush=True,
            )
    finally:
        capture.release()

    command = build_clip_ffmpeg_command(
        ffmpeg,
        frames_dir / "%04d.jpg",
        sample_fps,
        output_video,
        available_video_encoders(ffmpeg),
    )
    subprocess.run(command, check=True)
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": str(source),
        "camera_id": camera_id,
        "start_seconds": start_seconds,
        "duration_seconds": duration_seconds,
        "sample_fps": sample_fps,
        "confidence": confidence,
        "inference_size": inference_size,
        "model_health": service.health(),
        "summary": summarize_records(records),
        "records": records,
        "output_video": str(output_video),
    }
    (output_video.with_suffix(".json")).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a short annotated sandtable clip for PPT evidence.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--duration", type=float, default=6.0)
    parser.add_argument("--sample-fps", type=float, default=4.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = normalize_output_path(args.output)
    manifest = render_clip(
        source=args.source.expanduser().resolve(),
        camera_id=args.camera_id,
        start_seconds=args.start,
        duration_seconds=args.duration,
        sample_fps=args.sample_fps,
        output_video=output,
        confidence=args.conf,
        inference_size=args.imgsz,
        ffmpeg=args.ffmpeg,
    )
    print(json.dumps(manifest["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
