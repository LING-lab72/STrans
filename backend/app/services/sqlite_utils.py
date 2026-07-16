from __future__ import annotations

import sqlite3
from pathlib import Path
from types import TracebackType


class ClosingSQLiteConnection(sqlite3.Connection):
    """Commit or roll back like sqlite3.Connection, then always release the file."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


def open_sqlite(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, factory=ClosingSQLiteConnection)
    connection.row_factory = sqlite3.Row
    return connection
