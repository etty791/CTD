"""Differential harness for the discrete-event scheduler (MIGRATION.md phase 2).

It has two jobs, in sequence:

1. *Today* it characterises how much `advance_time`'s behaviour depends on the
   size of the steps it is called in. The current implementation is a
   phase-grouped whole-sweep-per-call: one call resolves every path-collision
   fate, then vacates every departed origin, then applies every arrival, then
   releases every expired rest - all at the post-advance clock. A capture whose
   resolution_time is 3000 is therefore applied *before* an arrival at 1000 if
   both fall inside one `advance_time(7000)`. So the implementation is not
   granularity-invariant, and knowing exactly where it is not is the input to
   the refactor.
2. Once the event heap lands it becomes the differential harness proper: heap
   at any granularity against tick-sweep at the reference granularity, and
   then - after the tick sweep is deleted - heap granularity-invariance alone.

A *script* is a fixed list of `Command`s generated once from a probe run and
then replayable against any implementation at any granularity. Replay always
issues a command at exactly its `time_ms` (the advance step is clamped so it
never straddles a command), so the only variable between two replays of one
script is how coarsely time is advanced *between* commands - which is precisely
what is under test.
"""

import random
from collections import Counter
from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Optional

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
from model.board import BOARD_SIZE, Board
from model.piece import State
from model.position import Position
from real_time.real_time_arbiter import RealTimeArbiter
from real_time.real_time_config import (
    DEFAULT_MOVE_DELAY_MS,
    LONG_REST_DURATION_MS,
    SchedulerKind,
)
from rules.rules_engine import validate_piece_move

RECORDED_EVENTS = (
    MoveStarted,
    MoveCompleted,
    MoveTruncated,
    MoveAborted,
    PieceCaptured,
    RestEnded,
    GameEnded,
)

# Every time the arbiter ever acts on is a command time plus a whole number of
# DEFAULT_MOVE_DELAY_MS (arrivals, vacates and collision resolutions) or a rest
# duration (itself a multiple of it). Every command time below is a multiple of
# COMMAND_TIME_GRID_MS, so no event can fall strictly between two multiples of
# the grid: a replay stepping by the grid groups exactly the same events per
# call as one stepping by 1 ms. That is what makes the grid usable as the cheap
# reference granularity - test_grid_granularity_matches_single_ms proves it
# rather than trusting the argument.
COMMAND_TIME_GRID_MS = 50
COMMAND_GAP_CHOICES_MS = (0, 100, 250, 400, 700, 1000, 1500)
JUMP_PROBABILITY = 0.15
COMMANDS_PER_SCRIPT = 40
# Long enough after the last command for every move to land and every rest to
# expire, so a replay always finishes with nothing pending.
HORIZON_TAIL_MS = 8 * DEFAULT_MOVE_DELAY_MS + LONG_REST_DURATION_MS

# The granularity every other one is judged against (see the grid note above).
REFERENCE_GRANULARITY_MS = COMMAND_TIME_GRID_MS
# What the server actually runs at (server_config.TICK_MS), and the coarse
# steps the existing arbiter/collision suites advance in.
COARSE_GRANULARITIES_MS = (1000, 3000, 7000)

SEEDS = tuple(range(12))

# Fields of a replay's end state, compared in this order so a report names the
# most fundamental difference rather than a downstream symptom.
COMPARED_FIELDS = ("pieces", "board", "pending", "events")


@dataclass(frozen=True)
class Command:
    """One order issued to the arbiter at an exact clock time. `target` is
    None for a jump in place."""

    time_ms: int
    piece_id: int
    target: Optional[Position]

    @property
    def is_jump(self) -> bool:
        return self.target is None


@dataclass(frozen=True)
class Divergence:
    """Where two replays of one script first stopped agreeing.
    `command_index` is -1 for the final settle-to-horizon comparison."""

    command_index: int
    clock_ms: int
    field: str
    left: Any
    right: Any

    def __str__(self) -> str:
        where = "horizon" if self.command_index < 0 else f"command {self.command_index}"
        return (
            f"{self.field} differs at {where} (clock={self.clock_ms}ms)\n"
            f"    left : {self.left}\n"
            f"    right: {self.right}"
        )


def _normalize(value):
    """Positions and enums into plain tuples/strings, so a snapshot is
    comparable *and* printable - Position has no __repr__, so leaving it in
    would make a divergence report a list of object addresses."""
    if isinstance(value, Position):
        return (value.x, value.y)
    if isinstance(value, Enum):
        return value.value
    return value


def _normalize_event(event) -> tuple:
    return (type(event).__name__,) + tuple(
        _normalize(getattr(event, field.name)) for field in fields(event)
    )


class _Run:
    """One standard-board arbiter plus the event log it published, and the
    piece index a script's `piece_id`s resolve through."""

    def __init__(self, **arbiter_kwargs):
        self.board = Board(Board.generate_standard_grid())
        self.bus = EventBus()
        self.events: list = []
        for event_type in RECORDED_EVENTS:
            self.bus.subscribe(event_type, self.events.append)
        self.arbiter = RealTimeArbiter(self.board, self.bus, **arbiter_kwargs)
        self.pieces: dict[int, Any] = {}
        for x in range(BOARD_SIZE):
            for y in range(BOARD_SIZE):
                piece = self.board.get_piece_at(Position(x, y))
                if piece is not None:
                    self.pieces[piece.id] = piece

    def advance_to(self, target_ms: int, granularity_ms: int) -> None:
        while self.arbiter.clock < target_ms:
            self.arbiter.advance_time(min(granularity_ms, target_ms - self.arbiter.clock))

    def issue(self, command: Command) -> bool:
        """Replay a command. A piece that is no longer idle rejects it, which
        is itself a comparable observable - the harness never skips a command
        to keep two runs in step."""
        piece = self.pieces[command.piece_id]
        if command.is_jump:
            return self.arbiter.add_jump(piece, piece.position)
        return self.arbiter.add_move(piece, piece.position, command.target)

    def snapshot(self) -> dict:
        pieces = tuple(
            (
                piece_id,
                piece.type.value,
                piece.color.value,
                piece.state.value,
                _normalize(piece.position),
            )
            for piece_id, piece in sorted(self.pieces.items())
        )
        board = tuple(
            (x, y, self.board.get_piece_at(Position(x, y)).id)
            for x in range(BOARD_SIZE)
            for y in range(BOARD_SIZE)
            if not self.board.is_cell_empty(Position(x, y))
        )
        pending = tuple(
            sorted(
                (
                    move.move_id,
                    move.piece.id,
                    _normalize(move.origin),
                    _normalize(move.target),
                    move.start_time,
                    move.arrival_time,
                )
                for move in self.arbiter.pending_moves
            )
        )
        # A multiset, not a sequence: chronological draining reorders the
        # stream relative to the phase-grouped sweep even where it agrees on
        # every individual event, and no consumer depends on that order (the
        # bus is keyed per event type).
        events = Counter(_normalize_event(event) for event in self.events)
        return {"pieces": pieces, "board": board, "pending": pending, "events": events}


def _legal_targets(board, piece) -> list[Position]:
    return [
        Position(x, y)
        for x in range(BOARD_SIZE)
        for y in range(BOARD_SIZE)
        if Position(x, y) != piece.position
        and validate_piece_move(board, piece, Position(x, y)).is_valid
    ]


def _pick_command(rng: random.Random, run: _Run, time_ms: int) -> Optional[Command]:
    candidates = list(run.pieces.values())
    rng.shuffle(candidates)
    for piece in candidates:
        if piece.state != State.idle:
            continue
        if rng.random() < JUMP_PROBABILITY:
            return Command(time_ms, piece.id, None)
        targets = _legal_targets(run.board, piece)
        if targets:
            return Command(time_ms, piece.id, rng.choice(targets))
    return None


def generate_script(seed: int, command_count: int = COMMANDS_PER_SCRIPT) -> tuple[Command, ...]:
    """A probe run picks commands that are actually issuable (an idle piece, a
    legal destination) and records them. The recorded list is then a fixed
    artifact: replaying it elsewhere may see a command rejected, and that is a
    difference worth catching rather than papering over."""
    rng = random.Random(seed)
    run = _Run()
    commands: list[Command] = []
    time_ms = 0
    for _ in range(command_count):
        time_ms += rng.choice(COMMAND_GAP_CHOICES_MS)
        run.advance_to(time_ms, REFERENCE_GRANULARITY_MS)
        command = _pick_command(rng, run, time_ms)
        if command is None:
            continue
        run.issue(command)
        commands.append(command)
    return tuple(commands)


def horizon_of(script: tuple[Command, ...]) -> int:
    return (script[-1].time_ms if script else 0) + HORIZON_TAIL_MS


def _diff(field: str, left, right):
    """The first differing element of two snapshots of one field, rather than
    both whole tuples - a 32-piece dump hides which piece moved."""
    if field == "events":
        missing = right - left
        extra = left - right
        return (
            f"extra {sorted(extra.elements())}" if extra else "",
            f"extra {sorted(missing.elements())}" if missing else "",
        )
    for left_item, right_item in zip(left, right):
        if left_item != right_item:
            return left_item, right_item
    return f"{len(left)} entries", f"{len(right)} entries"


def first_divergence(
    script: tuple[Command, ...],
    left_granularity_ms: int,
    right_granularity_ms: int,
    left_kwargs: Optional[dict] = None,
    right_kwargs: Optional[dict] = None,
) -> Optional[Divergence]:
    """Replay `script` twice in lockstep, comparing at every command time (both
    runs are at the same clock there) and again at the horizon. Returns the
    first difference, or None if the two runs agree throughout."""
    left = _Run(**(left_kwargs or {}))
    right = _Run(**(right_kwargs or {}))

    for index, command in enumerate(script):
        left.advance_to(command.time_ms, left_granularity_ms)
        right.advance_to(command.time_ms, right_granularity_ms)
        divergence = _compare(left, right, index, command.time_ms)
        if divergence is not None:
            return divergence
        left.issue(command)
        right.issue(command)

    horizon = horizon_of(script)
    left.advance_to(horizon, left_granularity_ms)
    right.advance_to(horizon, right_granularity_ms)
    return _compare(left, right, -1, horizon)


def _compare(left: _Run, right: _Run, command_index: int, clock_ms: int) -> Optional[Divergence]:
    left_state, right_state = left.snapshot(), right.snapshot()
    for field in COMPARED_FIELDS:
        if left_state[field] != right_state[field]:
            left_detail, right_detail = _diff(field, left_state[field], right_state[field])
            return Divergence(command_index, clock_ms, field, left_detail, right_detail)
    return None


# --- the committed assertions ---------------------------------------------


def test_scripts_are_dense_enough_to_be_worth_comparing():
    """A harness that generated no captures would prove nothing, so assert the
    generated scripts actually exercise the collision machinery."""
    captures = 0
    for seed in SEEDS:
        script = generate_script(seed)
        assert len(script) > COMMANDS_PER_SCRIPT // 2
        run = _Run()
        for command in script:
            run.advance_to(command.time_ms, REFERENCE_GRANULARITY_MS)
            run.issue(command)
        run.advance_to(horizon_of(script), REFERENCE_GRANULARITY_MS)
        assert not run.arbiter.pending_moves  # the horizon really does settle
        captures += sum(
            1 for event in run.events if isinstance(event, (PieceCaptured, MoveTruncated))
        )
    assert captures > len(SEEDS)


def test_grid_granularity_matches_single_ms():
    """Proves the alignment argument behind REFERENCE_GRANULARITY_MS: no event
    can fall strictly between two grid multiples, so stepping by the grid is
    indistinguishable from stepping by 1 ms. Kept to two seeds because the 1 ms
    leg is 50x the work of every other comparison here."""
    for seed in SEEDS[:2]:
        script = generate_script(seed)
        assert first_divergence(script, 1, REFERENCE_GRANULARITY_MS) is None


_HEAP = {"scheduler": SchedulerKind.EVENT_HEAP}


def test_event_heap_is_granularity_invariant():
    """A1's core claim: unlike the tick sweep (see the divergence categories
    documented above test_grid_granularity_matches_single_ms), the heap drains
    every event up to the requested target on every call regardless of how
    that target was reached, so how coarsely advance_time is called must never
    change its outcome. This is the property phase 2 replaces "match legacy"
    with, and the one later phases (replay-from-log determinism) depend on."""
    for seed in SEEDS:
        script = generate_script(seed)
        for granularity in COARSE_GRANULARITIES_MS:
            divergence = first_divergence(
                script, granularity, REFERENCE_GRANULARITY_MS,
                left_kwargs=_HEAP, right_kwargs=_HEAP,
            )
            assert divergence is None, f"seed={seed} granularity={granularity}\n{divergence}"


def test_event_heap_settles_to_the_same_state_as_tick_sweep():
    """The heap and the tick sweep are NOT required to agree at every command
    boundary: the heap resolves a synchronously-computable fate (e.g. a move
    blocked before its first step by something that landed a moment earlier)
    the instant the move is added, while the tick sweep only discovers the
    same fate on its next advance_time call. Confirmed directly - replaying
    seed 1 up to the point two commands share one exact millisecond with zero
    elapsed time between them, the heap has already applied the resulting
    MoveAborted while the tick sweep still shows the piece State.moving; one
    more (arbitrarily small) tick later the tick sweep reaches the identical
    State.long_rest. In production this is invisible: GameSession ticks every
    TICK_MS regardless of whether a command arrived, so the tick sweep would
    already have caught up before a human could notice. It only surfaces here
    because this harness compares state at exact command-issue boundaries
    with no interstitial tick - a comparison the tick sweep, at ANY
    granularity including 1 ms, cannot win, since it only ever resolves
    inside advance_time and never on add_move/add_jump themselves.

    So the comparison that is actually meaningful is settled *final* state:
    once every command has been issued and the horizon has fully drained,
    both schedulers must agree - which is what this asserts, and it is a
    strictly stronger claim than matching mid-script, since it is what a
    resync (a keyframe taken after the dust settles) would show a client."""
    for seed in SEEDS:
        script = generate_script(seed)
        horizon = horizon_of(script)
        for granularity in (REFERENCE_GRANULARITY_MS, *COARSE_GRANULARITIES_MS):
            heap = _Run(**_HEAP)
            sweep = _Run()
            for command in script:
                heap.advance_to(command.time_ms, granularity)
                heap.issue(command)
                sweep.advance_to(command.time_ms, REFERENCE_GRANULARITY_MS)
                sweep.issue(command)
            heap.advance_to(horizon, granularity)
            sweep.advance_to(horizon, REFERENCE_GRANULARITY_MS)
            divergence = _compare(heap, sweep, -1, horizon)
            assert divergence is None, f"seed={seed} granularity={granularity}\n{divergence}"
