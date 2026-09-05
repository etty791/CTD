from dataclasses import dataclass

import pytest

from model.piece import Color
from server.rooms import (
    InvalidRoomTransitionError,
    LeaveResult,
    RoomManager,
    SeekResult,
    UnknownRoomError,
)
from server.server_config import (
    MATCH_ELO_RANGE_INITIAL,
    MATCH_ELO_RANGE_MAX,
    MATCH_ELO_WIDEN_INTERVAL_MS,
    ROOM_ID_ALPHABET,
    ROOM_ID_LENGTH,
)
from shared.protocol_config import Role, RoomStatus


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
        manager.mark_live(created.room, "game-1")
        result = manager.join(created.room.name, FakeSession("dave"))
        assert result.role == Role.OBSERVER

    def test_repeat_join_by_seated_player_returns_same_seat(self, manager):
        created = manager.create_room(FakeSession("alice"))
        alice = created.room.players[0]
        result = manager.join(created.room.name, alice)
        assert result.role == Role.PLAYER
        assert result.color == Color.WHITE
        assert result.should_start_game is False
        # not re-seated
        assert [s.player_id for s in created.room.players] == ["alice"]

    def test_repeat_join_by_observer_stays_observer_even_if_seat_frees_up(self, manager):
        created = manager.create_room(FakeSession("alice"))
        manager.join(created.room.name, FakeSession("bob"))
        carol = FakeSession("carol")
        manager.join(created.room.name, carol)  # observer: room full

        bob = created.room.players[1]
        manager.leave(bob)  # a seat frees up

        result = manager.join(created.room.name, carol)
        assert result.role == Role.OBSERVER
        assert result.color is None


class TestRoomStatusFSM:
    def test_new_room_is_waiting(self, manager):
        created = manager.create_room(FakeSession("alice"))
        assert created.room.status == RoomStatus.WAITING

    def test_mark_live_sets_status_and_game_id(self, manager):
        created = manager.create_room(FakeSession("alice"))
        manager.mark_live(created.room, "game-1")
        assert created.room.status == RoomStatus.LIVE
        assert created.room.game_id == "game-1"

    def test_mark_live_twice_raises(self, manager):
        created = manager.create_room(FakeSession("alice"))
        manager.mark_live(created.room, "game-1")
        with pytest.raises(InvalidRoomTransitionError):
            manager.mark_live(created.room, "game-2")

    def test_mark_ended_before_live_raises(self, manager):
        created = manager.create_room(FakeSession("alice"))
        with pytest.raises(InvalidRoomTransitionError):
            manager.mark_ended(created.room)

    def test_mark_ended_after_live_succeeds(self, manager):
        created = manager.create_room(FakeSession("alice"))
        manager.mark_live(created.room, "game-1")
        manager.mark_ended(created.room)
        assert created.room.status == RoomStatus.ENDED


class TestSeek:
    def test_first_seeker_waits(self, manager):
        result = manager.seek(FakeSession("alice"), rating=1200, now_ms=0)
        assert result == SeekResult(matched=False, room=None)

    def test_second_seeker_in_range_matches(self, manager):
        manager.seek(FakeSession("alice"), rating=1200, now_ms=0)
        result = manager.seek(
            FakeSession("bob"), rating=1200 + MATCH_ELO_RANGE_INITIAL, now_ms=0
        )
        assert result.matched is True
        # waited first -> White (seat 0); caller -> Black (seat 1)
        assert [s.player_id for s in result.room.players] == ["alice", "bob"]

    def test_seeker_out_of_range_does_not_match(self, manager):
        manager.seek(FakeSession("alice"), rating=1200, now_ms=0)
        result = manager.seek(
            FakeSession("bob"), rating=1200 + MATCH_ELO_RANGE_INITIAL + 1, now_ms=0
        )
        assert result.matched is False

    def test_matches_closest_rating_in_range(self, manager):
        # 1140 and 1250 are >100 apart so they don't pair with each other, but
        # both sit within 100 of the 1200 caller; the closer one (1250) wins.
        manager.seek(FakeSession("low"), rating=1140, now_ms=0)
        manager.seek(FakeSession("high"), rating=1250, now_ms=0)
        result = manager.seek(FakeSession("caller"), rating=1200, now_ms=0)
        assert result.matched is True
        assert result.room.players[0].player_id == "high"

    def test_cancel_seek_removes_from_pool(self, manager):
        alice = FakeSession("alice")
        manager.seek(alice, rating=1200, now_ms=0)
        assert manager.cancel_seek(alice) is True
        # nobody left to match against
        result = manager.seek(FakeSession("bob"), rating=1200, now_ms=0)
        assert result.matched is False

    def test_cancel_unknown_seeker_returns_false(self, manager):
        assert manager.cancel_seek(FakeSession("ghost")) is False

    def test_wider_gap_does_not_match_immediately(self, manager):
        manager.seek(FakeSession("alice"), rating=1200, now_ms=0)
        result = manager.seek(FakeSession("bob"), rating=1500, now_ms=0)
        assert result.matched is False

    def test_widens_after_waiting_and_matches(self, manager):
        manager.seek(FakeSession("alice"), rating=1200, now_ms=0)
        later = MATCH_ELO_WIDEN_INTERVAL_MS * 3  # band: 100 + 50*3 = 250
        result = manager.seek(FakeSession("bob"), rating=1200 + 250, now_ms=later)
        assert result.matched is True

    def test_widening_is_capped(self, manager):
        manager.seek(FakeSession("alice"), rating=1200, now_ms=0)
        much_later = MATCH_ELO_WIDEN_INTERVAL_MS * 100  # would overshoot the cap
        result = manager.seek(
            FakeSession("bob"), rating=1200 + MATCH_ELO_RANGE_MAX + 1, now_ms=much_later
        )
        assert result.matched is False

    def test_two_arrivals_together_never_recheck_each_other(self, manager):
        # Both queue at the same instant, outside each other's initial band.
        # Widening is only evaluated when a *new* seeker arrives, so these
        # two never get a second look at each other.
        manager.seek(FakeSession("alice"), rating=1200, now_ms=0)
        result = manager.seek(FakeSession("bob"), rating=1500, now_ms=0)
        assert result.matched is False


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
        manager.seek(alice, rating=1200, now_ms=0)
        manager.leave(alice)
        result = manager.seek(FakeSession("bob"), rating=1200, now_ms=0)
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
