"""Server-only constants: routes, room/matchmaking knobs, and error messages.

Values the client must interpret identically (statuses, roles, the
matchmaking timeout) live in `shared/protocol_config.py` instead.
"""

from model.piece import Color

# --- HTTP / WebSocket routes ---
WS_PATH = "/ws"
HEALTH_PATH = "/health"
DEBUG_CONNECTIONS_PATH = "/debug/connections"

# --- Rooms ---
MAX_PLAYERS_PER_ROOM = 2
# Seat order: first player (creator) is White, second is Black.
SEAT_COLORS = (Color.WHITE, Color.BLACK)
# Short, typeable room ids. Crockford base32 alphabet (no I, L, O, U).
ROOM_ID_LENGTH = 6
ROOM_ID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

# --- Matchmaking (ELO seek pool) ---
# A "Play" seeker is paired with a waiting seeker within this rating band;
# if none appears within MATCH_TIMEOUT_MS (shared/protocol_config.py, since
# the client waits on it too), matchmaking gives up.
MATCH_ELO_RANGE = 100
ERROR_NO_MATCH_FOUND = "no opponent found"

# --- Ticking / game-over reasons ---
TICK_MS = 50
# STATE frames are published on change, not on every tick. This is the
# ceiling between two frames anyway: a resync heartbeat, so a dropped frame
# or an unexpected desync heals within a second on an otherwise idle board.
MAX_STATE_INTERVAL_MS = 1000
GAME_OVER_REASON_KING_CAPTURED = "king_captured"
GAME_OVER_REASON_DISCONNECT = "opponent_disconnected"
GAME_OVER_REASON_RESIGNATION = "resignation"

# --- Error messages ---
ERROR_ACCOUNT_NOT_FOUND = "account not found"
ERROR_NOT_AUTHENTICATED = "not authenticated"
ERROR_NOT_IN_GAME = "not in a game"
ERROR_NOT_YOUR_PIECE = "not your piece"
ERROR_ILLEGAL_MOVE = "illegal move: {reason}"
ERROR_NO_HANDLER = "no handler for type={type}"
ERROR_OBSERVER_CANNOT_MOVE = "observers cannot move"
ERROR_OBSERVER_CANNOT_RESIGN = "observers cannot resign"
ERROR_ALREADY_LOGGED_IN = "already logged in"
ERROR_USERNAME_TAKEN = "username taken"
ERROR_BAD_CREDENTIALS = "bad credentials"
ERROR_ALREADY_IN_GAME = "already in a game or room"
ERROR_ROOM_NOT_FOUND = "room not found"
