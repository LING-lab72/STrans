from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

import cv2


STATIC_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def safe_source_label(source: str | None) -> str | None:
    if source is None or source.isdigit():
        return source
    return "configured video source"


def redact_stream_error(message: str | None, source: str | None) -> str | None:
    if not message:
        return message
    if not source:
        return message
    return message.replace(source, safe_source_label(source) or "video source")


@dataclass
class VideoSnapshot:
    running: bool = False
    source: str | None = None
    connected: bool = False
    frame_width: int | None = None
    frame_height: int | None = None
    frames_received: int = 0
    fps: float = 0.0
    is_static_image: bool = False
    last_error: str | None = None


class VideoStreamService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture: cv2.VideoCapture | None = None
        self._latest_jpeg: bytes | None = None
        self._snapshot = VideoSnapshot()
        self._generation = 0
        self._last_frame_at = 0.0
        self._static_image_source = False

    def start(self, source: str) -> VideoSnapshot:
        with self._lifecycle_lock:
            with self._lock:
                # Starting an already active source must be cheap. Recreating
                # an OpenCV capture on every click leaves old RTSP/MJPEG
                # consumers behind and is the main cause of repeated-switch
                # instability.
                if (
                    self._snapshot.running
                    and self._snapshot.connected
                    and self._snapshot.source == source
                    and self._thread is not None
                    and self._thread.is_alive()
                ):
                    return VideoSnapshot(**self._snapshot.__dict__)
            self._shutdown_locked()
            stop_event = threading.Event()
            with self._lock:
                self._stop_event = stop_event
                self._latest_jpeg = None
                self._last_frame_at = 0.0
                self._static_image_source = False
                self._snapshot = VideoSnapshot(running=True, source=source)
                generation = self._generation
                thread = threading.Thread(
                    target=self._read_loop,
                    args=(source, generation, stop_event),
                    daemon=True,
                )
                self._thread = thread
            thread.start()
        return self.status()

    def stop(self) -> VideoSnapshot:
        with self._lifecycle_lock:
            self._shutdown_locked()
        return self.status()

    def _shutdown_locked(self) -> None:
        with self._lock:
            self._generation += 1
            stop_event = self._stop_event
            thread = self._thread
            capture = self._capture
            self._thread = None
            self._capture = None
            self._latest_jpeg = None
            self._last_frame_at = 0.0
            self._static_image_source = False
            self._snapshot.running = False
            self._snapshot.connected = False
        stop_event.set()
        if capture is not None:
            capture.release()
        if thread and thread.is_alive() and thread is not threading.current_thread():
            # OpenCV reads can occasionally take a moment to return after an
            # RTSP disconnect. The generation token prevents a late thread
            # from publishing frames, so do not freeze the API for seconds.
            thread.join(timeout=0.8)

    def status(self) -> VideoSnapshot:
        with self._lock:
            if (
                self._snapshot.running
                and self._snapshot.connected
                and not self._static_image_source
                and self._last_frame_at
                and time.monotonic() - self._last_frame_at > 3.0
            ):
                self._snapshot.connected = False
                self._snapshot.last_error = "Video stream stalled: no valid frame received for 3 seconds."
            snapshot = VideoSnapshot(**self._snapshot.__dict__)
            snapshot.source = safe_source_label(snapshot.source)
            snapshot.last_error = redact_stream_error(snapshot.last_error, self._snapshot.source)
            return snapshot

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    def mjpeg_frames(self) -> Generator[bytes, None, None]:
        with self._lock:
            generation = self._generation
            stop_event = self._stop_event
        while not stop_event.is_set() and self._is_current(generation):
            frame = self.latest_jpeg()
            if frame is None:
                if not self.status().running:
                    return
                time.sleep(0.05)
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Cache-Control: no-cache\r\n\r\n" + frame + b"\r\n"
            )
            time.sleep(0.03)

    def _is_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def _open_capture(self, capture_source: str | int) -> cv2.VideoCapture:
        if isinstance(capture_source, str) and capture_source.startswith("rtsp://"):
            # Keep decoder buffering minimal. The service itself is a one-frame
            # latest-frame buffer, so queued RTSP packets only add latency.
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;0"
            )
            capture = cv2.VideoCapture(capture_source, cv2.CAP_FFMPEG)
        else:
            capture = cv2.VideoCapture(capture_source)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        for property_name, timeout_ms in (("CAP_PROP_OPEN_TIMEOUT_MSEC", 3000), ("CAP_PROP_READ_TIMEOUT_MSEC", 3000)):
            property_id = getattr(cv2, property_name, None)
            if property_id is not None:
                capture.set(property_id, timeout_ms)
        return capture

    def _read_loop(self, source: str, generation: int, stop_event: threading.Event) -> None:
        capture_source: str | int = int(source) if source.isdigit() else source
        if isinstance(capture_source, str) and not capture_source.startswith(("http://", "https://", "rtsp://")):
            candidate = Path(capture_source)
            if not candidate.is_absolute():
                backend_root = Path(__file__).resolve().parents[2]
                candidate = backend_root / candidate
            if candidate.exists():
                capture_source = str(candidate)
        is_file_source = isinstance(capture_source, str) and Path(capture_source).exists()
        is_static_image = is_file_source and Path(str(capture_source)).suffix.lower() in STATIC_IMAGE_EXTENSIONS
        reconnect_delay = 0.6

        if is_static_image:
            # A JPG/PNG has one valid frame by design. Keep it available for
            # repeated model analysis, but never treat the lack of later frames
            # as a broken RTSP/video stream or trigger reconnect handling.
            frame = cv2.imread(str(capture_source))
            if frame is None:
                with self._lock:
                    if generation == self._generation:
                        self._snapshot.running = False
                        self._snapshot.connected = False
                        self._snapshot.last_error = f"Cannot decode image source: {safe_source_label(source)}"
                return
            encoded, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            if not encoded:
                with self._lock:
                    if generation == self._generation:
                        self._snapshot.running = False
                        self._snapshot.connected = False
                        self._snapshot.last_error = "JPEG encoding failed for image source."
                return
            with self._lock:
                if generation != self._generation:
                    return
                self._static_image_source = True
                self._latest_jpeg = buffer.tobytes()
                self._last_frame_at = time.monotonic()
                self._snapshot.running = True
                self._snapshot.connected = True
                self._snapshot.is_static_image = True
                self._snapshot.frame_height, self._snapshot.frame_width = frame.shape[:2]
                self._snapshot.frames_received = 1
                self._snapshot.fps = 0.0
                self._snapshot.last_error = None
            while not stop_event.wait(0.5) and self._is_current(generation):
                pass
            return

        while not stop_event.is_set() and self._is_current(generation):
            cap = self._open_capture(capture_source)
            with self._lock:
                if generation != self._generation:
                    cap.release()
                    return
                self._capture = cap

            if not cap.isOpened():
                with self._lock:
                    if generation == self._generation:
                        self._snapshot.connected = False
                        self._snapshot.last_error = f"Cannot open video source: {safe_source_label(source)}"
                cap.release()
                if is_file_source:
                    break
                stop_event.wait(reconnect_delay)
                continue

            last_fps_update = time.monotonic()
            last_frames = self.status().frames_received
            source_fps = cap.get(cv2.CAP_PROP_FPS)
            frame_interval = 1.0 / source_fps if source_fps and 1 <= source_fps <= 60 else 1.0 / 15.0
            consecutive_failures = 0

            while not stop_event.is_set() and self._is_current(generation):
                loop_started = time.monotonic()
                try:
                    ok, frame = cap.read()
                except cv2.error as error:
                    # Network cameras may throw a native OpenCV exception while
                    # a stream is being closed or reconfigured. Keep that fault
                    # isolated to this camera and let the outer loop reconnect.
                    with self._lock:
                        if generation == self._generation:
                            self._snapshot.connected = False
                            self._snapshot.last_error = f"OpenCV frame read failed; reconnecting: {error}"
                            self._latest_jpeg = None
                    break
                if not ok or frame is None or frame.size == 0:
                    if is_file_source:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        stop_event.wait(frame_interval)
                        continue
                    consecutive_failures += 1
                    with self._lock:
                        if generation == self._generation:
                            self._snapshot.connected = False
                            self._snapshot.last_error = "Frame read failed; reconnecting video source."
                            if consecutive_failures >= 3:
                                self._latest_jpeg = None
                    if consecutive_failures >= 5:
                        break
                    stop_event.wait(0.2)
                    continue

                encoded, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if not encoded:
                    with self._lock:
                        if generation == self._generation:
                            self._snapshot.last_error = "JPEG encoding failed."
                    continue

                now = time.monotonic()
                with self._lock:
                    if generation != self._generation:
                        break
                    consecutive_failures = 0
                    self._latest_jpeg = buffer.tobytes()
                    self._last_frame_at = now
                    self._snapshot.running = True
                    self._snapshot.connected = True
                    self._snapshot.is_static_image = False
                    self._snapshot.frame_height, self._snapshot.frame_width = frame.shape[:2]
                    self._snapshot.frames_received += 1
                    self._snapshot.last_error = None
                    if now - last_fps_update >= 1.0:
                        frames_delta = self._snapshot.frames_received - last_frames
                        self._snapshot.fps = round(frames_delta / (now - last_fps_update), 2)
                        last_frames = self._snapshot.frames_received
                        last_fps_update = now

                elapsed = time.monotonic() - loop_started
                # Local files need pacing; live streams should be drained as fast
                # as decoded so inference always receives the newest frame.
                if is_file_source and elapsed < frame_interval:
                    stop_event.wait(frame_interval - elapsed)

            cap.release()
            with self._lock:
                if self._capture is cap:
                    self._capture = None
            if not is_file_source and not stop_event.is_set():
                stop_event.wait(reconnect_delay)

        with self._lock:
            if generation == self._generation:
                self._capture = None
                self._snapshot.running = False
                self._snapshot.connected = False
