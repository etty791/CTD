import pytest

from model.piece import Color
from server.elo import DEFAULT_RATING, update_ratings
from server.persistence.user_repository import (
    AuthResult,
    CreateUserResult,
    GameResultRatings,
)
from server.persistence.worker import PersistenceNotStartedError, PersistenceWorker


@pytest.fixture
def worker(tmp_path):
    w = PersistenceWorker()
    w.start(str(tmp_path / "w.db"))
    yield w
    w.stop()


class TestPersistenceWorker:
    def test_schema_ready_immediately_after_start(self, worker):
        # A query against the (empty) schema must succeed, returning None, not error.
        result = worker.submit(lambda repo: repo.get_rating("nobody")).result()
        assert result is None

    def test_create_and_authenticate(self, worker):
        created = worker.submit(lambda repo: repo.create_user("alice", "pw")).result()
        assert created == CreateUserResult(ok=True, reason=created.reason)
        assert created.ok

        auth = worker.submit(lambda repo: repo.authenticate("alice", "pw")).result()
        assert isinstance(auth, AuthResult)
        assert auth.ok
        assert auth.rating == DEFAULT_RATING

    def test_apply_game_result_updates_both(self, worker):
        worker.submit(lambda repo: repo.create_user("white", "pw")).result()
        worker.submit(lambda repo: repo.create_user("black", "pw")).result()
        expected = update_ratings(DEFAULT_RATING, DEFAULT_RATING)

        result = worker.submit(
            lambda repo: repo.apply_game_result("white", "black", Color.WHITE)
        ).result()

        assert isinstance(result, GameResultRatings)
        assert result.white_new == expected.new_winner_rating
        assert result.black_new == expected.new_loser_rating
        # ratings persisted
        white_rating = worker.submit(lambda repo: repo.get_rating("white")).result()
        black_rating = worker.submit(lambda repo: repo.get_rating("black")).result()
        assert white_rating == expected.new_winner_rating
        assert black_rating == expected.new_loser_rating

    def test_submit_before_start_raises(self):
        w = PersistenceWorker()
        try:
            with pytest.raises(PersistenceNotStartedError):
                w.submit(lambda repo: repo.get_rating("x")).result()
        finally:
            w.stop()

    def test_start_creates_missing_parent_directory(self, tmp_path):
        w = PersistenceWorker()
        nested = tmp_path / "sub" / "deeper" / "w.db"
        w.start(str(nested))
        try:
            assert nested.parent.is_dir()
            assert worker_get_rating_missing(w) is None
        finally:
            w.stop()


def worker_get_rating_missing(w: PersistenceWorker):
    return w.submit(lambda repo: repo.get_rating("nobody")).result()
