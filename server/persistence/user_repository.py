"""Result-object repository over the users table."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from model.piece import Color
from server.elo import update_ratings
from server.persistence.db import Database
from server.persistence.password_hashing import hash_password, verify_password
from server.persistence.persistence_config import (
    AuthReason,
    SQL_INSERT_USER,
    SQL_SELECT_CREDENTIALS,
    SQL_SELECT_RATING,
    SQL_UPDATE_RATING,
)


@dataclass(frozen=True)
class CreateUserResult:
    ok: bool
    reason: str


@dataclass(frozen=True)
class AuthResult:
    ok: bool
    reason: str
    rating: int | None


@dataclass(frozen=True)
class GameResultRatings:
    white_old: int
    white_new: int
    black_old: int
    black_new: int


class UnknownPlayerError(Exception):
    """Raised when a game result references a username with no user row."""

    def __init__(self, username: str):
        super().__init__(f"no user row for username {username!r}")
        self.username = username


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class UserRepository:
    def __init__(self, db: Database):
        self._db = db

    def create_user(self, username: str, password: str) -> CreateUserResult:
        record = hash_password(password)
        conn = self._db.connection
        try:
            with conn:
                conn.execute(
                    SQL_INSERT_USER,
                    (username, record.salt, record.password_hash, _now_iso()),
                )
        except sqlite3.IntegrityError:
            return CreateUserResult(ok=False, reason=AuthReason.USERNAME_TAKEN)
        return CreateUserResult(ok=True, reason=AuthReason.OK)

    def authenticate(self, username: str, password: str) -> AuthResult:
        row = self._db.connection.execute(
            SQL_SELECT_CREDENTIALS, (username,)
        ).fetchone()
        if row is None:
            return AuthResult(ok=False, reason=AuthReason.NO_SUCH_USER, rating=None)
        salt, password_hash, rating = row
        if not verify_password(password, salt, password_hash):
            return AuthResult(ok=False, reason=AuthReason.BAD_PASSWORD, rating=None)
        return AuthResult(ok=True, reason=AuthReason.OK, rating=rating)

    def get_rating(self, username: str) -> int | None:
        row = self._db.connection.execute(SQL_SELECT_RATING, (username,)).fetchone()
        if row is None:
            return None
        return row[0]

    def apply_game_result(
        self,
        white_username: str,
        black_username: str,
        winner_color: Color,
    ) -> GameResultRatings:
        conn = self._db.connection
        white_old = self.get_rating(white_username)
        if white_old is None:
            raise UnknownPlayerError(white_username)
        black_old = self.get_rating(black_username)
        if black_old is None:
            raise UnknownPlayerError(black_username)
        white_won = winner_color == Color.WHITE
        if white_won:
            update = update_ratings(white_old, black_old)
            white_new, black_new = update.new_winner_rating, update.new_loser_rating
        else:
            update = update_ratings(black_old, white_old)
            black_new, white_new = update.new_winner_rating, update.new_loser_rating
        with conn:
            conn.execute(SQL_UPDATE_RATING, (white_new, white_username))
            conn.execute(SQL_UPDATE_RATING, (black_new, black_username))
        return GameResultRatings(
            white_old=white_old,
            white_new=white_new,
            black_old=black_old,
            black_new=black_new,
        )
