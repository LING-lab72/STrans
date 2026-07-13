from __future__ import annotations

import csv
import json
import sqlite3
from io import StringIO
from pathlib import Path
from typing import Any

from app.schemas.dashboard import AnalysisResult


class AnalysisStore:
    def __init__(self, db_path: str | Path = "data/traffic_analysis.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    camera_id TEXT,
                    frame_id INTEGER,
                    model_id TEXT,
                    vehicle_count INTEGER NOT NULL DEFAULT 0,
                    current_count INTEGER NOT NULL DEFAULT 0,
                    count_in INTEGER NOT NULL DEFAULT 0,
                    count_out INTEGER NOT NULL DEFAULT 0,
                    density REAL NOT NULL DEFAULT 0,
                    avg_speed REAL,
                    congestion_level TEXT,
                    detection_count INTEGER NOT NULL DEFAULT 0,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    inference_ms REAL,
                    plates TEXT,
                    whitelist_pass_count INTEGER NOT NULL DEFAULT 0,
                    whitelist_block_count INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL
                )
                """
            )
            for statement in [
                "ALTER TABLE analysis_records ADD COLUMN plates TEXT",
                "ALTER TABLE analysis_records ADD COLUMN whitelist_pass_count INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE analysis_records ADD COLUMN whitelist_block_count INTEGER NOT NULL DEFAULT 0",
            ]:
                try:
                    conn.execute(statement)
                except sqlite3.OperationalError:
                    pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_created_at ON analysis_records(created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_camera_id ON analysis_records(camera_id)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_incidents (
                    event_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    camera_id TEXT,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    handled_by TEXT,
                    handled_at TEXT,
                    note TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_incident_created_at ON alert_incidents(created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_incident_status ON alert_incidents(status)")
            recent_payloads = conn.execute(
                "SELECT camera_id, payload_json FROM analysis_records ORDER BY id DESC LIMIT 200"
            ).fetchall()
            for record in recent_payloads:
                try:
                    payload = json.loads(record["payload_json"])
                except (TypeError, json.JSONDecodeError):
                    continue
                for event in payload.get("events") or []:
                    event_id = str(event.get("event_id") or "").strip()
                    if not event_id:
                        continue
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO alert_incidents (
                            event_id, created_at, camera_id, event_type, severity, description
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event_id,
                            event.get("created_at") or payload.get("timestamp") or "",
                            event.get("camera_id") or record["camera_id"],
                            event.get("type") or "unknown",
                            event.get("severity") or "info",
                            event.get("description") or "",
                        ),
                    )

    def save(self, result: AnalysisResult) -> int:
        stats = result.traffic_stats
        payload = result.model_dump(mode="json")
        created_at = result.timestamp or payload.get("timestamp") or ""
        plates = sorted({item.plate for item in result.detections if item.plate})
        whitelist_pass_count = len([item for item in result.detections if item.whitelist_status is True])
        whitelist_block_count = len([item for item in result.detections if item.whitelist_status is False])
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO analysis_records (
                    created_at, camera_id, frame_id, model_id, vehicle_count, current_count,
                    count_in, count_out, density, avg_speed, congestion_level, detection_count,
                    event_count, inference_ms, plates, whitelist_pass_count, whitelist_block_count, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    result.camera_id,
                    result.frame_id,
                    result.model_id,
                    stats.vehicle_count,
                    stats.current_count,
                    stats.count_in,
                    stats.count_out,
                    stats.density,
                    stats.avg_speed,
                    stats.congestion_level,
                    len(result.detections),
                    len(result.events),
                    result.inference_ms,
                    ",".join(plates),
                    whitelist_pass_count,
                    whitelist_block_count,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            for event in result.events:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO alert_incidents (
                        event_id, created_at, camera_id, event_type, severity, description
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (event.event_id, event.created_at, event.camera_id or result.camera_id, event.type, event.severity, event.description),
                )
            return int(cursor.lastrowid)

    def list_records(self, limit: int = 30, camera_id: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        params: list[Any] = []
        where = ""
        if camera_id:
            where = "WHERE camera_id = ?"
            params.append(camera_id)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, created_at, camera_id, frame_id, model_id, vehicle_count, current_count,
                       count_in, count_out, density, avg_speed, congestion_level, detection_count,
                       event_count, inference_ms, plates, whitelist_pass_count, whitelist_block_count
                FROM analysis_records
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def export_csv(self, limit: int = 1000) -> str:
        rows = self.list_records(limit=limit)
        output = StringIO()
        fieldnames = [
            "id",
            "created_at",
            "camera_id",
            "frame_id",
            "model_id",
            "vehicle_count",
            "current_count",
            "count_in",
            "count_out",
            "density",
            "avg_speed",
            "congestion_level",
            "detection_count",
            "event_count",
            "inference_ms",
            "plates",
            "whitelist_pass_count",
            "whitelist_block_count",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()

    def export_json(self, limit: int = 1000) -> str:
        rows = self.list_records(limit=limit)
        return json.dumps({"items": rows}, ensure_ascii=False, indent=2)

    def count_records(self, camera_id: str | None = None) -> int:
        params: list[Any] = []
        where = ""
        if camera_id:
            where = "WHERE camera_id = ?"
            params.append(camera_id)
        with self._connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS total FROM analysis_records {where}", params).fetchone()
        return int(row["total"] if row else 0)

    def delete_record(self, record_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM analysis_records WHERE id = ?", (record_id,))
        return cursor.rowcount > 0

    def purge_records(self, before: str | None = None) -> int:
        with self._connect() as conn:
            if before:
                cursor = conn.execute("DELETE FROM analysis_records WHERE created_at < ?", (before,))
            else:
                cursor = conn.execute("DELETE FROM analysis_records")
        return int(cursor.rowcount)

    def list_incidents(self, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        params.append(max(1, min(limit, 500)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT event_id, created_at, camera_id, event_type, severity, description,
                       status, handled_by, handled_at, note
                FROM alert_incidents {where}
                ORDER BY created_at DESC LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def update_incident(self, event_id: str, status: str, handled_by: str, note: str = "") -> dict[str, Any]:
        if status not in {"pending", "confirmed", "resolved", "false_positive"}:
            raise ValueError("无效的告警状态")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE alert_incidents
                SET status = ?, handled_by = ?, handled_at = datetime('now', 'localtime'), note = ?
                WHERE event_id = ?
                """,
                (status, handled_by, note.strip(), event_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("告警记录不存在")
            row = conn.execute("SELECT * FROM alert_incidents WHERE event_id = ?", (event_id,)).fetchone()
        return dict(row) if row else {}
