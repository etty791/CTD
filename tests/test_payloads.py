import dataclasses
import json

from model.piece import Color, PieceType, State
from model.position import Position
from model.game_snapshot import PieceDTO
from rules.rules_engine import MoveValidation
from game_engine.payloads import (
    GameStatePayload,
    MoveValidationPayload,
    PiecePayload,
    PositionPayload,
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


class TestPositionPayload:
    def test_field_set(self):
        payload = PositionPayload.from_position(Position(2, 5))
        assert dataclasses.asdict(payload) == {"x": 2, "y": 5}

    def test_json_round_trip(self):
        payload = PositionPayload.from_position(Position(2, 5))
        decoded = json.loads(json.dumps(dataclasses.asdict(payload)))
        assert decoded == {"x": 2, "y": 5}


class TestPiecePayload:
    def test_field_set(self):
        payload = PiecePayload.from_piece_dto(sample_piece_dto())
        assert set(dataclasses.asdict(payload).keys()) == {
            "id", "position", "type", "color", "state", "origin", "target", "progress",
        }

    def test_enums_become_their_string_values(self):
        payload = PiecePayload.from_piece_dto(sample_piece_dto())
        assert payload.type == "R"
        assert payload.color == "w"
        assert payload.state == "moving"

    def test_json_round_trip(self):
        payload = PiecePayload.from_piece_dto(sample_piece_dto())
        decoded = json.loads(json.dumps(dataclasses.asdict(payload)))
        assert decoded == {
            "id": 1,
            "position": {"x": 0, "y": 0},
            "type": "R",
            "color": "w",
            "state": "moving",
            "origin": {"x": 0, "y": 0},
            "target": {"x": 0, "y": 3},
            "progress": 0.5,
        }


class TestMoveValidationPayload:
    def test_field_set(self):
        payload = MoveValidationPayload.from_move_validation(MoveValidation(False, "illegal_piece_move"))
        assert dataclasses.asdict(payload) == {"is_valid": False, "reason": "illegal_piece_move"}

    def test_json_round_trip(self):
        payload = MoveValidationPayload.from_move_validation(MoveValidation(True, "ok"))
        decoded = json.loads(json.dumps(dataclasses.asdict(payload)))
        assert decoded == {"is_valid": True, "reason": "ok"}


class TestGameStatePayload:
    def test_field_set(self):
        payload = GameStatePayload(pieces=[PiecePayload.from_piece_dto(sample_piece_dto())], scores={"w": 0, "b": 0})
        assert set(dataclasses.asdict(payload).keys()) == {"pieces", "scores"}

    def test_json_round_trip(self):
        payload = GameStatePayload(pieces=[PiecePayload.from_piece_dto(sample_piece_dto())], scores={"w": 1, "b": 0})
        decoded = json.loads(json.dumps(dataclasses.asdict(payload)))
        assert decoded["scores"] == {"w": 1, "b": 0}
        assert decoded["pieces"][0]["id"] == 1
