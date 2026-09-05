"""Pure computation of path-collision fates: given a set of in-flight moves,
which one(s) get truncated or captured, and when. Extracted from
RealTimeArbiter._resolve_path_collisions verbatim (same pairwise scan, same
tie-breaks) so it can be called either by the legacy per-tick sweep or, once
scheduled at add-time, by the event-heap scheduler - neither the algorithm
nor its results change with this move.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from model.piece import State
from model.position import Position


class CollisionOutcome(Enum):
    """Fate assigned to a move: CAPTURE destroys the losing piece mid-transit,
    TRUNCATE stops it one square short."""
    CAPTURE = "capture"
    TRUNCATE = "truncate"


@dataclass(frozen=True)
class Fate:
    """The earliest collision fate computed for one move. `cell` is the
    contested square; `capturing_move_id` is set only for CAPTURE (the move
    whose piece survives and is credited with the kill)."""
    resolution_time: int
    outcome: CollisionOutcome
    path: tuple
    cell: Position
    capturing_move_id: Optional[int] = None


def _is_straight_line(origin, target):
    dx = target.x - origin.x
    dy = target.y - origin.y
    return dx == 0 or dy == 0 or abs(dx) == abs(dy)


def path_cells(origin, target):
    """All cells along the straight path from origin to target (exclusive of
    origin, inclusive of target). Non-sliding moves (e.g. a knight's jump)
    have no intermediate squares, so just the target is returned."""
    if not _is_straight_line(origin, target):
        return [target]

    dx = 0 if target.x == origin.x else (1 if target.x > origin.x else -1)
    dy = 0 if target.y == origin.y else (1 if target.y > origin.y else -1)
    cells = []
    cur = Position(origin.x + dx, origin.y + dy)
    while cur != target:
        cells.append(cur)
        cur = Position(cur.x + dx, cur.y + dy)
    cells.append(target)
    return cells


def time_at_cell(move, path, cell, move_delay_ms):
    """Absolute clock time at which `move`'s piece reaches `cell` while
    travelling its current (fixed-speed) path from origin to target. `path`
    is `path_cells(move.origin, move.target)`, passed in rather than
    recomputed since every caller already has it."""
    return move.start_time + (path.index(cell) + 1) * move_delay_ms


def compute_collision_fates(moves, move_delay_ms: int) -> dict:
    """Look for any two in-flight moves whose paths cross and resolve the
    earliest crossing for each. Handles both standard moving collisions and
    airborne interceptions. Returns {move_id: Fate} for every move that has
    one - callers apply a fate only once their clock reaches its
    resolution_time (capture) or immediately (truncation is eager)."""
    fate: dict[int, Fate] = {}

    def consider(move, resolution_time, outcome, path, cell, capturing_move_id=None):
        current = fate.get(move.move_id)
        if current is None or resolution_time < current.resolution_time:
            fate[move.move_id] = Fate(resolution_time, outcome, tuple(path), cell, capturing_move_id)

    for i in range(len(moves)):
        for j in range(i + 1, len(moves)):
            a, b = moves[i], moves[j]
            path_a = path_cells(a.origin, a.target)
            path_b = path_cells(b.origin, b.target)

            # For jumps, path is exactly the cell they are jumping on.
            shared = set(path_a) & set(path_b)
            if not shared:
                continue

            is_a_airborne = a.piece.state == State.airborne
            is_b_airborne = b.piece.state == State.airborne

            # --- Airborne capture logic ---
            if is_a_airborne and not is_b_airborne:
                t_b = time_at_cell(b, path_b, a.origin, move_delay_ms)
                # Check if moving piece 'b' arrives during the jump window
                if a.start_time <= t_b <= a.arrival_time:
                    outcome = CollisionOutcome.TRUNCATE if a.piece.color == b.piece.color else CollisionOutcome.CAPTURE
                    if outcome == CollisionOutcome.CAPTURE:
                        consider(b, t_b, outcome, path_b, a.origin, a.move_id)
                    else:
                        consider(b, t_b, outcome, path_b, a.origin)
                continue

            if is_b_airborne and not is_a_airborne:
                t_a = time_at_cell(a, path_a, b.origin, move_delay_ms)
                if b.start_time <= t_a <= b.arrival_time:
                    outcome = CollisionOutcome.TRUNCATE if a.piece.color == b.piece.color else CollisionOutcome.CAPTURE
                    if outcome == CollisionOutcome.CAPTURE:
                        consider(a, t_a, outcome, path_a, b.origin, b.move_id)
                    else:
                        consider(a, t_a, outcome, path_a, b.origin)
                continue

            if is_a_airborne and is_b_airborne:
                continue  # Two jumps cannot collide mid-air since they stay in place
            # ----------------------------------

            # --- Standard collision logic ---
            # The earliest point, in real time, at which the two paths
            # actually conflict.
            cell = min(
                shared,
                key=lambda c: max(
                    time_at_cell(a, path_a, c, move_delay_ms),
                    time_at_cell(b, path_b, c, move_delay_ms),
                ),
            )

            t_a = time_at_cell(a, path_a, cell, move_delay_ms)
            t_b = time_at_cell(b, path_b, cell, move_delay_ms)
            resolution_time = max(t_a, t_b)
            outcome = CollisionOutcome.TRUNCATE if a.piece.color == b.piece.color else CollisionOutcome.CAPTURE

            if outcome == CollisionOutcome.TRUNCATE:
                # Block (same color): the later piece stops. On an exact tie
                # (t_a == t_b) the move ordered first (lower move_id) is
                # treated as earlier and keeps going, so exactly one side is
                # ever truncated instead of both.
                if t_a == t_b:
                    loser, loser_path = (b, path_b) if a.move_id < b.move_id else (a, path_a)
                elif t_a > t_b:
                    loser, loser_path = a, path_a
                else:
                    loser, loser_path = b, path_b
                consider(loser, resolution_time, outcome, loser_path, cell)
            else:
                # Capture (different colors): the earlier piece is destroyed
                # by the later (surviving) piece's move. On an exact tie the
                # move ordered first (lower move_id) survives and captures
                # the other, instead of both being destroyed.
                if t_a == t_b:
                    loser, loser_path, winner_move_id = (
                        (b, path_b, a.move_id) if a.move_id < b.move_id else (a, path_a, b.move_id)
                    )
                elif t_a < t_b:
                    loser, loser_path, winner_move_id = a, path_a, b.move_id
                else:
                    loser, loser_path, winner_move_id = b, path_b, a.move_id
                consider(loser, resolution_time, outcome, loser_path, cell, winner_move_id)

    return fate
