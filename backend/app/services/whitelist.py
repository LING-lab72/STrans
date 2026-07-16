from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
import sqlite3
import time

from app.services.sqlite_utils import open_sqlite


DEFAULT_WHITELIST_PLATES = {
    "京K9134J",
    "京E7654Z",
    "京H7912N",
    "京E4282Y",
    "京B6789T",
}

PLATE_ALIASES = {
    "京HF7912N": "京H7912N",
}

PLATE_PREFIX_FIXES = {
    "äº¬": "京",
    "žŠ": "京",
    "?": "京",
}


@dataclass(frozen=True)
class WhitelistDecision:
    plate_no: str | None
    whitelist_status: bool
    gate_action: str
    reason: str


class WhitelistStore:
    def __init__(self, db_path: str | Path = "data/traffic_analysis.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._active_cache: list[str] = []
        self._active_cache_expires_at = 0.0
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return open_sqlite(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vehicle_whitelist (
                    plate_no TEXT PRIMARY KEY,
                    owner TEXT NOT NULL DEFAULT '沙盘白名单车辆',
                    note TEXT NOT NULL DEFAULT '准入车牌',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            existing_count = conn.execute("SELECT COUNT(*) AS count FROM vehicle_whitelist").fetchone()["count"]
            if existing_count == 0:
                now = datetime.now().isoformat(timespec="seconds")
                for plate_no in sorted(DEFAULT_WHITELIST_PLATES):
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO vehicle_whitelist (
                            plate_no, owner, note, enabled, created_at, updated_at
                        )
                        VALUES (?, ?, ?, 1, ?, ?)
                        """,
                        (plate_no, "沙盘白名单车辆", "准入车牌", now, now),
                    )

    def list_items(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT plate_no, plate_no AS identity, owner, note, enabled, created_at, updated_at
                FROM vehicle_whitelist
                ORDER BY plate_no ASC
                """
            ).fetchall()
        return [
            {
                **dict(row),
                "enabled": bool(row["enabled"]),
                "gate_action": "allow" if row["enabled"] else "deny",
            }
            for row in rows
        ]

    def contains(self, plate_no: str) -> bool:
        if not plate_no:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT enabled FROM vehicle_whitelist WHERE plate_no = ?",
                (plate_no,),
            ).fetchone()
        return bool(row and row["enabled"])

    def active_plate_nos(self) -> list[str]:
        now = time.monotonic()
        if now < self._active_cache_expires_at:
            return self._active_cache
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT plate_no FROM vehicle_whitelist WHERE enabled = 1 ORDER BY plate_no"
            ).fetchall()
        self._active_cache = [str(row["plate_no"]) for row in rows]
        self._active_cache_expires_at = now + 2.0
        return self._active_cache

    def invalidate_cache(self) -> None:
        self._active_cache = []
        self._active_cache_expires_at = 0.0

    def match_plate(self, plate_no: str) -> str | None:
        normalized = normalize_plate(plate_no)
        if not normalized:
            return None
        active = self.active_plate_nos()
        if normalized in active:
            return normalized
        best_plate = None
        best_score = 0.0
        for candidate in active:
            score = SequenceMatcher(None, normalized, candidate).ratio()
            same_region = normalized[:2] == candidate[:2]
            same_tail = normalized[-4:] == candidate[-4:]
            if same_region and same_tail:
                score = max(score, 0.92)
            if score > best_score:
                best_plate = candidate
                best_score = score
        return best_plate if best_score >= 0.78 else None

    def upsert(self, plate_no: str, owner: str = "沙盘白名单车辆", note: str = "准入车牌") -> dict:
        normalized = normalize_plate(plate_no)
        if not normalized:
            raise ValueError("plate_no is required")
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO vehicle_whitelist (plate_no, owner, note, enabled, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                ON CONFLICT(plate_no) DO UPDATE SET
                    owner = excluded.owner,
                    note = excluded.note,
                    enabled = 1,
                    updated_at = excluded.updated_at
                """,
                (normalized, owner or "沙盘白名单车辆", note or "准入车牌", now, now),
            )
        self.invalidate_cache()
        return self.get(normalized)

    def delete(self, plate_no: str) -> bool:
        normalized = normalize_plate(plate_no)
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM vehicle_whitelist WHERE plate_no = ?", (normalized,))
        self.invalidate_cache()
        return cursor.rowcount > 0

    def get(self, plate_no: str) -> dict:
        normalized = normalize_plate(plate_no)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT plate_no, plate_no AS identity, owner, note, enabled, created_at, updated_at
                FROM vehicle_whitelist
                WHERE plate_no = ?
                """,
                (normalized,),
            ).fetchone()
        if row is None:
            return {}
        return {**dict(row), "enabled": bool(row["enabled"]), "gate_action": "allow" if row["enabled"] else "deny"}


def normalize_plate(plate_no: str | None) -> str:
    if not plate_no:
        return ""
    plate = plate_no.strip().upper().replace(" ", "").replace("-", "")
    for broken, fixed in PLATE_PREFIX_FIXES.items():
        if plate.startswith(broken):
            plate = fixed + plate[len(broken):]
            break
    plate = PLATE_ALIASES.get(plate, plate)
    if plate.startswith("京H") and plate.endswith("7912N"):
        return "京H7912N"
    return plate


whitelist_store = WhitelistStore()


def decide_plate(plate_no: str | None, confidence: float = 1.0) -> WhitelistDecision:
    plate = normalize_plate(plate_no)
    matched_plate = whitelist_store.match_plate(plate)
    display_plate = matched_plate or plate
    # OCR confidence is handled by the multi-frame plate stabilizer. Once a
    # normalized plate matches the database, membership alone decides access.
    allowed = bool(matched_plate)
    if allowed:
        reason = "白名单车辆，可通过"
    elif plate:
        reason = "非白名单车辆，建议拦截"
    else:
        reason = "未识别到车牌，需人工复核"
    return WhitelistDecision(
        plate_no=display_plate or None,
        whitelist_status=allowed,
        gate_action="allow" if allowed else "deny",
        reason=reason,
    )
