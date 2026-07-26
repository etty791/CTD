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
from view.view_config import DEFAULT_BOARD_SIZE


def make_piece_payload(id_, x, y, type_="R", color="w", state="idle", origin=None, target=None, progress=0.0):
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
        progress=progress,
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
                    origin=(2, 3), target=(4, 5), progress=0.25,
                )
            ],
            scores={"w": 3, "b": 1},
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
        assert dto.progress == 0.25

        scores = snapshot.get_scores()
        assert scores == {Color.WHITE: 3, Color.BLACK: 1}
        assert all(isinstance(k, Color) for k in scores)


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
