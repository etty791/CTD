"""Server-wide constants: routes, protocol status values, and error messages."""

# --- HTTP / WebSocket routes ---
WS_PATH = "/ws"
HEALTH_PATH = "/health"
DEBUG_CONNECTIONS_PATH = "/debug/connections"

# --- Protocol status / reason values ---
AUTH_STATUS_OK = "ok"
DISCONNECT_REASON = "opponent_disconnected"

# --- Error messages ---
ERROR_NOT_AUTHENTICATED = "not authenticated"
ERROR_NOT_IN_GAME = "not in a game"
ERROR_NOT_YOUR_PIECE = "not your piece"
ERROR_ILLEGAL_MOVE = "illegal move: {reason}"
ERROR_NO_HANDLER = "no handler for type={type}"
