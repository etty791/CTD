from events.game_events import (
    MoveAborted,
    MoveCompleted,
    MoveStarted,
    MoveTruncated,
    PieceCaptured,
    RestEnded,
)
from model.game_snapshot import PieceDTO
from model.piece import Color, PieceType, State
from model.position import Position
from server.encoding import event_payload_from, state_payload_from_snapshot


MOVE_START_MS = 1000
MOVE_ARRIVAL_MS = 4000
SNAPSHOT_CLOCK_MS = 2500


MOVE_START_MS = 1000
MOVE_ARRIVAL_MS = 4000
SNAPSHOT_CLOCK_MS = 2500


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


class FakeSnapshot:
    """Duck-types the GameSnapshot surface the encoder needs."""

    def __init__(self, pieces, scores, clock_ms=SNAPSHOT_CLOCK_MS):
        self._pieces = pieces
        self._scores = scores
        self._clock_ms = clock_ms

    def get_all_pieces(self):
        return self._pieces

    def get_scores(self):
        return self._scores

    def get_clock_ms(self):
        return self._clock_ms


class TestStatePayloadFromSnapshot:
    def test_mirrors_snapshot(self):
        snapshot = FakeSnapshot(pieces=[sample_piece_dto()], scores={Color.WHITE: 1, Color.BLACK: 0})

        payload = state_payload_from_snapshot(snapshot)

        assert payload.scores == {"w": 1, "b": 0}
        assert len(payload.pieces) == 1
        assert payload.pieces[0].id == 1

    def test_carries_move_times_and_the_clock_they_are_measured_against(self):
        snapshot = FakeSnapshot(
            pieces=[sample_piece_dto()], scores={Color.WHITE: 0, Color.BLACK: 0}
        )

        payload = state_payload_from_snapshot(snapshot)

        assert payload.server_time_ms == SNAPSHOT_CLOCK_MS
        assert payload.pieces[0].move_start_ms == MOVE_START_MS
        assert payload.pieces[0].move_arrival_ms == MOVE_ARRIVAL_MS

    def test_resting_piece_has_no_move_times(self):
        resting = sample_piece_dto()
        resting.move_start_ms = None
        resting.move_arrival_ms = None
        snapshot = FakeSnapshot(pieces=[resting], scores={Color.WHITE: 0, Color.BLACK: 0})

        payload = state_payload_from_snapshot(snapshot)

        assert payload.pieces[0].move_start_ms is None
        assert payload.pieces[0].move_arrival_ms is None

    def test_dumps_to_json_serialisable_shape(self):
        snapshot = FakeSnapshot(pieces=[sample_piece_dto()], scores={Color.WHITE: 0, Color.BLACK: 0})

        dumped = state_payload_from_snapshot(snapshot).model_dump()

        assert set(dumped.keys()) == {"pieces", "scores", "server_time_ms"}
        assert dumped["pieces"][0]["position"] == {"x": 0, "y": 0}

    def test_empty_snapshot_encodes_to_empty_pieces(self):
        payload = state_payload_from_snapshot(
            FakeSnapshot(pieces=[], scores={Color.WHITE: 0, Color.BLACK: 0})
        )

        assert payload.pieces == []


class TestEventPayloadFrom:
    def test_move_started(self):
        payload = event_payload_from(
            MoveStarted(move_id=1, piece_id=7, src=Position(6, 0), dst=Position(5, 0))
        )
        assert payload.event_type == "MoveStarted"
        assert payload.data == {
            "move_id": 1, "piece_id": 7,
            "src": {"x": 6, "y": 0}, "dst": {"x": 5, "y": 0},
        }

    def test_move_completed(self):
        payload = event_payload_from(
            MoveCompleted(
                move_id=1, piece_id=7, piece_type=PieceType.ROOK, color=Color.WHITE,
                src=Position(6, 0), dst=Position(5, 0),
            )
        )
        assert payload.event_type == "MoveCompleted"
        assert payload.data["piece_type"] == "R"
        assert payload.data["color"] == "w"

    def test_move_truncated(self):
        payload = event_payload_from(
            MoveTruncated(move_id=1, piece_id=7, target=Position(4, 0), arrival_time_ms=1500)
        )
        assert payload.event_type == "MoveTruncated"
        assert payload.data == {
            "move_id": 1, "piece_id": 7,
            "target": {"x": 4, "y": 0}, "arrival_time_ms": 1500,
        }

    def test_move_aborted(self):
        payload = event_payload_from(MoveAborted(move_id=1, piece_id=7, position=Position(6, 0)))
        assert payload.event_type == "MoveAborted"
        assert payload.data == {"move_id": 1, "piece_id": 7, "position": {"x": 6, "y": 0}}

    def test_piece_captured(self):
        payload = event_payload_from(
            PieceCaptured(
                piece_id=3, piece_type=PieceType.PAWN, color=Color.BLACK,
                position=Position(4, 0), capturing_move_id=2,
            )
        )
        assert payload.event_type == "PieceCaptured"
        assert payload.data == {
            "piece_id": 3, "piece_type": "P", "color": "b",
            "position": {"x": 4, "y": 0}, "capturing_move_id": 2,
        }

    def test_rest_ended(self):
        payload = event_payload_from(RestEnded(piece_id=3, position=Position(4, 0)))
        assert payload.event_type == "RestEnded"
        assert payload.data == {"piece_id": 3, "position": {"x": 4, "y": 0}}
