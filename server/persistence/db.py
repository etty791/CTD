"""SQLite connection + schema for the persistence layer."""

import sqlite3

from server.persistence.persistence_config import SQL_CREATE_USERS


class Database:
    """Owns a single sqlite3 connection to ``db_path``."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """Open (once) and return the connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
        return self._conn

    @property
    def connection(self) -> sqlite3.Connection:
        return self.connect()

    def init_schema(self) -> None:
        conn = self.connect()
        with conn:
            conn.execute(SQL_CREATE_USERS)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
