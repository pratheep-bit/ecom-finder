import math
from typing import Optional


def compute_bayesian_rating(
    rating: float,
    review_count: int,
    baseline_rating: float = 4.0,
    confidence_threshold: int = 50,
) -> float:
    """
    Computes the Bayesian weighted rating (True Bayesian Estimate):

        WR = (v / (v + m)) * R + (m / (v + m)) * C

    Where:
        R = observed product rating (0.0 to 5.0)
        v = number of reviews
        C = prior baseline rating (average across market or domain default, e.g. 4.0)
        m = minimum threshold of reviews for high confidence (default 50)

    Mathematical guarantees:
    1. A product with 5.0★ and only 10 reviews will regress toward the prior C=4.0:
       WR = (10/60)*5.0 + (50/60)*4.0 = 4.167
       This loses to a 4.7★ with 300 reviews:
       WR = (300/350)*4.7 + (50/350)*4.0 = 4.600

    2. A product with 3.8★ and 20,000 reviews will accurately settle near 3.800:
       WR = (20000/20050)*3.8 + (50/20050)*4.0 = 3.800
       This will NOT beat a 4.7★ with 1,000 reviews:
       WR = (1000/1050)*4.7 + (50/1050)*4.0 = 4.667

    Therefore, review count provides confidence without letting low-quality products
    outrank high-quality products purely by sheer popularity.
    """
    if rating <= 0.0:
        return 0.0

    v = max(0, review_count)
    m = max(1, confidence_threshold)
    c = max(0.0, min(5.0, baseline_rating))
    r = max(0.0, min(5.0, rating))

    weight_v = v / (v + m)
    weight_m = m / (v + m)
    weighted = (weight_v * r) + (weight_m * c)
    return round(weighted, 3)


def compute_review_confidence_score(
    review_count: int,
    half_confidence_reviews: int = 100,
) -> float:
    """
    Computes a normalized review confidence percentage (0.0% to 100.0%)
    representing the statistical stability of the rating.

    Uses a soft rational saturation curve:
        Confidence = (v / (v + k)) * 100

    Where k is the half-saturation point (e.g. 100 reviews yields 50% confidence,
    300 reviews yields 75% confidence, 900 reviews yields 90% confidence,
    and 10,000+ reviews approaches 99%+ confidence).
    """
    v = max(0, review_count)
    if v == 0:
        return 0.0

    k = max(1, half_confidence_reviews)
    confidence = (v / (v + k)) * 100.0
    return round(min(100.0, max(0.0, confidence)), 1)


def compute_wilson_lower_bound(
    positive_reviews: int,
    total_reviews: int,
    confidence: float = 0.95,
) -> float:
    """
    Optional Wilson score interval for Bernoulli parameter.
    Provided for reference or binary recommendation scoring.
    """
    if total_reviews == 0:
        return 0.0

    # z = 1.96 for 95% confidence
    z = 1.96
    p_hat = positive_reviews / total_reviews
    n = total_reviews

    denominator = 1 + z**2 / n
    centre_adjusted_probability = p_hat + z**2 / (2 * n)
    adjusted_standard_deviation = math.sqrt(
        (p_hat * (1 - p_hat) + z**2 / (4 * n)) / n
    )

    lower_bound = (
        centre_adjusted_probability - z * adjusted_standard_deviation
    ) / denominator
    return round(max(0.0, lower_bound), 3)
