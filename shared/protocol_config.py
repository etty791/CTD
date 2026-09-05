"""Literal values that appear inside wire payloads, plus the one timing
constant the client has to agree with the server on.

Server-only knobs (routes, tick rate, room id alphabet, error text) stay in
`server/server_config.py`; only values both sides must interpret identically
belong here.
"""

from enum import StrEnum

from model.board import BOARD_SIZE

# Board dimensions and time-unit conversion both sides must agree on -
# view/ and client/ each render from these rather than declaring their own.
DEFAULT_BOARD_SIZE = BOARD_SIZE
MS_PER_SECOND = 1000


# --- Protocol status values (shared by AUTH / REGISTER / LOGIN acks) ---
class Status(StrEnum):
    OK = "ok"
    FAILED = "failed"


# --- Player roles within a room (GameStartPayload.role) ---
class Role(StrEnum):
    PLAYER = "player"
    OBSERVER = "observer"


# --- Room lifecycle (RoomWaitingPayload.status) ---
class RoomStatus(StrEnum):
    WAITING = "waiting"
    LIVE = "live"
    ENDED = "ended"


ROOM_STATUS_WAITING = RoomStatus.WAITING

# How long the server searches for an ELO-matched opponent before giving up.
# The client sizes its own `play` wait from this, so it must not drift.
MATCH_TIMEOUT_MS = 60_000
