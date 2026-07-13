from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import string
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = os.getenv("STRANS_ADMIN_PASSWORD", "admin123")


class AuthStore:
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
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    created_at TEXT NOT NULL,
                    last_login_at TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at)")
            try:
                conn.execute("ALTER TABLE users ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
            except sqlite3.OperationalError:
                pass
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    username TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT,
                    detail TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_logs(created_at DESC)")
            if self.get_user_by_username(ADMIN_USERNAME) is None:
                self.create_user(ADMIN_USERNAME, ADMIN_PASSWORD, role="admin")

    def _hash_password(self, password: str, salt: str | None = None) -> str:
        salt = salt or secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), 120_000)
        return f"pbkdf2_sha256${salt}${base64.b64encode(digest).decode('ascii')}"

    def _verify_password(self, password: str, stored_hash: str) -> bool:
        try:
            algorithm, salt, digest = stored_hash.split("$", 2)
        except ValueError:
            return False
        if algorithm != "pbkdf2_sha256":
            return False
        expected = self._hash_password(password, salt)
        return hmac.compare_digest(expected, stored_hash)

    def _row_to_user(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "role": row["role"],
            "created_at": row["created_at"],
            "last_login_at": row["last_login_at"],
            "enabled": bool(row["enabled"]) if "enabled" in row.keys() else True,
        }

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, username, password_hash, role, created_at, last_login_at, enabled FROM users WHERE username = ?",
                (username.strip(),),
            ).fetchone()
        return dict(row) if row else None

    def create_user(self, username: str, password: str, role: str = "user") -> dict[str, Any]:
        username = username.strip()
        if len(username) < 3:
            raise ValueError("用户名至少需要 3 个字符")
        if len(password) < 6:
            raise ValueError("密码至少需要 6 位")
        if role not in {"admin", "user"}:
            role = "user"
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO users (username, password_hash, role, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (username, self._hash_password(password), role, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("用户名已存在") from exc
            row = conn.execute(
                "SELECT id, username, role, created_at, last_login_at, enabled FROM users WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return self._row_to_user(row) or {}

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        row = self.get_user_by_username(username)
        if not row or not bool(row.get("enabled", 1)) or not self._verify_password(password, row["password_hash"]):
            return None
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, row["id"]))
            user = conn.execute(
                "SELECT id, username, role, created_at, last_login_at, enabled FROM users WHERE id = ?",
                (row["id"],),
            ).fetchone()
        return self._row_to_user(user)

    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now()
        expires_at = now + timedelta(hours=12)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO user_sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token, user_id, now.isoformat(timespec="seconds"), expires_at.isoformat(timespec="seconds")),
            )
        return token

    def get_user_by_token(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT users.id, users.username, users.role, users.created_at, users.last_login_at, users.enabled
                FROM user_sessions
                JOIN users ON users.id = user_sessions.user_id
                WHERE user_sessions.token = ? AND user_sessions.expires_at > ? AND users.enabled = 1
                """,
                (token, now),
            ).fetchone()
        return self._row_to_user(row)

    def delete_session(self, token: str | None) -> None:
        if not token:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))

    def list_users(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, username, role, created_at, last_login_at, enabled FROM users ORDER BY id"
            ).fetchall()
        return [self._row_to_user(row) or {} for row in rows]

    def update_user(self, user_id: int, *, role: str | None = None, enabled: bool | None = None) -> dict[str, Any]:
        fields: list[str] = []
        params: list[Any] = []
        if role is not None:
            if role not in {"admin", "user"}:
                raise ValueError("无效的用户角色")
            fields.append("role = ?")
            params.append(role)
        if enabled is not None:
            fields.append("enabled = ?")
            params.append(1 if enabled else 0)
        if not fields:
            raise ValueError("没有需要更新的字段")
        params.append(user_id)
        with self._connect() as conn:
            cursor = conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", params)
            if cursor.rowcount == 0:
                raise ValueError("用户不存在")
            if enabled is False:
                conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            row = conn.execute(
                "SELECT id, username, role, created_at, last_login_at, enabled FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return self._row_to_user(row) or {}

    def change_password(self, user_id: int, old_password: str, new_password: str) -> None:
        if len(new_password) < 6:
            raise ValueError("新密码至少需要 6 位")
        with self._connect() as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None or not self._verify_password(old_password, row["password_hash"]):
                raise ValueError("原密码不正确")
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (self._hash_password(new_password), user_id))
            conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))

    def reset_password(self, user_id: int, new_password: str) -> None:
        if len(new_password) < 6:
            raise ValueError("新密码至少需要 6 位")
        with self._connect() as conn:
            cursor = conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (self._hash_password(new_password), user_id))
            if cursor.rowcount == 0:
                raise ValueError("用户不存在")
            conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))

    def delete_user(self, user_id: int) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise ValueError("用户不存在")
            if row["username"] == ADMIN_USERNAME:
                raise ValueError("不能删除默认管理员账号")
            conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def add_audit(self, username: str, action: str, target: str = "", detail: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO audit_logs (created_at, username, action, target, detail) VALUES (?, ?, ?, ?, ?)",
                (datetime.now().isoformat(timespec="seconds"), username, action, target, detail),
            )

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, username, action, target, detail FROM audit_logs ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def new_captcha(self) -> dict[str, str]:
        alphabet = string.ascii_uppercase + string.digits
        text = "".join(secrets.choice(alphabet) for _ in range(4))
        captcha_id = secrets.token_urlsafe(12)
        now = datetime.now()
        expires_at = now + timedelta(minutes=5)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS login_captcha (
                    captcha_id TEXT PRIMARY KEY,
                    code TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO login_captcha (captcha_id, code, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (captcha_id, text, now.isoformat(timespec="seconds"), expires_at.isoformat(timespec="seconds")),
            )
        svg = self._captcha_svg(text)
        return {"captcha_id": captcha_id, "image": "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")}

    def verify_captcha(self, captcha_id: str, code: str) -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT code FROM login_captcha WHERE captcha_id = ? AND expires_at > ?",
                (captcha_id, now),
            ).fetchone()
            conn.execute("DELETE FROM login_captcha WHERE captcha_id = ?", (captcha_id,))
        return bool(row and hmac.compare_digest(str(row["code"]).upper(), code.strip().upper()))

    def _captcha_svg(self, text: str) -> str:
        noise = "".join(
            f"<line x1='{secrets.randbelow(140)}' y1='{secrets.randbelow(44)}' x2='{secrets.randbelow(140)}' y2='{secrets.randbelow(44)}' stroke='#9db2c5' stroke-width='1'/>"
            for _ in range(8)
        )
        chars = "".join(
            f"<text x='{18 + index * 28}' y='{30 + secrets.randbelow(6)}' fill='#0f2d45' font-size='24' font-weight='800' transform='rotate({secrets.randbelow(16) - 8} {18 + index * 28} 25)'>{char}</text>"
            for index, char in enumerate(text)
        )
        return f"<svg xmlns='http://www.w3.org/2000/svg' width='140' height='44' viewBox='0 0 140 44'><rect width='140' height='44' rx='8' fill='#eef7ff'/>{noise}{chars}</svg>"


auth_store = AuthStore()
