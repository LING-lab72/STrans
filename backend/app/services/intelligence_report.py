from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from app.services.sqlite_utils import open_sqlite


DEFAULT_API_BASE = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


class IntelligenceReportService:
    """Persisted DeepSeek configuration and AI-generated traffic reports."""

    def __init__(self, db_path: str | Path = "data/traffic_analysis.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return open_sqlite(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS intelligence_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    api_base TEXT NOT NULL,
                    model TEXT NOT NULL,
                    api_key TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS intelligence_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    created_by TEXT,
                    camera_id TEXT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_summary_json TEXT NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_intelligence_reports_created_at ON intelligence_reports(id DESC)")

    @staticmethod
    def _masked_key(value: str) -> str:
        if not value:
            return ""
        return "*" * max(0, len(value) - 4) + value[-4:]

    def get_config(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT api_base, model, api_key, updated_at FROM intelligence_config WHERE id = 1").fetchone()
        if row is None:
            return {
                "api_base": DEFAULT_API_BASE,
                "model": DEFAULT_MODEL,
                "configured": False,
                "api_key_masked": "",
                "updated_at": None,
            }
        return {
            "api_base": row["api_base"],
            "model": row["model"],
            "configured": bool(row["api_key"]),
            "api_key_masked": self._masked_key(row["api_key"]),
            "updated_at": row["updated_at"],
        }

    def update_config(self, api_base: str, model: str, api_key: str | None) -> dict[str, Any]:
        api_base = (api_base or DEFAULT_API_BASE).strip().rstrip("/")
        model = (model or DEFAULT_MODEL).strip()
        if not api_base.startswith(("https://", "http://")):
            raise ValueError("API 地址必须以 http:// 或 https:// 开头。")
        if not model:
            raise ValueError("模型名称不能为空。")
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as connection:
            existing = connection.execute("SELECT api_key FROM intelligence_config WHERE id = 1").fetchone()
            key = api_key.strip() if api_key and api_key.strip() else (existing["api_key"] if existing else "")
            connection.execute(
                """
                INSERT INTO intelligence_config (id, api_base, model, api_key, updated_at)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    api_base = excluded.api_base,
                    model = excluded.model,
                    api_key = excluded.api_key,
                    updated_at = excluded.updated_at
                """,
                (api_base, model, key, now),
            )
        return self.get_config()

    def list_reports(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, created_at, created_by, camera_id, title, content, model, input_summary_json
                FROM intelligence_reports ORDER BY id DESC LIMIT ?
                """,
                (max(1, min(limit, 100)),),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["input_summary"] = json.loads(item.pop("input_summary_json") or "{}")
            items.append(item)
        return items

    def delete_report(self, report_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM intelligence_reports WHERE id = ?", (report_id,))
        return cursor.rowcount > 0

    def generate(self, context: dict[str, Any], created_by: str | None) -> dict[str, Any]:
        with self._connect() as connection:
            config = connection.execute("SELECT api_base, model, api_key FROM intelligence_config WHERE id = 1").fetchone()
        if config is None or not config["api_key"]:
            raise ValueError("尚未配置 DeepSeek API Key，请由管理员在智能报告页完成配置。")

        prompt = self._build_prompt(context)
        try:
            response = httpx.post(
                f"{config['api_base'].rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"},
                json={
                    "model": config["model"],
                    "temperature": 0.25,
                    "max_tokens": 1300,
                    "messages": [
                        {"role": "system", "content": "你是交通监测系统分析助手。只能依据提供的数据总结，不得编造未检测到的事实。请使用简洁、专业的中文 Markdown。"},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=35.0,
            )
            response.raise_for_status()
            payload = response.json()
            content = str(payload["choices"][0]["message"]["content"]).strip()
        except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"DeepSeek 调用失败：{exc}") from exc

        if not content:
            raise RuntimeError("DeepSeek 未返回报告内容。")
        now = datetime.now().isoformat(timespec="seconds")
        camera_id = context.get("camera_id")
        title = f"{context.get('camera_name') or camera_id or '当前视角'}交通智能分析报告"
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO intelligence_reports (created_at, created_by, camera_id, title, content, model, input_summary_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (now, created_by, camera_id, title, content, config["model"], json.dumps(context, ensure_ascii=False)),
            )
            report_id = int(cursor.lastrowid)
        return {
            "id": report_id,
            "created_at": now,
            "created_by": created_by,
            "camera_id": camera_id,
            "title": title,
            "content": content,
            "model": config["model"],
            "input_summary": context,
        }

    @staticmethod
    def _build_prompt(context: dict[str, Any]) -> str:
        instructions = (
            "请依据下列 STrans 沙盘交通监测快照生成一次分析报告。\n\n"
            "报告固定包含：\n"
            "1. 总体态势（1 段）；\n"
            "2. 检测摘要（车辆、车牌、拥堵、速度、推理耗时）；\n"
            "3. 事件与风险（只列有证据的事件）；\n"
            "4. 处置建议（2-4 条，可执行）；\n"
            "5. 数据局限说明（如静态画面、模型误检、车牌不稳定等）。\n\n"
            "不要重复 JSON；不要将‘未检测到’写成‘不存在’；数据不足时明确说明。\n\n"
            "监测快照：\n"
        )
        return instructions + json.dumps(context, ensure_ascii=False, indent=2)


intelligence_report_service = IntelligenceReportService()
