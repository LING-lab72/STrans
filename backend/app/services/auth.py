"""Compatibility exports for the active SQLite-backed authentication service."""

from app.services.auth_store import ADMIN_USERNAME, AuthStore, auth_store


__all__ = ["ADMIN_USERNAME", "AuthStore", "auth_store"]
