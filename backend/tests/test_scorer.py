import pytest
from backend.app.ranking.scorer import (
    calculate_product_scores,
    compute_price_value_score,
)


class TestScorer:
    def test_price_value_score_rewards_discounts_and_budget_headroom(self):
        # Product with 30% discount at 85% of budget cap
        score_good_value = compute_price_value_score(
            price=17000.0,
            original_price=24000.0,
            max_price=20000.0,
            median_pool_price=18000.0,
        )
        # Product with 0 discount at higher price
        score_lower_value = compute_price_value_score(
            price=20000.0,
            original_price=20000.0,
            max_price=20000.0,
            median_pool_price=18000.0,
        )
        assert score_good_value > score_lower_value

    def test_overall_scorer_configurable_weights(self):
        # High rating weight scenario
        breakdown_rating_heavy, _ = calculate_product_scores(
            price=18000.0,
            original_price=22000.0,
            rating=4.7,
            review_count=12000,
            title="Premium Phone",
            specifications=["8GB RAM", "AMOLED", "5G"],
            requirements=["8GB RAM"],
            availability="In Stock",
            has_amazon=True,
            has_flipkart=True,
            max_price=20000.0,
            weight_rating=0.70,
            weight_price=0.10,
            weight_requirements=0.10,
            weight_availability=0.10,
        )

        assert breakdown_rating_heavy.overall_score >= 85.0
        assert breakdown_rating_heavy.review_confidence_score >= 95.0
        assert breakdown_rating_heavy.bayesian_rating >= 4.6
