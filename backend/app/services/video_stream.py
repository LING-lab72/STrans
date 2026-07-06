from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Generator

import cv2


@dataclass
class VideoSnapshot:
    running: bool = False
    source: str | None = None
    connected: bool = False
    frame_width: int | None = None
    frame_height: int | None = None
    frames_received: int = 0
    fps: float = 0.0
    last_error: str | None = None


class VideoStreamService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture: cv2.VideoCapture | None = None
        self._latest_jpeg: bytes | None = None
        self._snapshot = VideoSnapshot()

    def start(self, source: str) -> VideoSnapshot:
        self.stop()
        self._stop_event.clear()
        with self._lock:
            self._latest_jpeg = None
            self._snapshot = VideoSnapshot(running=True, source=source)

        self._thread = threading.Thread(target=self._read_loop, args=(source,), daemon=True)
        self._thread.start()
        return self.status()

    def stop(self) -> VideoSnapshot:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

        if self._capture is not None:
            self._capture.release()
            self._capture = None

        with self._lock:
            self._snapshot.running = False
            self._snapshot.connected = False
        return self.status()

    def status(self) -> VideoSnapshot:
        with self._lock:
            return VideoSnapshot(**self._snapshot.__dict__)

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    def mjpeg_frames(self) -> Generator[bytes, None, None]:
        while True:
            if self._stop_event.is_set() and not self.status().running:
                time.sleep(0.2)

            frame = self.latest_jpeg()
            if frame is None:
                time.sleep(0.05)
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Cache-Control: no-cache\r\n\r\n" + frame + b"\r\n"
            )
            time.sleep(0.03)

    def _read_loop(self, source: str) -> None:
        capture_source: str | int = int(source) if source.isdigit() else source
        cap = cv2.VideoCapture(capture_source)
        self._capture = cap

        if not cap.isOpened():
            with self._lock:
                self._snapshot.running = False
                self._snapshot.connected = False
                self._snapshot.last_error = f"Cannot open video source: {source}"
            return

        started_at = time.time()
        last_fps_update = started_at
        last_frames = 0
        source_fps = cap.get(cv2.CAP_PROP_FPS)
        frame_interval = 1.0 / source_fps if source_fps and 1 <= source_fps <= 60 else 1.0 / 15.0

        with self._lock:
            self._snapshot.connected = True
            self._snapshot.last_error = None

        while not self._stop_event.is_set():
            loop_started = time.time()
            ok, frame = cap.read()
            if not ok or frame is None:
                with self._lock:
                    self._snapshot.connected = False
                    self._snapshot.last_error = "Frame read failed. Check phone/network/video URL."
                time.sleep(0.2)
                continue

            ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if not ok:
                with self._lock:
                    self._snapshot.last_error = "JPEG encoding failed."
                continue

            now = time.time()
            with self._lock:
                self._latest_jpeg = buffer.tobytes()
                self._snapshot.running = True
                self._snapshot.connected = True
                self._snapshot.frame_height, self._snapshot.frame_width = frame.shape[:2]
                self._snapshot.frames_received += 1
                self._snapshot.last_error = None
                if now - last_fps_update >= 1.0:
                    frames_delta = self._snapshot.frames_received - last_frames
                    self._snapshot.fps = round(frames_delta / (now - last_fps_update), 2)
                    last_frames = self._snapshot.frames_received
                    last_fps_update = now

            elapsed = time.time() - loop_started
            if elapsed < frame_interval:
                time.sleep(frame_interval - elapsed)

        cap.release()
        with self._lock:
            self._snapshot.running = False
            self._snapshot.connected = False
