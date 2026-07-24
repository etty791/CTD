import dataclasses
import json

from rules.rules_engine import MoveValidation
from game_engine.payloads import MoveValidationPayload


class TestMoveValidationPayload:
    def test_field_set(self):
        payload = MoveValidationPayload.from_move_validation(MoveValidation(False, "illegal_piece_move"))
        assert dataclasses.asdict(payload) == {"is_valid": False, "reason": "illegal_piece_move"}

    def test_json_round_trip(self):
        payload = MoveValidationPayload.from_move_validation(MoveValidation(True, "ok"))
        decoded = json.loads(json.dumps(dataclasses.asdict(payload)))
        assert decoded == {"is_valid": True, "reason": "ok"}
