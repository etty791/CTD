import pytest
from pydantic import ValidationError

from model.piece import Color, PieceType, State
from model.position import Position
from model.game_snapshot import PieceDTO
from server.messages import AuthPayload, MovePayload, PiecePayload, PositionPayload, StatePayload


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
