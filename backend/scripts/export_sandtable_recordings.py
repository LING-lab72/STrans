"""Validate and batch-remux retained sandtable recordings into MP4 files."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


def is_complete_recording(size_bytes: int, probe_returncode: int, probe_output: str) -> bool:
    """Return whether FFprobe found a usable video stream in a non-empty file."""
    if size_bytes <= 0 or probe_returncode != 0:
        return False
    fields = [line.strip() for line in probe_output.splitlines() if line.strip()]
    if not fields:
        return False
    try:
        return float(fields[-1]) > 0
    except ValueError:
        return False


def build_probe_command(ffprobe: str, input_file: Path) -> list[str]:
    return [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name:format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(input_file),
    ]


def build_export_command(ffmpeg: str, input_file: Path, output_file: Path) -> list[str]:
    return [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_file),
        "-map",
        "0:v:0",
        "-an",
        "-c:v",
        "copy",
        "-movflags",
        "+faststart",
        "-y",
        str(output_file),
    ]


@dataclass
class ExportSummary:
    exported: int = 0
    skipped_incomplete: int = 0
    skipped_existing: int = 0
    failed: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch-export complete sandtable MKV recordings as MP4 files.")
    parser.add_argument("--input-dir", type=Path, required=True, help="Recording root containing live*/ directories.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Destination root for MP4 files.")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing MP4 files.")
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    parser.add_argument("--ffprobe", default=shutil.which("ffprobe") or "ffprobe")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist: {args.input_dir}")
    for executable, name in ((args.ffmpeg, "ffmpeg"), (args.ffprobe, "ffprobe")):
        if not shutil.which(executable) and not Path(executable).exists():
            raise SystemExit(f"{name} was not found. Install it or pass --{name} with its executable path.")

    summary = ExportSummary()
    recordings = sorted(args.input_dir.glob("live*/*.mkv"))
    if not recordings:
        print("No MKV recording files found.")
        return 0

    for input_file in recordings:
        probe = subprocess.run(build_probe_command(args.ffprobe, input_file), capture_output=True, text=True, check=False)
        relative_path = input_file.relative_to(args.input_dir).with_suffix(".mp4")
        output_file = args.output_dir / relative_path
        if not is_complete_recording(input_file.stat().st_size, probe.returncode, probe.stdout):
            summary.skipped_incomplete += 1
            print(f"SKIP incomplete: {relative_path}")
            continue
        if output_file.exists() and not args.overwrite:
            summary.skipped_existing += 1
            print(f"SKIP existing: {relative_path}")
            continue

        output_file.parent.mkdir(parents=True, exist_ok=True)
        export = subprocess.run(build_export_command(args.ffmpeg, input_file, output_file), check=False)
        if export.returncode == 0 and output_file.exists() and output_file.stat().st_size > 0:
            summary.exported += 1
            print(f"EXPORTED: {relative_path}")
        else:
            summary.failed += 1
            print(f"FAILED: {relative_path}")

    print(
        "Summary: "
        f"exported={summary.exported}, incomplete={summary.skipped_incomplete}, "
        f"existing={summary.skipped_existing}, failed={summary.failed}."
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
