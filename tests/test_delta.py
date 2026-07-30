"""The delta protocol's load-bearing property: a client seeded with one
keyframe and fed nothing but deltas must agree with the server, move for
move, for a whole game.

Everything else in phase 1 -- sequence numbers, RESYNC, dropping the
heartbeat -- rests on that being true, so it is tested directly here against
real engines rather than hand-built op lists (those live in
tests/test_encoding.py and tests/test_remote_game.py).
"""

import random

import pytest

from client.remote_game import RemoteGameState
from events.game_events import GameEnded, PieceCaptured
from game_engine.game import KungFuChessGame
from model.board import BOARD_SIZE
from model.piece import Color, Piece, PieceType, State
from model.position import Position
from real_time.real_time_config import DEFAULT_MOVE_DELAY_MS
from rules.rules_engine import validate_piece_move
from server.delta import DeltaBuilder
from server.encoding import keyframe_payload_from_snapshot
from server.game_session import STATE_CHANGING_EVENTS
from server.server_config import TICK_MS
from shared.delta_ops import OpCode
from shared.messages import DeltaPayload

COMMAND_INTERVAL_MS = 2000
GAME_HORIZON_MS = 60_000
# Enough seeded games to walk through captures, truncations, aborts, jumps
# and promotions without pinning the test to one lucky script.
SCRIPT_SEEDS = [1, 7, 42, 99, 2024]


class _ScriptedGame:
    """One engine plus the delta stream a GameSession would produce for it,
    and a client state kept in lockstep from that stream alone."""

    def __init__(self, seed: int):
        self.engine = KungFuChessGame()
        self.rng = random.Random(seed)
        self.clock_ms = 0
        self.delta = DeltaBuilder(lambda: self.engine.get_snapshot().get_scores())
        for event_type in STATE_CHANGING_EVENTS:
            self.engine.events.subscribe(event_type, self.delta.on_event)
        # The client starts from the one keyframe it will ever be given.
        self.client = RemoteGameState.from_keyframe(
            keyframe_payload_from_snapshot(self.engine.get_snapshot())
        )
        self.frames = 0
        self.ops = 0
        self.next_command_ms = {Color.WHITE: 0, Color.BLACK: COMMAND_INTERVAL_MS // 2}

    def _idle_piece(self, color: Color):
        board = self.engine.board
        candidates = [
            (piece, Position(row, col))
            for row in range(BOARD_SIZE)
            for col in range(BOARD_SIZE)
            for piece in [board.get_piece_at(Position(row, col))]
            if piece is not None and piece.color == color and piece.state == State.idle
        ]
        return self.rng.choice(candidates) if candidates else (None, None)

    def _command(self, color: Color) -> None:
        if not self.engine.game_active or self.clock_ms < self.next_command_ms[color]:
            return
        self.next_command_ms[color] += COMMAND_INTERVAL_MS
        piece, origin = self._idle_piece(color)
        if piece is None:
            return
        destinations = [
            dest
            for row in range(BOARD_SIZE)
            for col in range(BOARD_SIZE)
            for dest in [Position(row, col)]
            if dest != origin and validate_piece_move(self.engine.board, piece, dest).is_valid
        ]
        if destinations:
            self.engine.move_request(origin, self.rng.choice(destinations))
        else:
            self.engine.jump_request(origin)

    def tick(self, ms: int) -> None:
        self.clock_ms += ms
        self._command(Color.WHITE)
        self._command(Color.BLACK)
        self.engine.wait(ms)
        if self.delta.has_ops():
            ops = self.delta.drain()
            self.frames += 1
            self.ops += len(ops)
            self.client = self.client.apply_delta(
                DeltaPayload(
                    ops=ops, server_time_ms=self.engine.get_snapshot().get_clock_ms()
                )
            )

    def assert_in_sync(self) -> None:
        """The client's board must equal a keyframe taken right now. `progress`
        is excluded deliberately: the server samples it at encode time and the
        client recomputes it against wall-clock, so they are meant to differ."""
        keyframe = keyframe_payload_from_snapshot(self.engine.get_snapshot())
        expected = {piece.id: piece.to_piece_dto() for piece in keyframe.pieces}
        actual = self.client.pieces

        assert set(actual) == set(expected)
        for piece_id, want in expected.items():
            got = actual[piece_id]
            assert (
                got.position, got.type, got.color, got.state,
                got.origin, got.target, got.move_start_ms, got.move_arrival_ms,
            ) == (
                want.position, want.type, want.color, want.state,
                want.origin, want.target, want.move_start_ms, want.move_arrival_ms,
            ), f"piece {piece_id} diverged: {got} != {want}"

        assert self.client.get_scores() == self.engine.get_snapshot().get_scores()


class TestKeyframeDeltaEquivalence:
    @pytest.mark.parametrize("seed", SCRIPT_SEEDS)
    def test_a_whole_game_stays_in_sync_from_one_keyframe(self, seed):
        scripted = _ScriptedGame(seed)

        while scripted.clock_ms < GAME_HORIZON_MS and scripted.engine.game_active:
            scripted.tick(TICK_MS)
            scripted.assert_in_sync()

        assert scripted.frames > 0, "the script never produced a frame to test"

    @pytest.mark.parametrize("seed", SCRIPT_SEEDS)
    def test_coarse_and_fine_ticking_agree(self, seed):
        """Several events landing in one pass coalesce into one frame; that
        frame must leave the client exactly where a frame per event would."""
        fine, coarse = _ScriptedGame(seed), _ScriptedGame(seed)

        while fine.clock_ms < GAME_HORIZON_MS and fine.engine.game_active:
            for _ in range(4):
                fine.tick(TICK_MS)
            coarse.tick(4 * TICK_MS)

        assert coarse.frames <= fine.frames
        coarse.assert_in_sync()
        fine.assert_in_sync()


class TestScriptsCoverTheInterestingOps:
    """A sync test proves nothing if the scripts only ever produce `m` ops."""

    def test_captures_landings_aborts_and_rests_all_occur(self):
        seen: set[str] = set()
        for seed in SCRIPT_SEEDS:
            scripted = _ScriptedGame(seed)
            builder = scripted.delta
            original_drain = builder.drain

            def drain(_original=original_drain):
                ops = _original()
                seen.update(op[0] for op in ops)
                return ops

            builder.drain = drain
            while scripted.clock_ms < GAME_HORIZON_MS and scripted.engine.game_active:
                scripted.tick(TICK_MS)

        assert {
            OpCode.MOVE_STARTED.value,
            OpCode.MOVE_COMPLETED.value,
            OpCode.MOVE_ABORTED.value,
            OpCode.PIECE_CAPTURED.value,
            OpCode.REST_ENDED.value,
            OpCode.SCORES.value,
        } <= seen


class _StagedGame:
    """A hand-built board driven by an explicit script, for the collisions the
    random games above don't reliably reach."""

    def __init__(self, pieces):
        grid = [[None] * BOARD_SIZE for _ in range(BOARD_SIZE)]
        for piece_id, (color, piece_type, x, y) in enumerate(pieces):
            grid[x][y] = Piece(piece_id, color.value, piece_type.value, Position(x, y))
        self.engine = KungFuChessGame(grid)
        self.delta = DeltaBuilder(lambda: self.engine.get_snapshot().get_scores())
        for event_type in STATE_CHANGING_EVENTS:
            self.engine.events.subscribe(event_type, self.delta.on_event)
        self.client = RemoteGameState.from_keyframe(
            keyframe_payload_from_snapshot(self.engine.get_snapshot())
        )
        self.op_codes: set[str] = set()

    def move(self, origin: Position, target: Position) -> None:
        self.engine.move_request(origin, target)

    def unvalidated_move(self, origin: Position, target: Position) -> None:
        """Enqueue a move the rules engine would refuse up front, to stage a
        move that only becomes impossible once it arrives. The arbiter is
        reached directly because that is exactly what this exercises: how the
        client tracks a move that dies in flight."""
        self.engine.rta.add_move(self.engine.board.get_piece_at(origin), origin, target)

    def run(self, ms: int) -> None:
        for _ in range(ms // TICK_MS):
            self.engine.wait(TICK_MS)
            if self.delta.has_ops():
                ops = self.delta.drain()
                self.op_codes.update(op[0] for op in ops)
                self.client = self.client.apply_delta(
                    DeltaPayload(
                        ops=ops, server_time_ms=self.engine.get_snapshot().get_clock_ms()
                    )
                )
            _assert_in_sync(self.client, self.engine)


def _assert_in_sync(client: RemoteGameState, engine: KungFuChessGame) -> None:
    keyframe = keyframe_payload_from_snapshot(engine.get_snapshot())
    expected = {piece.id: piece.to_piece_dto() for piece in keyframe.pieces}
    assert set(client.pieces) == set(expected)
    for piece_id, want in expected.items():
        got = client.pieces[piece_id]
        assert (
            got.position, got.type, got.color, got.state,
            got.origin, got.target, got.move_start_ms, got.move_arrival_ms,
        ) == (
            want.position, want.type, want.color, want.state,
            want.origin, want.target, want.move_start_ms, want.move_arrival_ms,
        ), f"piece {piece_id} diverged: {got} != {want}"


class TestStagedCollisionEquivalence:
    def test_a_move_truncated_in_flight_stays_in_sync(self):
        """A same-color blocker shortens a move mid-flight: the client must
        retarget the piece rather than let it slide to where it was headed."""
        staged = _StagedGame([
            (Color.WHITE, PieceType.ROOK, 0, 0),
            (Color.WHITE, PieceType.ROOK, 5, 3),
        ])
        staged.move(Position(0, 0), Position(0, 5))
        staged.move(Position(5, 3), Position(0, 3))

        staged.run(8 * DEFAULT_MOVE_DELAY_MS)

        assert OpCode.MOVE_TRUNCATED.value in staged.op_codes

    def test_a_retreating_move_stays_in_sync(self):
        """The other flavour of truncation: the move is over and the piece has
        already retreated onto the cell the op names."""
        staged = _StagedGame([
            (Color.WHITE, PieceType.ROOK, 0, 0),
            (Color.WHITE, PieceType.PAWN, 0, 3),
        ])
        staged.unvalidated_move(Position(0, 0), Position(0, 3))

        staged.run(8 * DEFAULT_MOVE_DELAY_MS)

        assert OpCode.MOVE_TRUNCATED.value in staged.op_codes
        assert staged.engine.board.get_piece_at(Position(0, 2)) is not None

    def test_a_promotion_stays_in_sync(self):
        staged = _StagedGame([
            (Color.WHITE, PieceType.PAWN, 1, 0),
            (Color.BLACK, PieceType.KING, 7, 7),
        ])
        staged.move(Position(1, 0), Position(0, 0))

        staged.run(4 * DEFAULT_MOVE_DELAY_MS)

        assert staged.engine.board.get_piece_at(Position(0, 0)).type is PieceType.QUEEN


class TestFrameSize:
    def test_a_move_frame_is_an_order_of_magnitude_smaller_than_a_keyframe(self):
        """Phase 0 measured 4801 bytes/frame for full state. The whole point
        of the delta protocol is that a move now costs a fraction of that."""
        engine = KungFuChessGame()
        builder = DeltaBuilder(lambda: engine.get_snapshot().get_scores())
        for event_type in STATE_CHANGING_EVENTS:
            engine.events.subscribe(event_type, builder.on_event)

        engine.move_request(Position(6, 0), Position(5, 0))
        delta = DeltaPayload(ops=builder.drain(), server_time_ms=0)
        keyframe = keyframe_payload_from_snapshot(engine.get_snapshot())

        assert len(delta.model_dump_json()) * 10 < len(keyframe.model_dump_json())


class TestDeltaBuilder:
    def test_an_idle_pass_has_nothing_to_say(self):
        engine = KungFuChessGame()
        builder = DeltaBuilder(lambda: engine.get_snapshot().get_scores())
        for event_type in STATE_CHANGING_EVENTS:
            engine.events.subscribe(event_type, builder.on_event)

        engine.wait(DEFAULT_MOVE_DELAY_MS)

        assert not builder.has_ops()
        assert builder.drain() == []

    def test_scores_are_reported_once_per_change(self):
        engine = KungFuChessGame()
        builder = DeltaBuilder(lambda: engine.get_snapshot().get_scores())
        for event_type in STATE_CHANGING_EVENTS:
            engine.events.subscribe(event_type, builder.on_event)
        engine.events.publish(
            PieceCaptured(
                piece_id=3, piece_type=PieceType.PAWN, color=Color.BLACK,
                position=Position(4, 0), capturing_move_id=2,
            )
        )

        first = builder.drain()
        engine.move_request(Position(6, 0), Position(5, 0))
        second = builder.drain()

        assert [op[0] for op in first] == [
            OpCode.PIECE_CAPTURED.value, OpCode.SCORES.value
        ]
        assert [op[0] for op in second] == [OpCode.MOVE_STARTED.value]

    def test_game_ended_produces_no_op(self):
        engine = KungFuChessGame()
        builder = DeltaBuilder(lambda: engine.get_snapshot().get_scores())
        for event_type in STATE_CHANGING_EVENTS:
            engine.events.subscribe(event_type, builder.on_event)

        engine.events.publish(GameEnded(Color.WHITE))

        assert not builder.has_ops()
