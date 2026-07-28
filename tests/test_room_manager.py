from dataclasses import dataclass

import pytest

from model.piece import Color
from server.rooms import (
    LeaveResult,
    RoomManager,
    SeekResult,
    UnknownRoomError,
)
from server.server_config import (
    MATCH_ELO_RANGE,
    ROOM_ID_ALPHABET,
    ROOM_ID_LENGTH,
)
from shared.protocol_config import Role


@dataclass
class FakeSession:
    """RoomManager only reads ``player_id`` off a session."""

    player_id: str


@pytest.fixture
def manager() -> RoomManager:
    return RoomManager()


class TestCreateRoom:
    def test_creator_is_white_player_not_started(self, manager):
        result = manager.create_room(FakeSession("alice"))
        assert result.role == Role.PLAYER
        assert result.color == Color.WHITE
        assert result.should_start_game is False
        assert result.room.players[0].player_id == "alice"

    def test_room_id_is_short_and_typeable(self, manager):
        result = manager.create_room(FakeSession("alice"))
        room_id = result.room.name
        assert len(room_id) == ROOM_ID_LENGTH
        assert all(ch in ROOM_ID_ALPHABET for ch in room_id)

    def test_room_ids_are_unique(self, manager):
        ids = {manager.create_room(FakeSession(f"p{i}")).room.name for i in range(20)}
        assert len(ids) == 20


class TestJoin:
    def test_second_player_is_black_and_starts_game(self, manager):
        created = manager.create_room(FakeSession("alice"))
        result = manager.join(created.room.name, FakeSession("bob"))
        assert result.role == Role.PLAYER
        assert result.color == Color.BLACK
        assert result.should_start_game is True
        assert [s.player_id for s in result.room.players] == ["alice", "bob"]

    def test_third_joiner_is_observer(self, manager):
        created = manager.create_room(FakeSession("alice"))
        manager.join(created.room.name, FakeSession("bob"))
        result = manager.join(created.room.name, FakeSession("carol"))
        assert result.role == Role.OBSERVER
        assert result.color is None
        assert result.should_start_game is False
        assert [s.player_id for s in result.room.observers] == ["carol"]

    def test_join_unknown_room_raises(self, manager):
        with pytest.raises(UnknownRoomError):
            manager.join("ZZZZZZ", FakeSession("bob"))

    def test_room_exists(self, manager):
        created = manager.create_room(FakeSession("alice"))
        assert manager.room_exists(created.room.name)
        assert not manager.room_exists("ZZZZZZ")

    def test_join_after_game_started_is_observer(self, manager):
        created = manager.create_room(FakeSession("alice"))
        manager.join(created.room.name, FakeSession("bob"))
        created.room.game_id = "game-1"
        result = manager.join(created.room.name, FakeSession("dave"))
        assert result.role == Role.OBSERVER


class TestSeek:
    def test_first_seeker_waits(self, manager):
        result = manager.seek(FakeSession("alice"), rating=1200)
        assert result == SeekResult(matched=False, room=None)

    def test_second_seeker_in_range_matches(self, manager):
        manager.seek(FakeSession("alice"), rating=1200)
        result = manager.seek(FakeSession("bob"), rating=1200 + MATCH_ELO_RANGE)
        assert result.matched is True
        # waited first -> White (seat 0); caller -> Black (seat 1)
        assert [s.player_id for s in result.room.players] == ["alice", "bob"]

    def test_seeker_out_of_range_does_not_match(self, manager):
        manager.seek(FakeSession("alice"), rating=1200)
        result = manager.seek(FakeSession("bob"), rating=1200 + MATCH_ELO_RANGE + 1)
        assert result.matched is False

    def test_matches_closest_rating_in_range(self, manager):
        # 1140 and 1250 are >100 apart so they don't pair with each other, but
        # both sit within 100 of the 1200 caller; the closer one (1250) wins.
        manager.seek(FakeSession("low"), rating=1140)
        manager.seek(FakeSession("high"), rating=1250)
        result = manager.seek(FakeSession("caller"), rating=1200)
        assert result.matched is True
        assert result.room.players[0].player_id == "high"

    def test_cancel_seek_removes_from_pool(self, manager):
        alice = FakeSession("alice")
        manager.seek(alice, rating=1200)
        assert manager.cancel_seek(alice) is True
        # nobody left to match against
        result = manager.seek(FakeSession("bob"), rating=1200)
        assert result.matched is False

    def test_cancel_unknown_seeker_returns_false(self, manager):
        assert manager.cancel_seek(FakeSession("ghost")) is False


class TestLeave:
    def test_player_leaving_reports_remaining(self, manager):
        created = manager.create_room(FakeSession("alice"))
        bob = FakeSession("bob")
        manager.join(created.room.name, bob)
        alice = created.room.players[0]

        result = manager.leave(alice)
        assert result.room_closed is False
        assert [s.player_id for s in result.room.players] == ["bob"]

    def test_last_leaver_closes_room(self, manager):
        created = manager.create_room(FakeSession("alice"))
        alice = created.room.players[0]
        result = manager.leave(alice)
        assert result.room_closed is True
        assert manager.room_of("alice") is None

    def test_observer_leaving_reports_remaining(self, manager):
        created = manager.create_room(FakeSession("alice"))
        manager.join(created.room.name, FakeSession("bob"))
        carol = FakeSession("carol")
        manager.join(created.room.name, carol)

        result = manager.leave(carol)
        assert result.room_closed is False
        assert [s.player_id for s in result.room.players] == ["alice", "bob"]

    def test_leaving_a_seeker_cancels_the_seek(self, manager):
        alice = FakeSession("alice")
        manager.seek(alice, rating=1200)
        manager.leave(alice)
        result = manager.seek(FakeSession("bob"), rating=1200)
        assert result.matched is False

    def test_leave_unknown_session_is_noop(self, manager):
        result = manager.leave(FakeSession("ghost"))
        assert result == LeaveResult(room=None, room_closed=False)


class TestRoomOf:
    def test_returns_room_for_joined_player(self, manager):
        created = manager.create_room(FakeSession("alice"))
        assert manager.room_of("alice") is created.room

    def test_returns_none_for_unknown(self, manager):
        assert manager.room_of("ghost") is None
