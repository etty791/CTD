"""Pure Elo rating math. No I/O, no persistence, no game knowledge."""

from dataclasses import dataclass

K_FACTOR = 32
ELO_SCALE = 400
ELO_BASE = 10
WIN_SCORE = 1.0
LOSS_SCORE = 0.0
DEFAULT_RATING = 1200


@dataclass(frozen=True)
class RatingUpdate:
    new_winner_rating: int
    new_loser_rating: int


def expected_score(rating_a: int, rating_b: int) -> float:
    """Probability that player A beats player B given their ratings."""
    return 1 / (1 + ELO_BASE ** ((rating_b - rating_a) / ELO_SCALE))


def update_ratings(
    winner_rating: int, loser_rating: int, k: int = K_FACTOR
) -> RatingUpdate:
    """Apply the standard Elo update after a decisive game (winner scores 1)."""
    winner_delta = round(k * (WIN_SCORE - expected_score(winner_rating, loser_rating)))
    loser_delta = round(k * (LOSS_SCORE - expected_score(loser_rating, winner_rating)))
    return RatingUpdate(
        new_winner_rating=winner_rating + winner_delta,
        new_loser_rating=loser_rating + loser_delta,
    )
