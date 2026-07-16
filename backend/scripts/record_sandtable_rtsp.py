"""Continuously retain a bounded local recording ring for one sandtable RTSP camera."""

from __future__ import annotations

import argparse
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.camera_hub import CameraHub


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = BACKEND_ROOT / "data" / "recordings"


def select_video_codec(requested: str, available_encoders: set[str]) -> str:
    if requested in available_encoders or requested == "copy":
        return requested
    if requested == "libx264":
        # The sandtable cameras already publish H.264.  Falling back to stream
        # copy is more reliable than a platform hardware encoder when twelve
        # sources are recorded concurrently, and avoids an unnecessary encode.
        return "copy"
    raise RuntimeError(f"Requested video encoder is not available: {requested}")


def available_video_encoders(ffmpeg: str) -> set[str]:
    completed = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    encoders: set[str] = set()
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0].startswith("V"):
            encoders.add(fields[1])
    return encoders


def build_ffmpeg_command(
    ffmpeg: str,
    source: str,
    output_pattern: Path,
    segment_seconds: int,
    max_segments: int,
    video_codec: str = "copy",
    preset: str | None = None,
    crf: int | None = None,
) -> list[str]:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-i",
        source,
        "-map",
        "0:v:0",
        "-an",
        "-c:v",
        video_codec,
    ]
    if video_codec != "copy":
        command.extend(["-preset", preset or "ultrafast", "-crf", str(crf if crf is not None else 30)])
    command.extend([
        "-f",
        "segment",
        "-segment_time",
        str(segment_seconds),
        "-segment_wrap",
        str(max_segments),
        "-reset_timestamps",
        "1",
        "-y",
        str(output_pattern),
    ])
    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record one sandtable RTSP stream into a bounded MKV segment ring.")
    parser.add_argument("--camera-id", default="live1", help="Configured sandtable camera ID (default: live1).")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--segment-seconds", type=int, default=300, help="Length of each segment (default: 300 seconds).")
    parser.add_argument("--max-segments", type=int, default=24, help="Maximum retained segments (default: 24, about two hours).")
    parser.add_argument("--video-codec", choices=["copy", "libx264"], default="copy", help="Use libx264 to reduce disk usage (default: copy).")
    parser.add_argument("--preset", default="ultrafast", help="FFmpeg encoder preset when transcoding (default: ultrafast).")
    parser.add_argument("--crf", type=int, default=30, help="H.264 quality level when transcoding (default: 30).")
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.segment_seconds < 30 or args.max_segments < 2:
        raise SystemExit("segment-seconds must be at least 30 and max-segments at least 2.")
    if not shutil.which(args.ffmpeg) and not Path(args.ffmpeg).exists():
        raise SystemExit("ffmpeg was not found. Install it or pass --ffmpeg with its executable path.")
    try:
        selected_codec = select_video_codec(args.video_codec, available_video_encoders(args.ffmpeg))
    except RuntimeError as error:
        raise SystemExit(str(error)) from error

    hub = CameraHub()
    try:
        camera = hub.get_source(args.camera_id)
    except KeyError as error:
        raise SystemExit(f"Unknown camera ID: {args.camera_id}") from error
    if camera.type != "sandtable":
        raise SystemExit(f"Camera {args.camera_id} is not a sandtable RTSP source.")

    output_dir = args.output_dir / args.camera_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = output_dir / f"{args.camera_id}_%03d.mkv"
    keep_running = True

    def stop(_signal: int, _frame: object) -> None:
        nonlocal keep_running
        keep_running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(f"Recording {args.camera_id} into {output_dir}; codec={selected_codec}; retaining {args.max_segments} segments.", flush=True)

    while keep_running:
        command = build_ffmpeg_command(
            args.ffmpeg,
            camera.stream_url,
            output_pattern,
            args.segment_seconds,
            args.max_segments,
            video_codec=selected_codec,
            preset=args.preset,
            crf=args.crf,
        )
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while keep_running and process.poll() is None:
            time.sleep(1)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        if keep_running:
            print(f"Recorder for {args.camera_id} reconnecting in 5 seconds.", flush=True)
            time.sleep(5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
