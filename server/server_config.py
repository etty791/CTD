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
# Typeable room ids. Crockford base32 alphabet (no I, L, O, U). 16 chars over
# this 32-symbol alphabet is ~80 bits - the brute-force fix from the spec.
ROOM_ID_LENGTH = 16
ROOM_ID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

# --- Matchmaking (ELO seek pool) ---
# A "Play" seeker is paired with a waiting seeker within a rating band that
# widens the longer they wait: MATCH_ELO_RANGE_INITIAL to start, +STEP every
# INTERVAL_MS, capped at MATCH_ELO_RANGE_MAX. Widening is evaluated only when
# a new seeker calls `seek` (against the band of whoever has been waiting);
# if nobody appears within MATCH_TIMEOUT_MS (shared/protocol_config.py, since
# the client waits on it too), matchmaking gives up regardless of band.
MATCH_ELO_RANGE_INITIAL = 100
MATCH_ELO_RANGE_STEP = 50
MATCH_ELO_WIDEN_INTERVAL_MS = 5_000
MATCH_ELO_RANGE_MAX = 400
ERROR_NO_MATCH_FOUND = "no opponent found"

# --- Ticking / game-over reasons ---
TICK_MS = 50
# Frames are published on change, and an idle game publishes none at all -
# there is no heartbeat. A dropped frame heals through the client noticing a
# gap in Envelope.seq and asking for a keyframe (RESYNC); socket liveness is
# WebSocket ping/pong, which uvicorn and the websockets client both do
# themselves. This is the floor between two frames of one game: a burst of
# commands coalesces rather than emitting a frame each.
FRAME_MIN_INTERVAL_MS = 10
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
