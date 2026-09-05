"""Delta op codes and the positional-array layout of each op.

Both sides of the wire must read these identically, so they live in `shared/`
alongside the rest of the contract. Only the vocabulary is here: building ops
from engine events is `server/delta.py`'s job (it needs `events/`, which
`shared/` must never import) and applying them is `client/remote_game.py`'s.

Ops are positional arrays rather than objects: a whole move frame lands around
150 bytes this way, against ~4.8 KB for the full-board state message it
replaces. The first element is always the op code, the second (where the op
concerns a piece) always its id, the third (where the op concerns a move) that
move's id -- so `OP_CODE_INDEX`, `OP_PIECE_ID` and `OP_MOVE_ID` are shared
across ops and only the tail differs:

    ["m",  piece_id, move_id, ox, oy, tx, ty, t0, t1]        MoveStarted
    ["t",  piece_id, move_id, tx, ty, t1, in_flight]         MoveTruncated
    ["c",  piece_id, move_id, sx, sy, dx, dy, type, color]   MoveCompleted
    ["a",  piece_id, move_id, x, y]                          MoveAborted
    ["x",  piece_id, by_move_id, x, y, type, color]          PieceCaptured
    ["r",  piece_id, x, y]                                   RestEnded
    ["sc", white, black]                                     scores changed

Notes on the shapes:
- `m` with ox,oy == tx,ty is a jump (the piece goes airborne and stays put).
- `t`'s `in_flight` distinguishes a piece still travelling toward a nearer
  target from one that has already retreated onto `tx,ty` and is resting.
- `c` carries the *post-promotion* piece type, which is the only way a piece's
  type ever changes.
- `x`'s `by_move_id` is the move that did the capturing, which is what
  correlates a capture with its move.

`GameEnded` deliberately has no op: GAME_OVER already carries the end of the
game, and a second path to it would be a second thing to keep idempotent.
"""

from enum import Enum

# Every op is [code, ...fields].
OP_CODE_INDEX = 0
# Shared across every op that names a piece / a move.
OP_PIECE_ID = 1
OP_MOVE_ID = 2


class OpCode(str, Enum):
    MOVE_STARTED = "m"
    MOVE_TRUNCATED = "t"
    MOVE_COMPLETED = "c"
    MOVE_ABORTED = "a"
    PIECE_CAPTURED = "x"
    REST_ENDED = "r"
    SCORES = "sc"


# Per-op tail offsets, named so neither side indexes an op with a bare integer.
MOVE_STARTED_ORIGIN_X = 3
MOVE_STARTED_ORIGIN_Y = 4
MOVE_STARTED_TARGET_X = 5
MOVE_STARTED_TARGET_Y = 6
MOVE_STARTED_START_MS = 7
MOVE_STARTED_ARRIVAL_MS = 8

MOVE_TRUNCATED_TARGET_X = 3
MOVE_TRUNCATED_TARGET_Y = 4
MOVE_TRUNCATED_ARRIVAL_MS = 5
MOVE_TRUNCATED_IN_FLIGHT = 6

MOVE_COMPLETED_SRC_X = 3
MOVE_COMPLETED_SRC_Y = 4
MOVE_COMPLETED_DST_X = 5
MOVE_COMPLETED_DST_Y = 6
MOVE_COMPLETED_TYPE = 7
MOVE_COMPLETED_COLOR = 8

MOVE_ABORTED_X = 3
MOVE_ABORTED_Y = 4

PIECE_CAPTURED_X = 3
PIECE_CAPTURED_Y = 4
PIECE_CAPTURED_TYPE = 5
PIECE_CAPTURED_COLOR = 6

REST_ENDED_X = 2
REST_ENDED_Y = 3

SCORES_WHITE = 1
SCORES_BLACK = 2
