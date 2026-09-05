import pytest

from server.elo import (
    DEFAULT_RATING,
    K_FACTOR,
    RatingUpdate,
    expected_score,
    update_ratings,
)


class TestExpectedScore:
    def test_symmetry_sums_to_one(self):
        a, b = 1400, 1200
        assert expected_score(a, b) + expected_score(b, a) == pytest.approx(1.0)

    def test_equal_ratings_is_half(self):
        assert expected_score(DEFAULT_RATING, DEFAULT_RATING) == pytest.approx(0.5)

    def test_higher_rating_favored(self):
        assert expected_score(1600, 1200) > 0.5
        assert expected_score(1200, 1600) < 0.5


class TestUpdateRatings:
    def test_equal_ratings_swing_is_16(self):
        result = update_ratings(DEFAULT_RATING, DEFAULT_RATING, k=K_FACTOR)
        assert result.new_winner_rating == DEFAULT_RATING + 16
        assert result.new_loser_rating == DEFAULT_RATING - 16

    def test_favorite_winning_gains_fewer_than_16(self):
        result = update_ratings(1800, 1200)
        gain = result.new_winner_rating - 1800
        assert 0 < gain < 16

    def test_underdog_winning_gains_more_than_16(self):
        result = update_ratings(1200, 1800)
        gain = result.new_winner_rating - 1200
        assert gain > 16

    def test_ratings_are_ints(self):
        result = update_ratings(1213, 1187)
        assert isinstance(result.new_winner_rating, int)
        assert isinstance(result.new_loser_rating, int)

    def test_returns_rating_update(self):
        assert isinstance(update_ratings(1200, 1200), RatingUpdate)

    def test_zero_sum_at_equal_ratings(self):
        # symmetric swing: winner's gain mirrors loser's loss
        result = update_ratings(DEFAULT_RATING, DEFAULT_RATING)
        winner_gain = result.new_winner_rating - DEFAULT_RATING
        loser_loss = DEFAULT_RATING - result.new_loser_rating
        assert winner_gain == loser_loss


class TestPurity:
    def test_same_args_same_result(self):
        first = update_ratings(1350, 1290)
        second = update_ratings(1350, 1290)
        assert first == second
