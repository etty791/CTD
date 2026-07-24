import pytest
from pydantic import ValidationError

from model.piece import Color, PieceType, State
from model.position import Position
from model.game_snapshot import PieceDTO
from server.messages import (
    AuthAckPayload,
    AuthPayload,
    CredentialsPayload,
    GameOverPayload,
    GameStartPayload,
    JoinRoomPayload,
    JumpPayload,
    MovePayload,
    PiecePayload,
    PositionPayload,
    RatingChangePayload,
    StatePayload,
)


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
    )


class FakeSnapshot:
    """Duck-types the GameSnapshot surface StatePayload.from_snapshot needs."""

    def __init__(self, pieces, scores):
        self._pieces = pieces
        self._scores = scores

    def get_all_pieces(self):
        return self._pieces

    def get_scores(self):
        return self._scores


class TestAuthPayload:
    def test_valid_payload_parses(self):
        payload = AuthPayload.model_validate({"player_id": "p1"})
        assert payload.player_id == "p1"

    def test_missing_player_id_raises_validation_error(self):
        with pytest.raises(ValidationError):
            AuthPayload.model_validate({})


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
            "progress": 0.5,
        }


class TestStatePayload:
    def test_from_snapshot_mirrors_snapshot(self):
        snapshot = FakeSnapshot(pieces=[sample_piece_dto()], scores={Color.WHITE: 1, Color.BLACK: 0})

        payload = StatePayload.from_snapshot(snapshot)

        assert payload.scores == {"w": 1, "b": 0}
        assert len(payload.pieces) == 1
        assert payload.pieces[0].id == 1

    def test_model_dump_is_json_serialisable_shape(self):
        snapshot = FakeSnapshot(pieces=[sample_piece_dto()], scores={Color.WHITE: 0, Color.BLACK: 0})
        payload = StatePayload.from_snapshot(snapshot)
        dumped = payload.model_dump()
        assert set(dumped.keys()) == {"pieces", "scores"}
        assert dumped["pieces"][0]["position"] == {"x": 0, "y": 0}


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
        payload = JoinRoomPayload(room_name="r1")
        assert JoinRoomPayload.model_validate(payload.model_dump()).room_name == "r1"

    def test_missing_room_name_raises(self):
        with pytest.raises(ValidationError):
            JoinRoomPayload.model_validate({})


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
