import pytest
from backend.app.ranking.rating import (
    compute_bayesian_rating,
    compute_review_confidence_score,
    compute_wilson_lower_bound,
)


class TestBayesianRating:
    def test_low_reviews_does_not_outrank_high_reviews(self):
        """
        CRITICAL REQUIREMENT:
        5.0★ with 10 reviews must NOT outrank 4.7★ with 300 reviews.
        """
        # Baseline prior C = 4.0, confidence threshold m = 50
        score_5_star_10_reviews = compute_bayesian_rating(
            rating=5.0,
            review_count=10,
            baseline_rating=4.0,
            confidence_threshold=50,
        )

        score_4_7_star_300_reviews = compute_bayesian_rating(
            rating=4.7,
            review_count=300,
            baseline_rating=4.0,
            confidence_threshold=50,
        )

        # 5.0 * (10/60) + 4.0 * (50/60) = 4.167
        # 4.7 * (300/350) + 4.0 * (50/350) = 4.600
        assert score_5_star_10_reviews < score_4_7_star_300_reviews
        assert score_5_star_10_reviews == pytest.approx(4.167, rel=1e-2)
        assert score_4_7_star_300_reviews == pytest.approx(4.600, rel=1e-2)

    def test_mediocre_rating_with_massive_reviews_does_not_beat_superior_product(self):
        """
        CRITICAL REQUIREMENT:
        3.8★ with 20,000 reviews must NOT automatically beat 4.7★ with 1,000 reviews.
        Review count provides confidence, not the entire score.
        """
        score_3_8_star_20k_reviews = compute_bayesian_rating(
            rating=3.8,
            review_count=20000,
            baseline_rating=4.0,
            confidence_threshold=50,
        )

        score_4_7_star_1k_reviews = compute_bayesian_rating(
            rating=4.7,
            review_count=1000,
            baseline_rating=4.0,
            confidence_threshold=50,
        )

        # 3.8 stays near 3.800
        # 4.7 stays near 4.667
        assert score_4_7_star_1k_reviews > score_3_8_star_20k_reviews
        assert score_3_8_star_20k_reviews == pytest.approx(3.800, rel=1e-2)
        assert score_4_7_star_1k_reviews == pytest.approx(4.667, rel=1e-2)

    def test_zero_reviews_regresses_to_baseline(self):
        score_zero_reviews = compute_bayesian_rating(
            rating=5.0,
            review_count=0,
            baseline_rating=4.0,
            confidence_threshold=50,
        )
        assert score_zero_reviews == 4.0

    def test_review_confidence_saturation(self):
        # 0 reviews -> 0% confidence
        assert compute_review_confidence_score(0, half_confidence_reviews=100) == 0.0
        # 10 reviews -> low confidence (~9.1%)
        conf_10 = compute_review_confidence_score(10, half_confidence_reviews=100)
        assert 5.0 <= conf_10 <= 15.0
        # 100 reviews -> half saturation (50%)
        conf_100 = compute_review_confidence_score(100, half_confidence_reviews=100)
        assert conf_100 == 50.0
        # 300 reviews -> ~75% confidence
        conf_300 = compute_review_confidence_score(300, half_confidence_reviews=100)
        assert conf_300 == 75.0
        # 10,000 reviews -> near 99% confidence
        conf_10k = compute_review_confidence_score(10000, half_confidence_reviews=100)
        assert conf_10k >= 99.0

    def test_wilson_lower_bound(self):
        # 10 out of 10 positive reviews
        score_10 = compute_wilson_lower_bound(10, 10)
        # 290 out of 300 positive reviews
        score_300 = compute_wilson_lower_bound(290, 300)
        assert score_300 > score_10
