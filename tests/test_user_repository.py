import pytest

from model.piece import Color
from server.elo import DEFAULT_RATING, update_ratings
from server.persistence.db import Database
from server.persistence.persistence_config import AuthReason
from server.persistence.user_repository import (
    AuthResult,
    CreateUserResult,
    GameResultRatings,
    UnknownPlayerError,
    UserRepository,
)


@pytest.fixture
def repo(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init_schema()
    yield UserRepository(db)
    db.close()


class TestCreateUser:
    def test_create_ok(self, repo):
        result = repo.create_user("alice", "pw")
        assert result == CreateUserResult(ok=True, reason=AuthReason.OK)

    def test_new_user_gets_default_rating(self, repo):
        repo.create_user("alice", "pw")
        assert repo.get_rating("alice") == DEFAULT_RATING

    def test_duplicate_username_rejected(self, repo):
        repo.create_user("alice", "pw")
        result = repo.create_user("alice", "other")
        assert not result.ok
        assert result.reason == AuthReason.USERNAME_TAKEN


class TestAuthenticate:
    def test_authenticate_ok(self, repo):
        repo.create_user("alice", "pw")
        result = repo.authenticate("alice", "pw")
        assert result.ok
        assert result.reason == AuthReason.OK
        assert result.rating == DEFAULT_RATING

    def test_no_such_user(self, repo):
        result = repo.authenticate("ghost", "pw")
        assert result == AuthResult(
            ok=False, reason=AuthReason.NO_SUCH_USER, rating=None
        )

    def test_bad_password(self, repo):
        repo.create_user("alice", "pw")
        result = repo.authenticate("alice", "nope")
        assert not result.ok
        assert result.reason == AuthReason.BAD_PASSWORD
        assert result.rating is None


class TestGetRating:
    def test_missing_user_returns_none(self, repo):
        assert repo.get_rating("ghost") is None


class TestApplyGameResult:
    def test_white_win_updates_both_ratings(self, repo):
        repo.create_user("white", "pw")
        repo.create_user("black", "pw")
        expected = update_ratings(DEFAULT_RATING, DEFAULT_RATING)

        result = repo.apply_game_result("white", "black", Color.WHITE)

        assert isinstance(result, GameResultRatings)
        assert result.white_new == expected.new_winner_rating
        assert result.black_new == expected.new_loser_rating
        assert repo.get_rating("white") == expected.new_winner_rating
        assert repo.get_rating("black") == expected.new_loser_rating

    def test_black_win_updates_both_ratings(self, repo):
        repo.create_user("white", "pw")
        repo.create_user("black", "pw")
        expected = update_ratings(DEFAULT_RATING, DEFAULT_RATING)

        repo.apply_game_result("white", "black", Color.BLACK)

        assert repo.get_rating("black") == expected.new_winner_rating
        assert repo.get_rating("white") == expected.new_loser_rating

    def test_unknown_player_raises(self, repo):
        repo.create_user("white", "pw")
        with pytest.raises(UnknownPlayerError):
            repo.apply_game_result("white", "ghost", Color.WHITE)
