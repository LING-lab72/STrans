"""Static road-modeler server and localhost-only RTSP single-frame bridge."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


TOOL_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = TOOL_ROOT.parents[1]
STATIC_ROOT = PROJECT_ROOT / "frontend" / "public" / "road_logic_modeler"
HOST = "127.0.0.1"
PORT = 8765
MAX_BODY = 64 * 1024


def validate_rtsp_url(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("RTSP 地址不能为空")
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"rtsp", "rtsps"} or not parsed.hostname:
        raise ValueError("只支持 rtsp:// 或 rtsps:// 地址")
    return url


def capture_frame(url: str) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，请先安装并加入 PATH")
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-timeout",
        "8000000",
        "-i",
        url,
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=12, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("连接摄像头超时") from exc
    if result.returncode != 0 or not result.stdout:
        detail = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise RuntimeError(detail[-1] if detail else "ffmpeg 未返回画面")
    return result.stdout


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        super().end_headers()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/health":
            self._json(200, {"data": {"status": "ok", "ffmpeg": bool(shutil.which("ffmpeg"))}})
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/rtsp/frame":
            self._error(404, "NOT_FOUND", "接口不存在")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                raise ValueError("请求内容大小无效")
            payload = json.loads(self.rfile.read(length))
            url = validate_rtsp_url(payload.get("url"))
            image = capture_frame(url)
            self._json(
                200,
                {
                    "data": {
                        "name": "rtsp-frame.jpg",
                        "dataUrl": "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii"),
                        "width": 0,
                        "height": 0,
                        "capturedAt": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                    }
                },
            )
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(422, "VALIDATION_ERROR", str(exc))
        except RuntimeError as exc:
            self._error(502, "CAPTURE_FAILED", str(exc))

    def _error(self, status: int, code: str, message: str) -> None:
        self._json(status, {"error": {"code": code, "message": message}})

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    if not (STATIC_ROOT / "index.html").exists():
        raise SystemExit(f"Road modeler static page not found: {STATIC_ROOT}")
    print(f"Road Logic Modeler: http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
