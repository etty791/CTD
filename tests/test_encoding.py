from model.game_snapshot import PieceDTO
from model.piece import Color, PieceType, State
from model.position import Position
from server.encoding import state_payload_from_snapshot


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
    """Duck-types the GameSnapshot surface the encoder needs."""

    def __init__(self, pieces, scores):
        self._pieces = pieces
        self._scores = scores

    def get_all_pieces(self):
        return self._pieces

    def get_scores(self):
        return self._scores


class TestStatePayloadFromSnapshot:
    def test_mirrors_snapshot(self):
        snapshot = FakeSnapshot(pieces=[sample_piece_dto()], scores={Color.WHITE: 1, Color.BLACK: 0})

        payload = state_payload_from_snapshot(snapshot)

        assert payload.scores == {"w": 1, "b": 0}
        assert len(payload.pieces) == 1
        assert payload.pieces[0].id == 1

    def test_dumps_to_json_serialisable_shape(self):
        snapshot = FakeSnapshot(pieces=[sample_piece_dto()], scores={Color.WHITE: 0, Color.BLACK: 0})

        dumped = state_payload_from_snapshot(snapshot).model_dump()

        assert set(dumped.keys()) == {"pieces", "scores"}
        assert dumped["pieces"][0]["position"] == {"x": 0, "y": 0}

    def test_empty_snapshot_encodes_to_empty_pieces(self):
        payload = state_payload_from_snapshot(
            FakeSnapshot(pieces=[], scores={Color.WHITE: 0, Color.BLACK: 0})
        )

        assert payload.pieces == []
