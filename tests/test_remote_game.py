import pytest

from model.board import EMPTY_CELL
from model.game_snapshot import PieceDTO
from model.piece import Color, PieceType, State
from model.position import Position
from client.remote_game import (
    MOVE_OK_REASON,
    OBSERVER_CANNOT_MOVE_REASON,
    RemoteBoardView,
    RemoteGame,
    RemoteGameState,
)
from events.game_events import GameEnded, GameStarted
from shared.messages import (
    GameOverPayload,
    JumpPayload,
    MovePayload,
    PiecePayload,
    PositionPayload,
    RatingChangePayload,
    StatePayload,
)
from shared.protocol import Envelope, MessageType
from view.view_config import DEFAULT_BOARD_SIZE, MS_PER_SECOND

MOVE_START_MS = 1000
MOVE_DURATION_MS = 2000
MOVE_ARRIVAL_MS = MOVE_START_MS + MOVE_DURATION_MS
# An arbitrary monotonic reading standing in for "when the frame landed".
FRAME_RECEIVED_AT_S = 500.0


def moving_state(received_at_s, server_time_ms=MOVE_START_MS) -> RemoteGameState:
    """A one-piece frame with a piece in flight from (2,3) to (4,5)."""
    return RemoteGameState.from_payload(
        StatePayload(
            pieces=[
                make_piece_payload(
                    1, 2, 3, state="moving", origin=(2, 3), target=(4, 5),
                    move_start_ms=MOVE_START_MS, move_arrival_ms=MOVE_ARRIVAL_MS,
                )
            ],
            scores={"w": 0, "b": 0},
            server_time_ms=server_time_ms,
        ),
        received_at_s=received_at_s,
    )


def make_piece_payload(
    id_, x, y, type_="R", color="w", state="idle", origin=None, target=None,
    move_start_ms=None, move_arrival_ms=None,
):
    origin = origin or (x, y)
    target = target or (x, y)
    return PiecePayload(
        id=id_,
        position=PositionPayload(x=x, y=y),
        type=type_,
        color=color,
        state=state,
        origin=PositionPayload(x=origin[0], y=origin[1]),
        target=PositionPayload(x=target[0], y=target[1]),
        move_start_ms=move_start_ms,
        move_arrival_ms=move_arrival_ms,
    )


class FakeConnection:
    def __init__(self):
        self.sent: list[Envelope] = []

    def send(self, envelope: Envelope) -> None:
        self.sent.append(envelope)


def board_view_over(*piece_payloads) -> RemoteBoardView:
    state = RemoteGameState.from_payload(
        StatePayload(pieces=list(piece_payloads), scores={"w": 0, "b": 0})
    )
    return RemoteBoardView(lambda: state)


class TestRemoteBoardView:
    def test_occupied_and_empty_cells(self):
        board = board_view_over(
            make_piece_payload(1, 0, 0, color="w"), make_piece_payload(2, 7, 7, color="b")
        )

        assert not board.is_cell_empty(Position(0, 0))
        piece = board.get_piece_at(Position(0, 0))
        assert isinstance(piece, PieceDTO)
        assert piece.color == Color.WHITE

        other = board.get_piece_at(Position(7, 7))
        assert other.color == Color.BLACK

        assert board.is_cell_empty(Position(3, 3))
        assert board.get_piece_at(Position(3, 3)) is EMPTY_CELL

    def test_tracks_the_current_state(self):
        game = RemoteGame(FakeConnection(), is_observer=False)
        game.apply_state(
            StatePayload(pieces=[make_piece_payload(1, 0, 0)], scores={"w": 0, "b": 0})
        )
        assert not game.board.is_cell_empty(Position(0, 0))

        game.apply_state(
            StatePayload(pieces=[make_piece_payload(1, 4, 4)], scores={"w": 0, "b": 0})
        )

        assert game.board.is_cell_empty(Position(0, 0))
        assert not game.board.is_cell_empty(Position(4, 4))

    def test_boundaries(self):
        board = board_view_over()
        assert board.is_within_boundaries(Position(0, 0))
        assert board.is_within_boundaries(Position(DEFAULT_BOARD_SIZE - 1, DEFAULT_BOARD_SIZE - 1))
        assert not board.is_within_boundaries(Position(-1, 0))
        assert not board.is_within_boundaries(Position(0, DEFAULT_BOARD_SIZE))


class TestRemoteGameState:
    def test_no_state_yet_returns_empty_and_zeroed(self):
        game = RemoteGame(FakeConnection(), is_observer=False)

        snapshot = game.get_snapshot()

        assert snapshot.get_all_pieces() == []
        assert snapshot.get_scores() == {Color.WHITE: 0, Color.BLACK: 0}

    def test_apply_state_reconstructs_typed_dtos(self):
        game = RemoteGame(FakeConnection(), is_observer=False)
        state = StatePayload(
            pieces=[
                make_piece_payload(
                    1, 2, 3, type_="N", color="w", state="moving",
                    origin=(2, 3), target=(4, 5),
                    move_start_ms=MOVE_START_MS, move_arrival_ms=MOVE_ARRIVAL_MS,
                )
            ],
            scores={"w": 3, "b": 1},
            server_time_ms=MOVE_START_MS,
        )

        game.apply_state(state)
        snapshot = game.get_snapshot()
        pieces = snapshot.get_all_pieces()

        assert len(pieces) == 1
        dto = pieces[0]
        assert isinstance(dto, PieceDTO)
        assert dto.id == 1
        assert dto.position == Position(2, 3)
        assert dto.type is PieceType.KNIGHT
        assert dto.color is Color.WHITE
        assert dto.state is State.moving
        assert dto.origin == Position(2, 3)
        assert dto.target == Position(4, 5)
        assert dto.move_start_ms == MOVE_START_MS
        assert dto.move_arrival_ms == MOVE_ARRIVAL_MS

        scores = snapshot.get_scores()
        assert scores == {Color.WHITE: 3, Color.BLACK: 1}
        assert all(isinstance(k, Color) for k in scores)


class TestProgressInterpolation:
    """The server sends a frame only when something changed, so the client is
    what turns a move's absolute start/arrival times into smooth motion."""

    def test_progress_advances_with_wall_clock_between_frames(self):
        state = moving_state(received_at_s=FRAME_RECEIVED_AT_S)

        half_way = FRAME_RECEIVED_AT_S + (MOVE_DURATION_MS / 2) / MS_PER_SECOND
        assert state.get_all_pieces(now_s=FRAME_RECEIVED_AT_S)[0].progress == 0.0
        assert state.get_all_pieces(now_s=half_way)[0].progress == pytest.approx(0.5)

    def test_progress_clamps_at_arrival(self):
        state = moving_state(received_at_s=FRAME_RECEIVED_AT_S)

        long_past_arrival = FRAME_RECEIVED_AT_S + (MOVE_DURATION_MS * 3) / MS_PER_SECOND

        assert state.get_all_pieces(now_s=long_past_arrival)[0].progress == 1.0

    def test_a_frame_arriving_mid_move_resumes_from_the_server_clock(self):
        # The frame was encoded a quarter of the way through the move: the
        # client must start there, not at 0.
        state = moving_state(
            received_at_s=FRAME_RECEIVED_AT_S,
            server_time_ms=MOVE_START_MS + MOVE_DURATION_MS // 4,
        )

        assert state.get_all_pieces(now_s=FRAME_RECEIVED_AT_S)[0].progress == pytest.approx(0.25)

    def test_resting_piece_never_animates(self):
        state = RemoteGameState.from_payload(
            StatePayload(
                pieces=[make_piece_payload(1, 2, 3, state="long_rest")],
                scores={"w": 0, "b": 0},
                server_time_ms=MOVE_ARRIVAL_MS,
            ),
            received_at_s=FRAME_RECEIVED_AT_S,
        )

        far_later = FRAME_RECEIVED_AT_S + MOVE_DURATION_MS / MS_PER_SECOND

        assert state.get_all_pieces(now_s=far_later)[0].progress == 0.0

    def test_board_view_reads_the_authoritative_position_not_the_animation(self):
        # Interpolation is purely visual: the controller must still see the
        # moving piece on the square the server says it occupies.
        state = moving_state(received_at_s=FRAME_RECEIVED_AT_S)
        board = RemoteBoardView(lambda: state)

        assert not board.is_cell_empty(Position(2, 3))
        assert board.is_cell_empty(Position(4, 5))


class TestMoveRequest:
    def test_player_sends_move_envelope_that_round_trips(self):
        conn = FakeConnection()
        game = RemoteGame(conn, is_observer=False)

        result = game.move_request(Position(6, 0), Position(5, 0))

        assert result.is_valid
        assert result.reason == MOVE_OK_REASON
        assert len(conn.sent) == 1
        envelope = conn.sent[0]
        assert envelope.type == MessageType.MOVE
        # Proves by_alias=True was used: validating the dumped dict recovers "from"/"to".
        move_payload = MovePayload.model_validate(envelope.payload)
        assert move_payload.from_.to_position() == Position(6, 0)
        assert move_payload.to.to_position() == Position(5, 0)

    def test_observer_sends_nothing_and_is_rejected(self):
        conn = FakeConnection()
        game = RemoteGame(conn, is_observer=True)

        result = game.move_request(Position(6, 0), Position(5, 0))

        assert not result.is_valid
        assert result.reason == OBSERVER_CANNOT_MOVE_REASON
        assert conn.sent == []


class TestJumpRequest:
    def test_player_sends_jump_envelope_that_round_trips(self):
        conn = FakeConnection()
        game = RemoteGame(conn, is_observer=False)

        result = game.jump_request(Position(3, 4))

        assert result.is_valid
        assert result.reason == MOVE_OK_REASON
        assert len(conn.sent) == 1
        envelope = conn.sent[0]
        assert envelope.type == MessageType.JUMP
        jump_payload = JumpPayload.model_validate(envelope.payload)
        assert jump_payload.pos.to_position() == Position(3, 4)

    def test_observer_sends_nothing_and_is_rejected(self):
        conn = FakeConnection()
        game = RemoteGame(conn, is_observer=True)

        result = game.jump_request(Position(3, 4))

        assert not result.is_valid
        assert result.reason == OBSERVER_CANNOT_MOVE_REASON
        assert conn.sent == []


class TestWait:
    def test_first_wait_publishes_game_started_once(self):
        game = RemoteGame(FakeConnection(), is_observer=False)
        received = []
        game.events.subscribe(GameStarted, lambda e: received.append(e))

        game.wait(16)
        game.wait(16)
        game.wait(16)

        assert len(received) == 1


class TestEndGame:
    def test_marks_inactive_stores_payload_and_publishes_game_ended(self):
        game = RemoteGame(FakeConnection(), is_observer=False)
        received = []
        game.events.subscribe(GameEnded, lambda e: received.append(e))
        payload = GameOverPayload(
            winner="w",
            reason="king_captured",
            rating_changes=[RatingChangePayload(username="alice", old_rating=1200, new_rating=1216)],
        )

        game.end_game(payload)

        assert game.game_active is False
        assert game.game_over_payload is payload
        assert len(received) == 1
        assert received[0] == GameEnded(Color.WHITE)
