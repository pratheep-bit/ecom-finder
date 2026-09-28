import re
from typing import List, Tuple, Optional, Dict, Any
from rapidfuzz import fuzz

from backend.app.config import settings
from backend.app.models.product import (
    RequirementMatchResult,
    RequirementStatus,
    ScoringBreakdown,
)
from backend.app.ranking.rating import (
    compute_bayesian_rating,
    compute_review_confidence_score,
)


def match_single_requirement(
    req: str,
    combined_text: str,
    specs_list: List[str],
) -> RequirementMatchResult:
    """
    Evaluates whether a single user requirement (e.g. '8GB RAM', 'AMOLED', '5G', 'ANC')
    is matched, unmatched, or unknown based on the product title and specs.
    Works generically across any product domain (phones, laptops, audio, TVs, shoes).
    """
    req_clean = req.strip()
    if not req_clean:
        return RequirementMatchResult(
            requirement=req,
            status=RequirementStatus.UNKNOWN,
            confidence=0.5,
        )

    req_lower = req_clean.lower()
    text_lower = combined_text.lower()

    # Normalize unit abbreviations in req_lower and text_lower
    # e.g. "30h" <-> "30 hours", "30hrs", "30 hr"
    req_normalized = re.sub(r"\b(\d+)\s*h\b", r"\1 hours", req_lower)
    text_normalized = re.sub(r"\b(\d+)\s*hours?\b|\b(\d+)\s*hrs?\b", r"\1 hours", text_lower)

    # 1. Exact or word-boundary regex match in title or specs
    pattern = r"\b" + re.escape(req_lower) + r"\b"
    if re.search(pattern, text_lower) or re.search(r"\b" + re.escape(req_normalized) + r"\b", text_normalized):
        return RequirementMatchResult(
            requirement=req_clean,
            status=RequirementStatus.MATCHED,
            matched_token=req_clean,
            confidence=1.0,
        )

    # 2. Check tokens within requirement e.g. "8GB RAM" or "30h battery"
    tokens = req_lower.split()
    if len(tokens) > 1:
        # Check if each token or its normalized unit equivalent exists in text
        match_count = 0
        for t in tokens:
            t_norm = re.sub(r"\b(\d+)h\b", r"\1 hours", t)
            if t in text_lower or t_norm in text_normalized:
                match_count += 1
            else:
                # Check for digit part e.g. '30' and 'hours'
                digits = re.findall(r"\d+", t)
                if digits and all(d in text_lower for d in digits):
                    match_count += 1

        if match_count == len(tokens):
            return RequirementMatchResult(
                requirement=req_clean,
                status=RequirementStatus.MATCHED,
                matched_token=req_clean,
                confidence=0.95,
            )

    # 3. Fuzzy match against each individual spec line
    best_ratio = 0
    matched_spec = None
    for spec in specs_list:
        spec_lower = spec.lower()
        ratio = fuzz.partial_ratio(req_lower, spec_lower)
        if ratio > best_ratio:
            best_ratio = ratio
            matched_spec = spec

    if best_ratio >= 85:
        return RequirementMatchResult(
            requirement=req_clean,
            status=RequirementStatus.MATCHED,
            matched_token=matched_spec,
            confidence=round(best_ratio / 100.0, 2),
        )

    # 4. If specs were provided but requirement is absent -> check for contradiction or unmatched
    # For example, user asked for "16GB RAM" and specs say "8 GB RAM" or "4 GB RAM"
    # Check if number + unit conflict exists
    num_match = re.search(r"(\d+)\s*(gb|tb|mah|hz|w)\b", req_lower)
    if num_match:
        target_val, unit = num_match.groups()
        # Find any other mention of same unit in specs
        conflict_pattern = rf"(\d+)\s*{re.escape(unit)}\b"
        found_vals = re.findall(conflict_pattern, text_lower)
        if found_vals and target_val not in found_vals:
            # Different value found for the same unit -> UNMATCHED
            return RequirementMatchResult(
                requirement=req_clean,
                status=RequirementStatus.UNMATCHED,
                matched_token=f"Found: {found_vals[0]} {unit.upper()}",
                confidence=0.85,
            )

    # If we have little or no spec details, mark UNKNOWN rather than falsely claiming absence or presence
    if len(specs_list) < 2:
        return RequirementMatchResult(
            requirement=req_clean,
            status=RequirementStatus.UNKNOWN,
            confidence=0.5,
        )

    return RequirementMatchResult(
        requirement=req_clean,
        status=RequirementStatus.UNMATCHED,
        confidence=0.7,
    )


def evaluate_requirements(
    title: str,
    specifications: List[str],
    requirements: List[str],
) -> Tuple[List[RequirementMatchResult], float]:
    """
    Evaluates all user requirements against product title and specs.
    Returns the list of match results and a normalized score (0.0 to 100.0).
    """
    if not requirements:
        return [], 100.0

    combined_text = f"{title} " + " ".join(specifications)
    results: List[RequirementMatchResult] = []
    total_score = 0.0

    for req in requirements:
        res = match_single_requirement(req, combined_text, specifications)
        results.append(res)
        if res.status == RequirementStatus.MATCHED:
            total_score += 100.0 * res.confidence
        elif res.status == RequirementStatus.UNKNOWN:
            # Neutral score for unknown specs (does not harshly penalize if scraper lacked deep specs)
            total_score += 50.0
        else:
            total_score += 0.0

    req_score = round(total_score / len(requirements), 1)
    return results, req_score


def compute_price_value_score(
    price: float,
    original_price: Optional[float],
    max_price: Optional[float],
    median_pool_price: float,
) -> float:
    """
    Evaluates the price/value proposition:
    - Relative discount percentage
    - Budget efficiency (providing great specs comfortably below the user's max budget)
    - Competitiveness against the median candidate price in the search pool
    """
    if price <= 0:
        return 50.0

    # 1. Discount score (up to 35 points)
    discount_score = 0.0
    if original_price and original_price > price:
        discount_pct = ((original_price - price) / original_price) * 100.0
        # 40% discount maxes out this component
        discount_score = min(35.0, (discount_pct / 40.0) * 35.0)
    else:
        discount_score = 10.0  # baseline

    # 2. Budget tier alignment / value proposition (up to 40 points)
    budget_score = 20.0
    if max_price and max_price > 0:
        if price <= max_price:
            ratio = price / max_price
            # Premium/target alignment:
            # When the user declares a budget (e.g. 70,000):
            # Best value is achieved by products utilizing 50% - 98% of the budget tier
            if 0.50 <= ratio <= 0.98:
                budget_score = 40.0
            elif 0.30 <= ratio < 0.50:
                # Moderate budget utilization
                budget_score = 22.0 + ((ratio - 0.30) / 0.20) * 18.0
            elif ratio < 0.30:
                # Severely under-budget tier mismatch (e.g. ₹7,000 on a ₹70,000 search, or ₹300)
                # Steeply decay score so cheap items / accessories do not beat flagship devices on a flagship budget
                budget_score = max(0.0, (ratio / 0.30) * 15.0)
            else:
                # 0.98 to 1.0 (Right at the ceiling)
                budget_score = 38.0
        else:
            # Over budget
            overrun_ratio = (price - max_price) / max_price
            budget_score = max(0.0, 20.0 - (overrun_ratio * 100.0))

    # 3. Market competitiveness relative to median pool price (up to 25 points)
    comp_score = 15.0
    if median_pool_price > 0:
        price_ratio = price / median_pool_price
        if 0.8 <= price_ratio <= 1.2:
            comp_score = 25.0
        elif price_ratio < 0.8:
            comp_score = 20.0
        else:
            comp_score = max(5.0, 25.0 - (price_ratio - 1.0) * 20.0)

    total_value = discount_score + budget_score + comp_score
    return round(min(100.0, max(0.0, total_value)), 1)


def compute_availability_score(
    availability: str,
    has_amazon: bool,
    has_flipkart: bool,
) -> float:
    """
    Scores stock availability and multi-channel presence (both platforms available = higher score).
    """
    avail_lower = availability.lower() if availability else ""
    if "out of stock" in avail_lower or "unavailable" in avail_lower:
        return 10.0

    score = 80.0
    # Multi-marketplace presence bonus: gives users purchasing choice and price competition
    if has_amazon and has_flipkart:
        score += 20.0
    elif has_amazon or has_flipkart:
        score += 10.0

    return min(100.0, score)


def calculate_product_scores(
    price: float,
    original_price: Optional[float],
    rating: float,
    review_count: int,
    title: str,
    specifications: List[str],
    requirements: List[str],
    availability: str,
    has_amazon: bool,
    has_flipkart: bool,
    max_price: Optional[float] = None,
    median_pool_price: float = 0.0,
    weight_rating: Optional[float] = None,
    weight_price: Optional[float] = None,
    weight_requirements: Optional[float] = None,
    weight_availability: Optional[float] = None,
    baseline_rating: float = 4.0,
    confidence_threshold: int = 50,
) -> Tuple[ScoringBreakdown, List[RequirementMatchResult]]:
    """
    Calculates the full ScoringBreakdown and requirement match results for a product.
    Weights are configurable and dynamically normalized.
    """
    # 1. Bayesian Rating & Review Confidence
    bayesian_val = compute_bayesian_rating(
        rating=rating,
        review_count=review_count,
        baseline_rating=baseline_rating,
        confidence_threshold=confidence_threshold,
    )
    # Bayesian score out of 100: rating (0-5) mapped to 0-100
    bayesian_score_100 = (bayesian_val / 5.0) * 100.0

    review_conf_pct = compute_review_confidence_score(review_count)

    # Composite rating score considers both Bayesian quality and statistical confidence
    composite_rating_quality = (0.75 * bayesian_score_100) + (0.25 * review_conf_pct)

    # 2. Price / Value Score
    price_val_score = compute_price_value_score(
        price=price,
        original_price=original_price,
        max_price=max_price,
        median_pool_price=median_pool_price,
    )

    # 3. Requirement Match Score
    req_results, req_match_score = evaluate_requirements(
        title=title,
        specifications=specifications,
        requirements=requirements,
    )

    # 4. Availability Score
    avail_score = compute_availability_score(
        availability=availability,
        has_amazon=has_amazon,
        has_flipkart=has_flipkart,
    )

    # 5. Configurable Weights Normalization
    w_r = weight_rating if weight_rating is not None else settings.WEIGHT_RATING_CONFIDENCE
    w_p = weight_price if weight_price is not None else settings.WEIGHT_PRICE_VALUE
    w_req = weight_requirements if weight_requirements is not None else settings.WEIGHT_REQUIREMENTS
    w_a = weight_availability if weight_availability is not None else settings.WEIGHT_AVAILABILITY

    # If no requirements were specified by the user, reallocate requirements weight to rating & price
    if not requirements:
        redistribute = w_req / 2.0
        w_r += redistribute
        w_p += redistribute
        w_req = 0.0

    total_w = w_r + w_p + w_req + w_a
    if total_w > 0:
        w_r /= total_w
        w_p /= total_w
        w_req /= total_w
        w_a /= total_w

    overall = (
        (composite_rating_quality * w_r)
        + (price_val_score * w_p)
        + (req_match_score * w_req)
        + (avail_score * w_a)
    )

    # Minor penalty if over budget
    if max_price and price > max_price:
        overrun_pct = ((price - max_price) / max_price) * 100.0
        # Penalize proportional to overrun
        penalty = min(25.0, overrun_pct * 1.5)
        overall = max(0.0, overall - penalty)

    breakdown = ScoringBreakdown(
        raw_rating=round(rating, 2),
        review_count=review_count,
        bayesian_rating=bayesian_val,
        review_confidence_score=review_conf_pct,
        price_value_score=price_val_score,
        requirement_match_score=req_match_score,
        availability_score=avail_score,
        overall_score=round(overall, 1),
    )

    return breakdown, req_results
