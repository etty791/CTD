"""Server-wide constants: routes, protocol status values, and error messages."""

from enum import StrEnum

# --- HTTP / WebSocket routes ---
WS_PATH = "/ws"
HEALTH_PATH = "/health"
DEBUG_CONNECTIONS_PATH = "/debug/connections"

# --- Protocol status values (shared by AUTH / REGISTER / LOGIN acks) ---
class Status(StrEnum):
    OK = "ok"
    FAILED = "failed"


# --- Player roles within a room ---
class Role(StrEnum):
    PLAYER = "player"
    OBSERVER = "observer"


ROLE_PLAYER = Role.PLAYER
ROLE_OBSERVER = Role.OBSERVER

# --- Room / matchmaking ---
ROOM_STATUS_WAITING = "waiting"
QUICK_MATCH_ROOM_PREFIX = "quickmatch-"

# --- Ticking / game-over reasons ---
TICK_MS = 50
GAME_OVER_REASON_KING_CAPTURED = "king_captured"
GAME_OVER_REASON_DISCONNECT = "opponent_disconnected"
# Same reason, surfaced on the RESIGN message a disconnect triggers.
DISCONNECT_REASON = GAME_OVER_REASON_DISCONNECT

# --- Error messages ---
ERROR_NOT_AUTHENTICATED = "not authenticated"
ERROR_NOT_IN_GAME = "not in a game"
ERROR_NOT_YOUR_PIECE = "not your piece"
ERROR_ILLEGAL_MOVE = "illegal move: {reason}"
ERROR_NO_HANDLER = "no handler for type={type}"
ERROR_OBSERVER_CANNOT_MOVE = "observers cannot move"
ERROR_ALREADY_LOGGED_IN = "already logged in"
ERROR_USERNAME_TAKEN = "username taken"
ERROR_BAD_CREDENTIALS = "bad credentials"
