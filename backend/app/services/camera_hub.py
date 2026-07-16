from __future__ import annotations

import threading
import sqlite3
import time
from pathlib import Path

from app.schemas.video import CameraCreateRequest, CameraSource, CameraStatusItem, CameraUpdateRequest, VideoStatus
from app.services.sqlite_utils import open_sqlite
from app.services.video_stream import VideoStreamService


SANDTABLE_CAMERAS: list[CameraSource] = [
    CameraSource(camera_id="live1", name="桥面", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live1", location="沙盘桥面"),
    CameraSource(camera_id="live2", name="停车场出口", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live2", location="停车场出口"),
    CameraSource(camera_id="live3", name="行人检测", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live3", location="行人检测区"),
    CameraSource(camera_id="live4", name="消防车识别", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live4", location="消防车识别区"),
    CameraSource(camera_id="live5", name="桥出口", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live5", location="桥出口"),
    CameraSource(camera_id="live6", name="桥入口", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live6", location="桥入口"),
    CameraSource(camera_id="live7", name="道路 2", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live7", location="道路 2"),
    CameraSource(camera_id="live8", name="隧道事故识别", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live8", location="隧道事故识别"),
    CameraSource(camera_id="live9", name="隧道车辆数量", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live9", location="隧道车辆数量"),
    CameraSource(camera_id="live10", name="道路 3", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live10", location="道路 3"),
    CameraSource(camera_id="live11", name="停车场入口", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live11", location="停车场入口"),
    CameraSource(camera_id="live12", name="道路 1", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live12", location="道路 1"),
]

MAX_ACTIVE_STREAMS = 4


class CameraHub:
    def __init__(self, db_path: str | Path = "data/traffic_analysis.db") -> None:
        self._lock = threading.RLock()
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._sources: dict[str, CameraSource] = {item.camera_id: item for item in SANDTABLE_CAMERAS}
        self._streams: dict[str, VideoStreamService] = {item.camera_id: VideoStreamService() for item in SANDTABLE_CAMERAS}
        self.current_camera_id: str = "live1"
        self._start_order: list[str] = []
        self._init_db()
        self._load_custom_sources()

    def _connect(self) -> sqlite3.Connection:
        return open_sqlite(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS camera_sources (
                    camera_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    stream_url TEXT NOT NULL,
                    location TEXT NOT NULL,
                    description TEXT,
                    heatmap_mode TEXT NOT NULL DEFAULT 'auto',
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(camera_sources)").fetchall()}
            if "heatmap_mode" not in columns:
                conn.execute("ALTER TABLE camera_sources ADD COLUMN heatmap_mode TEXT NOT NULL DEFAULT 'auto'")

    def _load_custom_sources(self) -> None:
        with self._connect() as conn:
            rows = conn.execute("SELECT camera_id, name, type, stream_url, location, description, heatmap_mode FROM camera_sources").fetchall()
        for row in rows:
            source = CameraSource(**dict(row), status="offline")
            self._sources[source.camera_id] = source
            self._streams[source.camera_id] = VideoStreamService()

    def _persist_source(self, source: CameraSource) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO camera_sources (camera_id, name, type, stream_url, location, description, heatmap_mode)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(camera_id) DO UPDATE SET
                    name = excluded.name, type = excluded.type, stream_url = excluded.stream_url,
                    location = excluded.location, description = excluded.description, heatmap_mode = excluded.heatmap_mode,
                    updated_at = datetime('now', 'localtime')
                """,
                (source.camera_id, source.name, source.type, source.stream_url, source.location, source.description, source.heatmap_mode),
            )

    def list_sources(self) -> list[CameraSource]:
        result = []
        for camera_id, source in self._sources.items():
            status = self._streams[camera_id].status()
            result.append(
                source.model_copy(
                    update={
                        "status": (
                            "online"
                            if status.connected
                            else "error"
                            if status.last_error
                            else "connecting"
                            if status.running
                            else "offline"
                        ),
                        "selected": camera_id == self.current_camera_id,
                    }
                )
            )
        return result

    def get_source(self, camera_id: str) -> CameraSource:
        return self._sources[camera_id]

    def add_source(self, req: CameraCreateRequest) -> CameraSource:
        with self._lock:
            suffix = 1
            while f"custom{suffix}" in self._sources:
                suffix += 1
            camera_id = f"custom{suffix}"
            source = CameraSource(camera_id=camera_id, **req.model_dump(), status="offline")
            self._sources[camera_id] = source
            self._streams[camera_id] = VideoStreamService()
            self._persist_source(source)
            return source

    def update_source(self, camera_id: str, req: CameraUpdateRequest) -> CameraSource:
        with self._lock:
            if camera_id not in self._sources:
                raise KeyError(camera_id)
            current = self._sources[camera_id]
            updates = {key: value for key, value in req.model_dump().items() if value is not None}
            if updates.get("stream_url") and self._streams[camera_id].status().running:
                self._streams[camera_id].stop()
                self._start_order = [item for item in self._start_order if item != camera_id]
            source = current.model_copy(update={**updates, "status": "offline", "selected": False})
            self._sources[camera_id] = source
            self._persist_source(source)
            return source

    def delete_source(self, camera_id: str) -> None:
        if camera_id.startswith("live"):
            raise ValueError("预置沙盘摄像头不能删除")
        with self._lock:
            if camera_id not in self._sources:
                raise KeyError(camera_id)
            self._streams[camera_id].stop()
            self._streams.pop(camera_id, None)
            self._sources.pop(camera_id, None)
            self._start_order = [item for item in self._start_order if item != camera_id]
            with self._connect() as conn:
                conn.execute("DELETE FROM camera_sources WHERE camera_id = ?", (camera_id,))

    def test_source(self, camera_id: str, timeout_seconds: float = 4.0) -> dict[str, object]:
        if camera_id not in self._sources:
            raise KeyError(camera_id)
        source = self._sources[camera_id]
        probe = VideoStreamService()
        probe.start(source.stream_url)
        deadline = time.monotonic() + max(1.0, min(timeout_seconds, 8.0))
        status = probe.status()
        while time.monotonic() < deadline and not status.connected and not status.last_error:
            time.sleep(0.1)
            status = probe.status()
        probe.stop()
        return {
            "ok": bool(status.connected),
            "camera_id": camera_id,
            "message": "连接成功" if status.connected else (status.last_error or "连接超时"),
            "frame_width": status.frame_width,
            "frame_height": status.frame_height,
            "fps": status.fps,
        }

    def start(self, camera_id: str) -> VideoStatus:
        with self._lock:
            source = self._sources[camera_id]
            stream = self._streams[camera_id]
            current_status = stream.status()
            if current_status.running and current_status.connected:
                self.current_camera_id = camera_id
                self._start_order = [item for item in self._start_order if item != camera_id]
                self._start_order.append(camera_id)
                return VideoStatus(**current_status.__dict__)
            active_ids = [
                active_id
                for active_id in self._start_order
                if active_id in self._streams and self._streams[active_id].status().running
            ]
            while len(active_ids) >= MAX_ACTIVE_STREAMS:
                oldest_id = active_ids.pop(0)
                if oldest_id != camera_id:
                    self._streams[oldest_id].stop()
                    self._start_order = [item for item in self._start_order if item != oldest_id]
            self.current_camera_id = camera_id
            self._start_order = [item for item in self._start_order if item != camera_id]
            self._start_order.append(camera_id)
            return VideoStatus(**stream.start(source.stream_url).__dict__)

    def start_custom(self, source: str, name: str | None = None, location: str | None = None) -> CameraSource:
        req = CameraCreateRequest(
            name=name or "手动视频源",
            type="phone" if source.startswith(("http://", "https://")) else "custom",
            stream_url=source,
            location=location or "手动接入",
            description="手动输入的视频源，可用于手机 IP Webcam、USB 摄像头或本地视频。",
        )
        camera = self.add_source(req)
        self.start(camera.camera_id)
        return camera

    def stop(self, camera_id: str) -> VideoStatus:
        with self._lock:
            self._start_order = [item for item in self._start_order if item != camera_id]
            return VideoStatus(**self._streams[camera_id].stop().__dict__)

    def stop_all(self) -> list[CameraStatusItem]:
        for stream in self._streams.values():
            stream.stop()
        self._start_order = []
        return self.status_all()

    def status(self, camera_id: str) -> VideoStatus:
        return VideoStatus(**self._streams[camera_id].status().__dict__)

    def status_all(self) -> list[CameraStatusItem]:
        return [
            CameraStatusItem(camera_id=camera_id, status=VideoStatus(**stream.status().__dict__))
            for camera_id, stream in self._streams.items()
        ]

    def mjpeg_frames(self, camera_id: str):
        return self._streams[camera_id].mjpeg_frames()

    def latest_jpeg(self, camera_id: str) -> bytes | None:
        return self._streams[camera_id].latest_jpeg()
