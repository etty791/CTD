from dataclasses import dataclass
from typing import Optional

from model.piece import Piece, PieceType, Color, State
from rules.promotion import is_promotion_square
from rules.rules_engine import validate_piece_move
from model.position import Position
from real_time.collision_fates import CollisionOutcome, compute_collision_fates, path_cells
from real_time.event_queue import EventKind, EventQueue
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
from observability.metrics import counter
from observability.metrics_config import ARBITER_EVENTS_TOTAL, ARBITER_MOVES_TOTAL, LABEL_EVENT

_arbiter_events_total = counter(ARBITER_EVENTS_TOTAL, (LABEL_EVENT,))
_arbiter_moves_total = counter(ARBITER_MOVES_TOTAL)

REST_DURATION_MS = {
    State.long_rest: LONG_REST_DURATION_MS,
    State.short_rest: SHORT_REST_DURATION_MS,
}

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

def _move_distance(origin, target):
    """Number of animation 'steps' a move takes, used for arrival timing.
    Sliding moves take one step per square; a non-sliding jump (e.g. a
    knight) is a single leap regardless of its Chebyshev distance, matching
    the single-cell path returned by path_cells for such moves.
    """
    if origin == target:
        return 0
    if not _is_straight_line(origin, target):
        return 1
    return max(abs(target.x - origin.x), abs(target.y - origin.y))

class RealTimeArbiter:

    def __init__(
        self,
        board,
        event_bus: Optional[EventBus] = None,
        scheduler: SchedulerKind = DEFAULT_SCHEDULER,
    ):
        self.board = board
        self.pending_moves = []
        self.clock = 0
        self._resting: list[RestingPiece] = []
        self._next_move_id = 1
        self.event_bus = event_bus
        self._scheduler_kind = scheduler
        # Only populated (and only consulted) in EVENT_HEAP mode; harmless
        # and unused otherwise. See real_time/event_queue.py.
        self._events = EventQueue()

    def _new_move_id(self) -> int:
        move_id = self._next_move_id
        self._next_move_id += 1
        return move_id

    def _publish(self, event) -> None:
        """No-op when no event_bus was provided, so callers/tests never
        have to construct one just to use the arbiter."""
        _arbiter_events_total.inc(event=type(event).__name__)
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
        if self._scheduler_kind == SchedulerKind.EVENT_HEAP:
            # A piece captured mid-rest would otherwise leave a stale
            # REST_END scheduled; harmless (the handler no-ops on a
            # non-resting piece) but cancelled anyway for hygiene.
            self._events.cancel(EventKind.REST_END, piece)

    def _drop_moves_for(self, piece: Piece) -> None:
        """Remove every pending Move belonging to `piece` - called the
        instant a piece dies so its stale move can never again be swept up
        as if the piece were still travelling."""
        for move in [m for m in self.pending_moves if m.piece is piece]:
            self._remove_move(move)

    def _remove_move(self, move) -> None:
        """Drop `move` from pending_moves and, in EVENT_HEAP mode, cancel
        whatever COLLISION/VACATE/MOVE_DONE is still scheduled for it - the
        one place every move-removal path funnels through, so a dead move
        can never again be popped off the heap and acted on."""
        if move in self.pending_moves:
            self.pending_moves.remove(move)
        if self._scheduler_kind == SchedulerKind.EVENT_HEAP:
            self._events.cancel(EventKind.COLLISION, move.move_id)
            self._events.cancel(EventKind.VACATE, move.move_id)
            self._events.cancel(EventKind.MOVE_DONE, move.move_id)

    def _place_piece(self, position: Position, piece: Piece) -> None:
        """Land `piece` on `position` and apply promotion - the arbiter's
        job, not Board's, since promotion is a rule (rules/promotion.py)."""
        self.board.place_piece(position, piece)
        if is_promotion_square(self.board, piece):
            piece.type = PieceType.QUEEN

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
        _arbiter_moves_total.inc()
        self._publish(MoveStarted(
            move.move_id, piece.id, origin, target, move.start_time, move.arrival_time,
        ))
        self._schedule_move(move)
        return True

    def add_jump(self, piece, pos):
        if piece.state != State.idle:
            return False
        arrival_time = self.clock + DEFAULT_MOVE_DELAY_MS
        move = Move(piece, pos, pos, arrival_time, self.clock, self._new_move_id())
        piece.state = State.airborne
        self.pending_moves.append(move)
        _arbiter_moves_total.inc()
        self._publish(MoveStarted(
            move.move_id, piece.id, pos, pos, move.start_time, move.arrival_time,
        ))
        self._schedule_move(move)
        return True

    def _schedule_move(self, move) -> None:
        """EVENT_HEAP mode only: give a freshly-added move its VACATE (if it
        actually leaves its origin) and MOVE_DONE events, then recompute
        every pending move's collision fate from scratch - the newcomer may
        have changed who collides with whom."""
        if self._scheduler_kind != SchedulerKind.EVENT_HEAP:
            return
        if move.origin != move.target:
            self._events.schedule(
                move.start_time + DEFAULT_MOVE_DELAY_MS, EventKind.VACATE, move.move_id, move
            )
        self._events.schedule(move.arrival_time, EventKind.MOVE_DONE, move.move_id, move)
        self._recompute_fates()

    def advance_time(self, ms):
        target_ms = self.clock + ms
        if self._scheduler_kind == SchedulerKind.EVENT_HEAP:
            return self._advance_to_event_heap(target_ms)
        return self._advance_time_tick_sweep(ms)

    def _advance_time_tick_sweep(self, ms):
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

    # ------------------------------------------------------------------
    # Event-heap scheduler (MIGRATION.md phase 2)
    # ------------------------------------------------------------------

    def next_event_time(self) -> Optional[int]:
        """EVENT_HEAP mode only: the clock time of the earliest pending
        event, or None if the game is fully settled (nothing scheduled).
        Lets a caller (server/game_shard.py) park a game's wake instead of
        polling it every tick."""
        return self._events.peek_time()

    def _advance_to_event_heap(self, target_ms: int) -> bool:
        """Drain every event up to and including `target_ms`, advancing
        `self.clock` to each one's own time as it is handled (so timing
        anchored to move.start_time/arrival_time - _begin_rest chief among
        them - is unaffected by how coarsely advance_time was called), then
        snapping to target_ms once the heap is empty or has nothing left
        due. Events sharing one millisecond are handled in
        EventKind priority order (see event_queue.py's docstring): every
        COLLISION first, then a fate recompute (a capture can change who
        else collides), then VACATE, then MOVE_DONE (batched together so
        simultaneous arrivals at one target still go through
        _resolve_collision), then REST_END."""
        king_captured = False
        while True:
            time_ms = self._events.peek_time()
            if time_ms is None or time_ms > target_ms:
                break
            self.clock = time_ms
            due = self._events.pop_due_at(time_ms)
            collisions = [e for e in due if e.kind == EventKind.COLLISION]
            vacates = [e for e in due if e.kind == EventKind.VACATE]
            arrivals = [e for e in due if e.kind == EventKind.MOVE_DONE]
            rest_ends = [e for e in due if e.kind == EventKind.REST_END]

            for event in collisions:
                king_captured = self._handle_collision_event(event.key, event.payload) or king_captured
            if collisions:
                self._recompute_fates()

            for event in vacates:
                self._handle_vacate_event(event.key)

            if arrivals:
                king_captured = self._handle_move_done_batch(arrivals) or king_captured
                self._recompute_fates()

            for event in rest_ends:
                self._handle_rest_end_event(event.payload)
        self.clock = target_ms
        return king_captured

    def _recompute_fates(self) -> None:
        """EVENT_HEAP mode only: recompute every pending move's collision
        fate from one pairwise scan (real_time.collision_fates - the same
        scan the legacy sweep ran every tick) and apply it - a single pass,
        deliberately not iterated to a fixed point. A truncation found in
        this pass can itself change another move's path, but legacy never
        re-scans within one call either: it applies whatever one
        `_resolve_path_collisions` call finds and leaves any second-order
        effect to be discovered independently, generally by the untouched
        move's own arrival-time revalidation (`_is_still_valid`, which
        already rejects a path blocked by a piece that has since landed in
        it, and `_retreat_vacated_move`). Iterating here to a fixed point
        would let one truncation cascade into pre-emptively truncating a
        second move that legacy only ever discovers via that arrival-time
        path - a real behavioral divergence caught by
        tests/test_collisions.py's TestFriendlyCollisionsEdgeCases, not a
        timing artifact like the ones documented in
        tests/test_scheduler_equivalence.py. CAPTURE fates are (re)scheduled
        as COLLISION events at their resolution_time rather than applied
        here - the event fires and actually destroys the piece once the
        clock reaches it."""
        fates = compute_collision_fates(self.pending_moves, DEFAULT_MOVE_DELAY_MS)
        for move in list(self.pending_moves):
            fate = fates.get(move.move_id)
            if fate is not None and fate.outcome == CollisionOutcome.TRUNCATE:
                self._truncate_move(move, list(fate.path), fate.cell)

        for move in self.pending_moves:
            fate = fates.get(move.move_id)
            if fate is not None and fate.outcome == CollisionOutcome.CAPTURE:
                self._events.schedule(
                    fate.resolution_time, EventKind.COLLISION, move.move_id, fate.capturing_move_id
                )
            else:
                self._events.cancel(EventKind.COLLISION, move.move_id)

    def _find_move(self, move_id: int):
        for move in self.pending_moves:
            if move.move_id == move_id:
                return move
        return None

    def _handle_collision_event(self, move_id: int, capturing_move_id: int) -> bool:
        move = self._find_move(move_id)
        if move is None:
            return False  # superseded - the move already left pending_moves
        return self._capture_in_flight(move, capturing_move_id)

    def _handle_vacate_event(self, move_id: int) -> None:
        move = self._find_move(move_id)
        if move is None:
            return
        if move.piece.state == State.airborne or move.origin == move.target:
            return
        if self.board.get_piece_at(move.origin) == move.piece:
            self.board.set_piece_at(move.origin, None)

    def _handle_move_done_batch(self, events) -> bool:
        arrived = []
        for event in events:
            move = self._find_move(event.key)
            if move is None:
                continue
            self._remove_move(move)
            arrived.append(move)

        king_captured = False
        for target, moves in self._group_by_target(arrived).items():
            if len(moves) > 1:
                king_captured = self._resolve_collision(moves, target) or king_captured
            else:
                king_captured = self._resolve_single(moves[0]) or king_captured
        return king_captured

    def _handle_rest_end_event(self, piece: Piece) -> None:
        if not piece.state.is_resting():
            return
        piece.state = State.idle
        self._publish(RestEnded(piece.id, piece.position))
        self._resting = [entry for entry in self._resting if entry.piece is not piece]

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
                self.board.set_piece_at(move.origin, None)

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
        rest_until_ms = stop_time_ms + REST_DURATION_MS[rest_state]
        self._resting.append(RestingPiece(piece, rest_until_ms))
        if self._scheduler_kind == SchedulerKind.EVENT_HEAP:
            # Keyed by the piece object itself (identity), not piece.id -
            # piece.id is a caller-supplied label that several test fixtures
            # (and, in principle, callers in general) do not guarantee is
            # unique across pieces, and a collision there would let one
            # piece's rest-release cancel another's.
            self._events.schedule(rest_until_ms, EventKind.REST_END, piece, piece)

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
                self._place_piece(move.origin, move.piece)
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
        path = path_cells(move.origin, move.target)
        # Nearest-to-target first: path cells (excluding the contested
        # target) walked backwards, then origin as the final fallback.
        candidates = list(reversed(path[:-1])) + [move.origin]
        for cell in candidates:
            if self.board.is_cell_empty(cell):
                self._place_piece(cell, move.piece)
                self._begin_rest(move.piece, State.long_rest, move.arrival_time)
                self._publish(MoveTruncated(
                    move.move_id, move.piece.id, cell, move.arrival_time, in_flight=False,
                ))
                return
        # Not believed reachable (the origin is always a candidate and,
        # per the vacate proof, is free unless something else has already
        # landed there) - but must not crash if it somehow happens.
        self._mark_captured(move.piece, move.move_id)

    # ------------------------------------------------------------------
    # Rules 2 & 3: temporal path-collision detection
    # ------------------------------------------------------------------

    def _resolve_path_collisions(self):
        """Look for any two in-flight pieces whose paths cross, and resolve
        the earliest crossing for each of them (the pairwise scan itself
        lives in real_time.collision_fates, pure and reusable by the
        event-heap scheduler). Handles both standard moving collisions and
        airborne interceptions."""
        moves = self.pending_moves
        fates = compute_collision_fates(moves, DEFAULT_MOVE_DELAY_MS)

        king_captured = False
        for move in list(moves):
            if move not in self.pending_moves:
                # Already dropped underneath us - e.g. its piece was
                # marked captured while resolving another move's fate.
                continue
            fate = fates.get(move.move_id)
            if fate is None:
                continue
            if fate.outcome == CollisionOutcome.CAPTURE:
                if fate.resolution_time > self.clock:
                    # The paths cross, but the pieces haven't actually
                    # reached the shared cell yet - re-derived and applied
                    # once self.clock catches up to resolution_time.
                    continue
                king_captured = self._capture_in_flight(move, fate.capturing_move_id) or king_captured
            else:
                self._truncate_move(move, list(fate.path), fate.cell)
        return king_captured

    def _destroy_in_transit(self, move, capturing_move_id) -> bool:
        """Destroy a piece that lost a race for a shared square while still
        mid-flight. Returns True if it was a king (publishing GameEnded for
        the surviving side), so every caller propagates game-over
        identically. _mark_captured is idempotent and evicts the piece's
        own pending move, so callers need not touch pending_moves
        themselves."""
        if self.board.get_piece_at(move.origin) == move.piece:
            self.board.set_piece_at(move.origin, None)
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
            self._remove_move(move)
            return
        if self._scheduler_kind == SchedulerKind.EVENT_HEAP:
            # Still travelling, but arrival_time just changed - the
            # MOVE_DONE scheduled when this move was added is stale.
            self._events.schedule(move.arrival_time, EventKind.MOVE_DONE, move.move_id, move)
        self._publish(MoveTruncated(
            move.move_id, move.piece.id, move.target, move.arrival_time, in_flight=True,
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
        if target_piece is not None and target_piece.color == move.piece.color:
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
        is_game_over = target_piece is not None and target_piece.type == PieceType.KING
        if target_piece is not None:
            self._mark_captured(target_piece, move.move_id)
        if self.board.get_piece_at(move.origin) == move.piece:
            self.board.set_piece_at(move.origin, None)
        self._place_piece(move.target, move.piece)
        self._begin_rest(move.piece, State.long_rest, move.arrival_time)
        self._publish(MoveCompleted(
            move.move_id, move.piece.id, move.piece.type, move.piece.color,
            move.origin, move.target,
        ))
        if is_game_over:
            self._publish(GameEnded(_opposite_color(target_piece.color)))
        return is_game_over

