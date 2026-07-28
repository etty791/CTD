import pytest
from pydantic import ValidationError

from model.piece import Color, PieceType, State
from model.position import Position
from model.game_snapshot import PieceDTO
from shared.messages import (
    IDLE_PROGRESS,
    AuthAckPayload,
    CredentialsPayload,
    GameOverPayload,
    GameStartPayload,
    JoinRoomPayload,
    JumpPayload,
    MovePayload,
    PiecePayload,
    PositionPayload,
    RatingChangePayload,
    RoomWaitingPayload,
    StatePayload,
)


MOVE_START_MS = 1000
MOVE_ARRIVAL_MS = 4000


def sample_piece_dto():
    return PieceDTO(
        id=1,
        position=Position(0, 0),
        type=PieceType.ROOK,
        color=Color.WHITE,
        state=State.moving,
        origin=Position(0, 0),
        target=Position(0, 3),
        progress=0.5,
        move_start_ms=MOVE_START_MS,
        move_arrival_ms=MOVE_ARRIVAL_MS,
    )


class TestMovePayload:
    def test_valid_payload_parses_via_from_alias(self):
        payload = MovePayload.model_validate({"from": {"x": 0, "y": 1}, "to": {"x": 2, "y": 1}})
        assert payload.from_.to_position() == Position(0, 1)
        assert payload.to.to_position() == Position(2, 1)

    def test_missing_from_raises_validation_error(self):
        with pytest.raises(ValidationError):
            MovePayload.model_validate({"to": {"x": 2, "y": 1}})

    def test_missing_to_raises_validation_error(self):
        with pytest.raises(ValidationError):
            MovePayload.model_validate({"from": {"x": 0, "y": 1}})

    def test_malformed_position_raises_validation_error(self):
        with pytest.raises(ValidationError):
            MovePayload.model_validate({"from": {"x": 0}, "to": {"x": 2, "y": 1}})


class TestPositionPayload:
    def test_round_trips_through_position(self):
        payload = PositionPayload.from_position(Position(3, 4))
        assert payload.to_position() == Position(3, 4)

    @pytest.mark.parametrize("x, y", [(-1, 0), (0, -1), (8, 0), (0, 8)])
    def test_rejects_out_of_bounds_coordinates(self, x, y):
        with pytest.raises(ValidationError):
            PositionPayload(x=x, y=y)


class TestPiecePayload:
    def test_from_piece_dto_mirrors_dto_fields(self):
        payload = PiecePayload.from_piece_dto(sample_piece_dto())

        assert payload.model_dump() == {
            "id": 1,
            "position": {"x": 0, "y": 0},
            "type": "R",
            "color": "w",
            "state": "moving",
            "origin": {"x": 0, "y": 0},
            "target": {"x": 0, "y": 3},
            "move_start_ms": MOVE_START_MS,
            "move_arrival_ms": MOVE_ARRIVAL_MS,
        }

    def test_dto_round_trips_through_the_wire(self):
        dto = sample_piece_dto()

        restored = PiecePayload.model_validate_json(
            PiecePayload.from_piece_dto(dto).model_dump_json()
        ).to_piece_dto(progress=dto.progress)

        assert restored == dto
        assert restored.type is PieceType.ROOK
        assert restored.color is Color.WHITE
        assert restored.state is State.moving

    def test_progress_is_not_on_the_wire_and_defaults_to_idle(self):
        # The sampled fraction is deliberately absent: the receiver derives it
        # from the move times, which is what lets frames be sent on change.
        restored = PiecePayload.from_piece_dto(sample_piece_dto()).to_piece_dto()

        assert restored.progress == IDLE_PROGRESS

    def test_resting_piece_has_no_move_times(self):
        dto = sample_piece_dto()
        dto.move_start_ms = None
        dto.move_arrival_ms = None

        payload = PiecePayload.from_piece_dto(dto)

        assert payload.move_start_ms is None
        assert payload.move_arrival_ms is None
        assert payload.to_piece_dto().move_start_ms is None


class TestStatePayload:
    def test_round_trips_through_json(self):
        payload = StatePayload(
            pieces=[PiecePayload.from_piece_dto(sample_piece_dto())],
            scores={"w": 1, "b": 0},
            server_time_ms=2500,
        )

        restored = StatePayload.model_validate_json(payload.model_dump_json())

        assert restored == payload
        assert restored.server_time_ms == 2500
        assert set(payload.model_dump().keys()) == {"pieces", "scores", "server_time_ms"}


class TestCredentialsPayload:
    def test_round_trips(self):
        payload = CredentialsPayload(username="alice", password="pw")
        restored = CredentialsPayload.model_validate(payload.model_dump())
        assert restored.username == "alice"
        assert restored.password == "pw"

    def test_missing_password_raises(self):
        with pytest.raises(ValidationError):
            CredentialsPayload.model_validate({"username": "alice"})


class TestAuthAckPayload:
    def test_validates_without_rating(self):
        payload = AuthAckPayload.model_validate({"status": "ok", "player_id": "alice"})
        assert payload.rating is None

    def test_validates_with_rating(self):
        payload = AuthAckPayload.model_validate(
            {"status": "ok", "player_id": "alice", "rating": 1234}
        )
        assert payload.rating == 1234

    def test_round_trips_through_json(self):
        payload = AuthAckPayload(status="ok", player_id="alice", rating=1200)
        restored = AuthAckPayload.model_validate_json(payload.model_dump_json())
        assert restored == payload


class TestJoinRoomPayload:
    def test_round_trips(self):
        payload = JoinRoomPayload(room_id="r1")
        assert JoinRoomPayload.model_validate(payload.model_dump()).room_id == "r1"

    def test_missing_room_id_raises(self):
        with pytest.raises(ValidationError):
            JoinRoomPayload.model_validate({})


class TestRoomWaitingPayload:
    def test_round_trips(self):
        payload = RoomWaitingPayload(room_id="r1", status="waiting")
        restored = RoomWaitingPayload.model_validate(payload.model_dump())
        assert restored == payload


class TestJumpPayload:
    def test_round_trips_through_position(self):
        payload = JumpPayload.model_validate({"pos": {"x": 2, "y": 5}})
        assert payload.pos.to_position() == Position(2, 5)

    def test_malformed_position_raises(self):
        with pytest.raises(ValidationError):
            JumpPayload.model_validate({"pos": {"x": 2}})


class TestGameStartPayload:
    def test_player_round_trips(self):
        payload = GameStartPayload(
            game_id="g1",
            role="player",
            color="w",
            white_username="alice",
            black_username="bob",
        )
        restored = GameStartPayload.model_validate(payload.model_dump())
        assert restored == payload

    def test_observer_color_none_validates(self):
        payload = GameStartPayload.model_validate(
            {
                "game_id": "g1",
                "role": "observer",
                "color": None,
                "white_username": "alice",
                "black_username": "bob",
            }
        )
        assert payload.color is None


class TestRatingChangePayload:
    def test_round_trips(self):
        payload = RatingChangePayload(username="alice", old_rating=1200, new_rating=1216)
        restored = RatingChangePayload.model_validate(payload.model_dump())
        assert restored == payload


class TestGameOverPayload:
    def test_round_trips_with_rating_changes(self):
        payload = GameOverPayload(
            winner="w",
            reason="king_captured",
            rating_changes=[
                RatingChangePayload(username="alice", old_rating=1200, new_rating=1216),
                RatingChangePayload(username="bob", old_rating=1200, new_rating=1184),
            ],
        )
        restored = GameOverPayload.model_validate_json(payload.model_dump_json())
        assert restored == payload
        assert len(restored.rating_changes) == 2

    def test_empty_rating_changes_default(self):
        payload = GameOverPayload(winner="w", reason="king_captured")
        assert payload.rating_changes == []
