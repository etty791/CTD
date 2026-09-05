"""Client-side configuration: server URL resolution, timeouts, and the
user-facing strings the shell prints (kept out of shell.py's logic so it has
no inline literals beyond simple f-string interpolation of named pieces)."""

import os

DEFAULT_SERVER_URL = "ws://127.0.0.1:8000/ws"
SERVER_URL_ENV_VAR = "CTD_SERVER_URL"

RESPONSE_TIMEOUT_S = 10
# Added to server.server_config.MATCH_TIMEOUT_MS/1000 when the shell blocks
# waiting for a `play` match, so the client's own timeout is strictly looser
# than the server's -- the server's ERROR_NO_MATCH_FOUND should always win.
MATCHMAKING_TIMEOUT_BUFFER_S = 5

PROMPT = "> "
USERNAME_PROMPT = "Username: "
PASSWORD_PROMPT = "Password: "

# --- command names ---
CMD_REGISTER = "register"
CMD_LOGIN = "login"
CMD_PLAY = "play"
CMD_ROOM = "room"
CMD_HELP = "help"
CMD_QUIT = "quit"

# --- user-facing messages ---
MSG_NOT_LOGGED_IN = "Log in first (register / login)."
MSG_UNKNOWN_COMMAND = "Unknown command. Type 'help' for the command list."
MSG_GOODBYE = "Goodbye."
MSG_SEARCHING = "Searching for an opponent..."
MSG_WAITING_FOR_OPPONENT = "Waiting for them to join... (Ctrl+C to cancel)"
MSG_SEEK_CANCELLED = "Cancelled waiting (the room stays open server-side for now)."
MSG_PLAY_QUEUED = "No immediate match -- queued, waiting for an opponent... (Ctrl+C to cancel)"
MSG_PLAY_CANCELLED = "Cancelled search for an opponent."
MSG_HELP_TEXT = (
    "Commands:\n"
    "  register            create an account\n"
    "  login               log into an account\n"
    "  play                quick-match by rating\n"
    "  room                create a room and wait for an opponent\n"
    "  room <room_id>      join an existing room\n"
    "  help                show this message\n"
    "  quit                exit"
)


def resolve_server_url() -> str:
    """Return the configured server URL (env override, else the default)."""
    override = os.environ.get(SERVER_URL_ENV_VAR)
    if override:
        return override
    return DEFAULT_SERVER_URL
