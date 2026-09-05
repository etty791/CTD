"""Configuration, constants, and reason vocabulary for the persistence layer.

Single home for every persistence constant (DB location, scrypt parameters,
SQL statements, result reasons). Kept pure and importable: reading this module
must not touch the filesystem (no directory creation) so it can be imported
freely in tests and tooling.
"""

import os
from enum import StrEnum

from server.elo import DEFAULT_RATING

# --- Database location ---
DB_ENV_VAR = "CTD_DB_PATH"
DEFAULT_DB_DIR = "server/data"
DEFAULT_DB_FILENAME = "ctd.db"

# --- scrypt hashing parameters ---
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64
SALT_BYTES = 16

# --- SQL ---
# DEFAULT_RATING lives in server.elo; interpolate it into the column default so
# 1200 is not duplicated as a bare literal (safe: it is our own int constant).
SQL_CREATE_USERS = f"""
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    salt BLOB NOT NULL,
    password_hash BLOB NOT NULL,
    rating INTEGER NOT NULL DEFAULT {DEFAULT_RATING},
    created_at TEXT NOT NULL
)
"""
SQL_INSERT_USER = (
    "INSERT INTO users (username, salt, password_hash, created_at) "
    "VALUES (?, ?, ?, ?)"
)
SQL_SELECT_CREDENTIALS = (
    "SELECT salt, password_hash, rating FROM users WHERE username = ?"
)
SQL_SELECT_RATING = "SELECT rating FROM users WHERE username = ?"
SQL_UPDATE_RATING = "UPDATE users SET rating = ? WHERE username = ?"


class AuthReason(StrEnum):
    """Persistence-layer result reasons (distinct from rules' MoveReason)."""

    OK = "ok"
    USERNAME_TAKEN = "username_taken"
    NO_SUCH_USER = "no_such_user"
    BAD_PASSWORD = "bad_password"


def resolve_db_path() -> str:
    """Return the configured SQLite path (env override, else the default).

    Does not create any directory — callers create it at server boot time.
    """
    override = os.environ.get(DB_ENV_VAR)
    if override:
        return override
    return os.path.join(DEFAULT_DB_DIR, DEFAULT_DB_FILENAME)
