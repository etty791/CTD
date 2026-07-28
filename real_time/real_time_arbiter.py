from dataclasses import dataclass
from enum import Enum
from typing import Optional

from model.board import EMPTY_CELL
from model.piece import Piece, PieceType, Color, State
from rules.rules_engine import validate_piece_move
from model.position import Position
from real_time.real_time_config import *
from events.event_bus import EventBus
from events.game_events import (
    GameEnded,
    MoveAborted,
    MoveCompleted,
    MoveStarted,
    MoveTruncated,
    PieceCaptured,
    RestEnded,
)

REST_DURATION_MS = {
    State.long_rest: LONG_REST_DURATION_MS,
    State.short_rest: SHORT_REST_DURATION_MS,
}

class _CollisionOutcome(Enum):
    """Fate assigned to a move by _resolve_path_collisions: CAPTURE destroys
    the losing piece mid-transit, TRUNCATE stops it one square short."""
    CAPTURE = "capture"
    TRUNCATE = "truncate"

class Move:
    def __init__(self, piece, origin, target, arrival_time, start_time, move_id):
        self.piece = piece
        self.origin = origin
        self.target = target
        self.arrival_time = arrival_time
        self.start_time = start_time
        self.move_id = move_id

@dataclass
class RestingPiece:
    piece: Piece
    rest_until_ms: int

def _opposite_color(color: Color) -> Color:
    return Color.BLACK if color == Color.WHITE else Color.WHITE

def _is_straight_line(origin, target):
    """True if target is reachable from origin along a single rook/bishop
    direction (i.e. a 'sliding' move). False for knight-style jumps."""
    dx = target.x - origin.x
    dy = target.y - origin.y
    return dx == 0 or dy == 0 or abs(dx) == abs(dy)

def _path_cells(origin, target):
    """Returns all cells along the straight path from origin to target
    (exclusive of origin, inclusive of target).

    Moves that are not a straight line or 45-degree diagonal (e.g. a
    knight's jump) have no intermediate squares to slide through, so we
    return just the target. Treating them as a sliding move would make the
    unit-step walk below never reach the target (infinite loop).
    """

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

def _move_distance(origin, target):
    """Number of animation 'steps' a move takes, used for arrival timing.
    Sliding moves take one step per square; a non-sliding jump (e.g. a
    knight) is a single leap regardless of its Chebyshev distance, matching
    the single-cell path returned by _path_cells for such moves.
    """
    if origin == target:
        return 0
    if not _is_straight_line(origin, target):
        return 1
    return max(abs(target.x - origin.x), abs(target.y - origin.y))

class RealTimeArbiter:

    def __init__(self, board, event_bus: Optional[EventBus] = None):
        self.board = board
        self.pending_moves = []
        self.clock = 0
        self._resting: list[RestingPiece] = []
        self._next_move_id = 1
        self.event_bus = event_bus

    def _new_move_id(self) -> int:
        move_id = self._next_move_id
        self._next_move_id += 1
        return move_id

    def _publish(self, event) -> None:
        """No-op when no event_bus was provided, so callers/tests never
        have to construct one just to use the arbiter."""
        if self.event_bus is not None:
            self.event_bus.publish(event)

    def _record_capture(self, captured_piece: Piece, capturing_move_id: int) -> None:
        """Publish PieceCaptured for `captured_piece`, attributing it to the
        move (`capturing_move_id`) whose arrival or path caused the capture -
        scoring itself is not the arbiter's concern; see ScoreTracker."""
        self._publish(PieceCaptured(
            captured_piece.id, captured_piece.type, captured_piece.color,
            captured_piece.position, capturing_move_id,
        ))

    def _mark_captured(self, piece: Piece, capturing_move_id: int) -> None:
        """The one place a piece dies. Idempotent - a piece already marked
        captured (e.g. its old path gets swept a second time before the
        ghost is fully cleaned up) is left alone, so it is never announced
        or scored twice. Evicts the piece's own pending move (if any) so a
        corpse can no longer truncate, capture, or be captured again."""
        if piece.state == State.captured:
            return
        piece.state = State.captured
        self._record_capture(piece, capturing_move_id)
        self._drop_moves_for(piece)

    def _drop_moves_for(self, piece: Piece) -> None:
        """Remove every pending Move belonging to `piece` - called the
        instant a piece dies so its stale move can never again be swept up
        as if the piece were still travelling."""
        self.pending_moves = [m for m in self.pending_moves if m.piece is not piece]

    def add_move(self, piece, origin, target):
        # --- Rule 1: Movement Lock (Debounce) ---
        # A piece that is already mid-flight has an immutable path: any
        # attempt to issue it a new destination is rejected outright until
        # it becomes idle again. piece.state is the single source of truth
        # for this - it flips to State.moving the instant a move is
        # accepted below, and once that move concludes (arrival in
        # _apply_move, being blocked in _truncate_move, or being
        # invalidated in _resolve_single / _resolve_collision) the piece
        # enters a rest state that _release_expired_rests later returns to
        # State.idle. Resting pieces are rejected here by the same check.
        # Nothing else in this class is allowed to
        # add a pending move for a piece without going through here first,
        # so this one check is sufficient - no need to separately scan
        # pending_moves for a matching origin.
        if piece.state != State.idle:
            return False

        # Reject moves that are illegal per the rules engine up front.
        # Without this, an illegal move would sit in pending_moves with the
        # piece locked in State.moving until it finally got rejected at
        # arrival time, needlessly freezing the piece in the meantime.
        # if not validate_move(self.board, origin, target).is_valid:
        #     return False

        distance = _move_distance(origin, target)
        arrival_time = self.clock + (distance * DEFAULT_MOVE_DELAY_MS)
        move = Move(piece, origin, target, arrival_time, self.clock, self._new_move_id())
        piece.state = State.moving
        self.pending_moves.append(move)
        self._publish(MoveStarted(move.move_id, piece.id, origin, target))
        return True

    def add_jump(self, piece, pos):
        if piece.state != State.idle:
            return False
        arrival_time = self.clock + DEFAULT_MOVE_DELAY_MS
        move = Move(piece, pos, pos, arrival_time, self.clock, self._new_move_id())
        piece.state = State.airborne
        self.pending_moves.append(move)
        self._publish(MoveStarted(move.move_id, piece.id, pos, pos))
        return True
    
    def advance_time(self, ms):
        king_captured = False
        self.clock += ms
        king_captured = self._resolve_path_collisions() or king_captured
        self._vacate_departed_origins()
        arrived = self._pop_arrived_moves()
        for target, moves in self._group_by_target(arrived).items():
            if len(moves) > 1:
                king_captured = self._resolve_collision(moves, target) or king_captured
            else:
                king_captured = self._resolve_single(moves[0]) or king_captured
        self._release_expired_rests()
        return king_captured

    def _vacate_departed_origins(self) -> None:
        """A mover has left its origin the instant its first step
        completes (start_time + DEFAULT_MOVE_DELAY_MS) - per the user's
        occupancy rule, other pieces then treat that square as empty:
        passable and landable. Jumps never vacate (origin == target, and
        the piece stays there, airborne, for the whole window so it can
        keep intercepting)."""
        for move in self.pending_moves:
            if move.piece.state == State.airborne or move.origin == move.target:
                continue
            first_step_time = move.start_time + DEFAULT_MOVE_DELAY_MS
            if self.clock >= first_step_time and self.board.get_piece_at(move.origin) == move.piece:
                self.board.set_piece_at(move.origin, EMPTY_CELL)

    # ------------------------------------------------------------------
    # Rest (cooldown) handling
    # ------------------------------------------------------------------

    def _begin_rest(self, piece: Piece, rest_state: State, stop_time_ms: int) -> None:
        """Put a piece into a rest state that expires REST_DURATION_MS
        after `stop_time_ms` - the deterministic clock time the piece
        stopped moving (its move's arrival_time), NOT the current clock,
        so rests behave identically however coarsely time is advanced."""
        if piece.state == State.captured:
            return
        piece.state = rest_state
        self._resting.append(RestingPiece(piece, stop_time_ms + REST_DURATION_MS[rest_state]))

    def _release_expired_rests(self) -> None:
        """Return pieces whose rest has expired to State.idle. Runs once
        at the END of advance_time: rests are anchored to arrival_time,
        so a rest that both starts and expires within a single large
        advance_time call is released in that same call. Pieces captured
        while resting are dropped, never resurrected."""
        still_resting: list[RestingPiece] = []
        for entry in self._resting:
            if not entry.piece.state.is_resting():
                continue
            if entry.rest_until_ms <= self.clock:
                entry.piece.state = State.idle
                self._publish(RestEnded(entry.piece.id, entry.piece.position))
            else:
                still_resting.append(entry)
        self._resting = still_resting

    def _abort_move(self, move) -> None:
        """End a move that does not complete as planned. Shared by every
        abort site: blocked before its first step, losing a same-color
        arrival race, or failing revalidation on arrival.

        Two cases, distinguished by whether the piece ever vacated its
        origin (board state is the single source of truth for this - see
        _vacate_departed_origins):

        - Never vacated (still standing on origin - true for a jump, which
          never vacates, or a slide blocked before its first step; proof:
          a truncate-to-origin is only ever assigned when the blocker
          arrives at or before the first-step instant): unchanged from
          before - the piece rests right where it stands and MoveAborted
          is published. Defensive guard: if the origin cell was somehow
          not held by the piece, put it back rather than losing it.
        - Already vacated: per the user's rule it never returns to origin -
          it retreats instead (see _retreat_vacated_move).
        """
        if move.piece.state == State.captured:
            # Already destroyed (and already announced via PieceCaptured):
            # there is no resting piece left to report.
            return
        if move.origin == move.target or self.board.get_piece_at(move.origin) == move.piece:
            if move.origin != move.target and self.board.get_piece_at(move.origin) != move.piece:
                self.board.place_piece(move.origin, move.piece)
            self._begin_rest(move.piece, State.long_rest, move.arrival_time)
            self._publish(MoveAborted(move.move_id, move.piece.id, move.origin))
            return
        self._retreat_vacated_move(move)

    def _retreat_vacated_move(self, move) -> None:
        """A vacated piece that cannot complete its move does not return to
        origin. It stops on the nearest free square walking backwards from
        its (contested/illegal) target along its own path - for a
        one-square move that is the origin itself, which is why a
        single-step abort degenerates to the pre-vacate MoveAborted
        behavior. If no square along the path is free, the piece has
        nowhere to stand and is removed."""
        path = _path_cells(move.origin, move.target)
        # Nearest-to-target first: path cells (excluding the contested
        # target) walked backwards, then origin as the final fallback.
        candidates = list(reversed(path[:-1])) + [move.origin]
        for cell in candidates:
            if self.board.is_cell_empty(cell):
                self.board.place_piece(cell, move.piece)
                self._begin_rest(move.piece, State.long_rest, move.arrival_time)
                self._publish(MoveTruncated(move.move_id, move.piece.id, cell, move.arrival_time))
                return
        # Not believed reachable (the origin is always a candidate and,
        # per the vacate proof, is free unless something else has already
        # landed there) - but must not crash if it somehow happens.
        self._mark_captured(move.piece, move.move_id)

    # ------------------------------------------------------------------
    # Rules 2 & 3: temporal path-collision detection
    # ------------------------------------------------------------------

    def _time_at_cell(self, move, path, cell):
        """Absolute clock time at which `move`'s piece reaches `cell`
        while travelling its current (fixed-speed) path from origin to
        target. `path` is `_path_cells(move.origin, move.target)` - passed
        in rather than recomputed, since every caller already has it."""
        return move.start_time + (path.index(cell) + 1) * DEFAULT_MOVE_DELAY_MS

    def _resolve_path_collisions(self):
        """Look for any two in-flight pieces whose paths cross, and
        resolve the earliest crossing for each of them.
        Handles both standard moving collisions and airborne interceptions.
        """
        moves = self.pending_moves
        # id(move) -> (resolution_time, _CollisionOutcome, payload)
        fate = {}

        def consider(move, resolution_time, kind, payload):
            current = fate.get(id(move))
            if current is None or resolution_time < current[0]:
                fate[id(move)] = (resolution_time, kind, payload)

        for i in range(len(moves)):
            for j in range(i + 1, len(moves)):
                a, b = moves[i], moves[j]
                path_a = _path_cells(a.origin, a.target)
                path_b = _path_cells(b.origin, b.target)
                
                # For jumps, path is exactly the cell they are jumping on.
                shared = set(path_a) & set(path_b)
                if not shared:
                    continue

                is_a_airborne = a.piece.state == State.airborne
                is_b_airborne = b.piece.state == State.airborne

                # --- New Airborne Capture Logic ---
                if is_a_airborne and not is_b_airborne:
                    t_b = self._time_at_cell(b, path_b, a.origin)
                    # Check if moving piece 'b' arrives during the 1000ms jump window
                    if a.start_time <= t_b <= a.arrival_time:
                        kind = _CollisionOutcome.TRUNCATE if a.piece.color == b.piece.color else _CollisionOutcome.CAPTURE
                        # The moving piece 'b' takes the fate (gets blocked or captured)
                        payload = (path_b, a.origin, a.move_id) if kind == _CollisionOutcome.CAPTURE else (path_b, a.origin)
                        consider(b, t_b, kind, payload)
                    continue # Skip standard collision logic for this pair

                if is_b_airborne and not is_a_airborne:
                    t_a = self._time_at_cell(a, path_a, b.origin)
                    # Check if moving piece 'a' arrives during the 1000ms jump window
                    if b.start_time <= t_a <= b.arrival_time:
                        kind = _CollisionOutcome.TRUNCATE if a.piece.color == b.piece.color else _CollisionOutcome.CAPTURE
                        # The moving piece 'a' takes the fate (gets blocked or captured)
                        payload = (path_a, b.origin, b.move_id) if kind == _CollisionOutcome.CAPTURE else (path_a, b.origin)
                        consider(a, t_a, kind, payload)
                    continue # Skip standard collision logic for this pair

                if is_a_airborne and is_b_airborne:
                    continue # Two jumps cannot collide mid-air since they stay in place
                # ----------------------------------

                # --- Standard Collision Logic ---
                # The earliest point, in real time, at which the two
                # paths actually conflict
                cell = min(
                    shared,
                    key=lambda c: max(
                        self._time_at_cell(a, path_a, c),
                        self._time_at_cell(b, path_b, c),
                    ),
                )
                
                t_a = self._time_at_cell(a, path_a, cell)
                t_b = self._time_at_cell(b, path_b, cell)
                resolution_time = max(t_a, t_b)
                kind = _CollisionOutcome.TRUNCATE if a.piece.color == b.piece.color else _CollisionOutcome.CAPTURE

                if kind == _CollisionOutcome.TRUNCATE:
                    # Block (same color): the later piece stops
                    if t_a >= t_b:
                        consider(a, resolution_time, kind, (path_a, cell))
                    if t_b >= t_a:
                        consider(b, resolution_time, kind, (path_b, cell))
                else:
                    # Capture (different colors): the earlier piece is destroyed
                    # by the later (surviving) piece's move.
                    if t_a <= t_b:
                        consider(a, resolution_time, kind, (path_a, cell, b.move_id))
                    if t_b <= t_a:
                        consider(b, resolution_time, kind, (path_b, cell, a.move_id))

        king_captured = False
        for move in list(moves):
            if move not in self.pending_moves:
                # Already dropped underneath us - e.g. its piece was
                # marked captured while resolving another move's fate.
                continue
            outcome = fate.get(id(move))
            if outcome is None:
                continue
            resolution_time, kind, payload = outcome
            if kind == _CollisionOutcome.CAPTURE:
                if resolution_time > self.clock:
                    # The paths cross, but the pieces haven't actually
                    # reached the shared cell yet - re-derived and applied
                    # once self.clock catches up to resolution_time.
                    continue
                path, cell, capturing_move_id = payload
                king_captured = self._capture_in_flight(move, capturing_move_id) or king_captured
            else:
                path, cell = payload
                self._truncate_move(move, path, cell)
        return king_captured

    def _destroy_in_transit(self, move, capturing_move_id) -> bool:
        """Destroy a piece that lost a race for a shared square while still
        mid-flight. Returns True if it was a king (publishing GameEnded for
        the surviving side), so every caller propagates game-over
        identically. _mark_captured is idempotent and evicts the piece's
        own pending move, so callers need not touch pending_moves
        themselves."""
        if self.board.get_piece_at(move.origin) == move.piece:
            self.board.set_piece_at(move.origin, EMPTY_CELL)
        self._mark_captured(move.piece, capturing_move_id)
        if move.piece.type == PieceType.KING:
            self._publish(GameEnded(_opposite_color(move.piece.color)))
            return True
        return False

    def _capture_in_flight(self, move, capturing_move_id) -> bool:
        """A piece is destroyed mid-transit by an opposite-color piece
        that reaches their shared square later than it does. _mark_captured
        (via _destroy_in_transit) already evicted this move from
        pending_moves."""
        return self._destroy_in_transit(move, capturing_move_id)

    def _truncate_move(self, move, path, collision_cell):
        """A piece is blocked by its own color: it stops one square short
        of `collision_cell`, on the cell immediately preceding it along
        `move`'s own trajectory (its origin, if `collision_cell` was the
        very first step)."""
        idx = path.index(collision_cell)
        stop_cell = move.origin if idx == 0 else path[idx - 1]
        move.target = stop_cell
        move.arrival_time = move.start_time + _move_distance(move.origin, stop_cell) * DEFAULT_MOVE_DELAY_MS
        if stop_cell == move.origin:
            # Blocked before it could take even a single step - there's
            # nothing left to animate, so the move ends here and the piece
            # rests rather than staying in State.moving toward its own
            # square. arrival_time was just reset to start_time above, so
            # the rest anchors there.
            self._abort_move(move)
            self.pending_moves.remove(move)
            return
        self._publish(MoveTruncated(
            move.move_id, move.piece.id, move.target, move.arrival_time,
        ))

    # ------------------------------------------------------------------
    # Arrival handling
    # ------------------------------------------------------------------

    def _pop_arrived_moves(self):
        arrived = [m for m in self.pending_moves if m.arrival_time <= self.clock]
        arrived.sort(key=lambda m: m.arrival_time)
        for m in arrived:
            self.pending_moves.remove(m)
        return arrived

    def _group_by_target(self, moves):
        groups = {}
        for m in moves:
            groups.setdefault(m.target, []).append(m)
        return groups

    def _resolve_collision(self, moves, target):
        # Sort by arrival time: earliest arrival wins.
        # NOTE: with _resolve_path_collisions now running every tick
        # before moves are popped as "arrived" - and a move's target
        # always being part of its own path - two moves heading for the
        # same square are normally already resolved (captured/truncated)
        # long before they'd land here together. This is kept as a
        # defensive fallback for same-tick edge cases.
        moves.sort(key=lambda m: m.arrival_time)
        winner = moves[0]
        losers = moves[1:]
        king_captured = False
        for m in losers:
            if m.piece.color == winner.piece.color:
                # Same-color pieces can't capture one another - it simply
                # never lands on the contested square, same as a blocked
                # move elsewhere.
                self._abort_move(m)
                continue
            king_captured = self._destroy_in_transit(m, winner.move_id) or king_captured
        # The winner still needs to be validated - e.g. it could turn out
        # to be a friendly-fire "capture" on the target square, or its path
        # could have become illegal in the meantime. _resolve_single already
        # does this check for the single-mover case; do it here too.
        if not self._is_still_valid(winner):
            self._abort_move(winner)
            return king_captured
        return self._apply_move(winner) or king_captured

    def _resolve_single(self, move):

        if move.origin != move.target and not self._is_still_valid(move):
            # The move never happened - don't leave the piece stuck
            # thinking it's still mid-move.
            self._abort_move(move)
            return False
        return self._apply_move(move)

    def _is_still_valid(self, move):
        if move.piece.state == State.captured:
            return False
        # Check if the move is still legal. move.origin may currently be
        # empty (the piece vacates it mid-flight - see
        # _vacate_departed_origins), so this is keyed off the piece itself
        # rather than a board scan of its origin cell.
        if not validate_piece_move(self.board, move.piece, move.target).is_valid:
            return False
        target_piece = self.board.get_piece_at(move.target)
        if target_piece != EMPTY_CELL and target_piece.color == move.piece.color:
            return False
        return True

    def _apply_move(self, move):
        if move.origin == move.target:
            # A jump landing - the piece never left its square.
            self._begin_rest(move.piece, State.short_rest, move.arrival_time)
            self._publish(MoveCompleted(
                move.move_id, move.piece.id, move.piece.type, move.piece.color,
                move.origin, move.target,
            ))
            return False

        target_piece = self.board.get_piece_at(move.target)
        is_game_over = target_piece != EMPTY_CELL and target_piece.type == PieceType.KING
        if target_piece != EMPTY_CELL:
            self._mark_captured(target_piece, move.move_id)
        if self.board.get_piece_at(move.origin) == move.piece:
            self.board.set_piece_at(move.origin, EMPTY_CELL)
        self.board.place_piece(move.target, move.piece)
        self._begin_rest(move.piece, State.long_rest, move.arrival_time)
        self._publish(MoveCompleted(
            move.move_id, move.piece.id, move.piece.type, move.piece.color,
            move.origin, move.target,
        ))
        if is_game_over:
            self._publish(GameEnded(_opposite_color(target_piece.color)))
        return is_game_over

