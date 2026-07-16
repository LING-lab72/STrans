"""批量截取沙盘 RTSP 摄像头画面。

用法:
  python batch_capture.py                     # 截取全部 12 个摄像头
  python batch_capture.py --cameras live1 live3  # 只截取指定摄像头
  python batch_capture.py --out-dir ./frames  # 自定义输出目录
  python batch_capture.py --timeout 15        # 单个摄像头超时秒数（默认 12）
  python batch_capture.py --no-jpg            # 不保存 jpg 文件，只生成 JSON

输出:
  <out-dir>/live1.jpg          # 每个摄像头的画面
  <out-dir>/live1.meta.json    # 每个摄像头的元数据
  <out-dir>/capture_report.json # 汇总报告（含 base64 dataUrl，可导入建模器）
  <out-dir>/capture_report.csv  # CSV 格式报告
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── 12 路沙盘摄像头预设 ──
CAMERA_PRESETS = [
    {"id": "live1",  "place": "桥面",         "url": "rtsp://10.126.59.120:8554/live/live1"},
    {"id": "live2",  "place": "停车场出口",   "url": "rtsp://10.126.59.120:8554/live/live2"},
    {"id": "live3",  "place": "行人检测",     "url": "rtsp://10.126.59.120:8554/live/live3"},
    {"id": "live4",  "place": "消防车识别",   "url": "rtsp://10.126.59.120:8554/live/live4"},
    {"id": "live5",  "place": "桥出口",       "url": "rtsp://10.126.59.120:8554/live/live5"},
    {"id": "live6",  "place": "桥入口",       "url": "rtsp://10.126.59.120:8554/live/live6"},
    {"id": "live7",  "place": "道路2",         "url": "rtsp://10.126.59.120:8554/live/live7"},
    {"id": "live8",  "place": "隧道（事故识别）", "url": "rtsp://10.126.59.120:8554/live/live8"},
    {"id": "live9",  "place": "隧道（车辆数量）", "url": "rtsp://10.126.59.120:8554/live/live9"},
    {"id": "live10", "place": "道路3",         "url": "rtsp://10.126.59.120:8554/live/live10"},
    {"id": "live11", "place": "停车场入口",   "url": "rtsp://10.126.59.120:8554/live/live11"},
    {"id": "live12", "place": "道路1",         "url": "rtsp://10.126.59.120:8554/live/live12"},
]


def capture_frame(url: str, timeout: int = 12) -> bytes:
    """用 ffmpeg 截取单帧 RTSP 画面，返回 JPEG 字节。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，请先安装并加入 PATH")
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-rtsp_transport", "tcp", "-timeout", "8000000",
        "-i", url, "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ]
    result = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
    if result.returncode != 0 or not result.stdout:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        # 取最后一行作为错误信息
        last_line = stderr.splitlines()[-1] if stderr else "ffmpeg 未返回画面"
        raise RuntimeError(last_line)
    if result.stdout[:2] != b"\xff\xd8":
        raise RuntimeError("返回数据不是有效的 JPEG")
    return result.stdout


def get_image_dimensions(jpeg_bytes: bytes):
    """从 JPEG 字节中解析宽高（不依赖 PIL/cv2）。"""
    try:
        import struct
        data = jpeg_bytes
        i = 2  # 跳过 SOI 标记
        while i < len(data) - 1:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                # SOF0/SOF1/SOF2: 包含宽高信息
                height = struct.unpack(">H", data[i + 5:i + 7])[0]
                width = struct.unpack(">H", data[i + 7:i + 9])[0]
                return width, height
            elif marker == 0xD9:
                break  # EOI
            elif marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0x01):
                i += 2
            else:
                if i + 3 < len(data):
                    length = struct.unpack(">H", data[i + 2:i + 4])[0]
                    i += 2 + length
                else:
                    break
    except Exception:
        pass
    return 0, 0


def run_batch(cameras: list, out_dir: Path, timeout: int, save_jpg: bool):
    """批量截取所有指定摄像头的画面。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    total = len(cameras)

    print(f"开始批量截取 {total} 个摄像头画面...\n")

    for idx, cam in enumerate(cameras, 1):
        cam_id = cam["id"]
        place = cam["place"]
        url = cam["url"]
        prefix = f"[{idx}/{total}] {cam_id} ({place})"
        print(f"{prefix} 正在截取...", end="", flush=True)
        t0 = time.time()

        entry = {
            "id": cam_id,
            "place": place,
            "url": url,
            "status": "pending",
            "elapsed": 0,
            "error": "",
        }

        try:
            jpeg = capture_frame(url, timeout=timeout)
            elapsed = time.time() - t0
            width, height = get_image_dimensions(jpeg)
            data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
            captured_at = datetime.now(timezone.utc).isoformat()

            entry.update({
                "status": "ok",
                "elapsed": round(elapsed, 1),
                "size": len(jpeg),
                "width": width,
                "height": height,
                "dataUrl": data_url,
                "capturedAt": captured_at,
            })

            if save_jpg:
                jpg_path = out_dir / f"{cam_id}.jpg"
                jpg_path.write_bytes(jpeg)

            meta_path = out_dir / f"{cam_id}.meta.json"
            meta_path.write_text(
                json.dumps({
                    "name": f"{cam_id}.jpg",
                    "dataUrl": data_url,
                    "width": width,
                    "height": height,
                    "capturedAt": captured_at,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            print(f" 成功  {width}x{height}  {len(jpeg) // 1024}KB  {elapsed:.1f}s")

        except subprocess.TimeoutExpired:
            elapsed = time.time() - t0
            entry.update({"status": "timeout", "elapsed": round(elapsed, 1), "error": f"超时 ({timeout}s)"})
            print(f" 超时  {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - t0
            entry.update({"status": "error", "elapsed": round(elapsed, 1), "error": str(e)})
            print(f" 失败  {e}")

        results.append(entry)

    # 汇总报告
    report_path = out_dir / "capture_report.json"
    ok_count = sum(1 for r in results if r["status"] == "ok")
    report = {
        "summary": {
            "total": total,
            "ok": ok_count,
            "failed": total - ok_count,
            "capturedAt": datetime.now(timezone.utc).isoformat(),
        },
        "cameras": results,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # CSV 报告
    csv_path = out_dir / "capture_report.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "place", "status", "elapsed", "size", "width", "height", "error"])
        writer.writeheader()
        for r in results:
            writer.writerow({
                "id": r["id"],
                "place": r["place"],
                "status": r["status"],
                "elapsed": r["elapsed"],
                "size": r.get("size", ""),
                "width": r.get("width", ""),
                "height": r.get("height", ""),
                "error": r.get("error", ""),
            })

    print(f"\n{'='*50}")
    print(f"完成: {ok_count}/{total} 成功")
    print(f"报告: {report_path}")
    print(f"CSV:  {csv_path}")
    if save_jpg:
        print(f"图片: {out_dir}/*.jpg")
    print(f"元数据: {out_dir}/*.meta.json")

    return report


def main():
    parser = argparse.ArgumentParser(description="批量截取沙盘 RTSP 摄像头画面")
    parser.add_argument("--cameras", nargs="*", default=None,
                        help="只截取指定摄像头（按 ID 或序号，如 live1 3 或 live1 live3）")
    parser.add_argument("--out-dir", default="captures", type=Path,
                        help="输出目录（默认 captures）")
    parser.add_argument("--timeout", type=int, default=12,
                        help="单个摄像头超时秒数（默认 12）")
    parser.add_argument("--no-jpg", action="store_true",
                        help="不保存 jpg 文件，只生成 JSON")
    args = parser.parse_args()

    # 选择摄像头子集
    cameras = CAMERA_PRESETS
    if args.cameras:
        selected = []
        for spec in args.cameras:
            # 按数字索引选择
            if spec.isdigit():
                idx = int(spec) - 1
                if 0 <= idx < len(CAMERA_PRESETS):
                    selected.append(CAMERA_PRESETS[idx])
                else:
                    print(f"警告: 序号 {spec} 超出范围（1-{len(CAMERA_PRESETS)}），已跳过")
                    continue
            # 按 ID 选择
            else:
                match = next((c for c in CAMERA_PRESETS if c["id"] == spec), None)
                if match:
                    selected.append(match)
                else:
                    print(f"警告: 未知摄像头 ID '{spec}'，已跳过")
        cameras = selected

    if not cameras:
        print("错误: 没有选择有效的摄像头")
        sys.exit(1)

    run_batch(cameras, args.out_dir, args.timeout, not args.no_jpg)


if __name__ == "__main__":
    main()
