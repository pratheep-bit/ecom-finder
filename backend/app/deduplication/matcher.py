import re
import uuid
from typing import List, Optional, Tuple, Dict
from rapidfuzz import fuzz

from backend.app.models.product import (
    Marketplace,
    MarketplaceOffer,
    UnifiedProduct,
    ScoringBreakdown,
)
from backend.app.normalizers.product import (
    extract_brand,
    normalize_title,
    clean_specifications,
)


def extract_model_identifiers(title: str) -> List[str]:
    """
    Extracts alphanumeric model designations or key identifiers from a product title:
    e.g. 'Galaxy S24', 'iPhone 15', 'RTX 4060', 'WH-1000XM4', 'Edge 50 Pro', 'S23'
    """
    tokens = []
    # 1. Alphanumeric tokens e.g. S24, M34, WH-1000XM4
    candidates = re.findall(
        r"\b[A-Za-z0-9]+-[A-Za-z0-9]+\b|\b[A-Za-z]+[0-9]+[A-Za-z0-9]*\b|\b[0-9]+[A-Za-z]+[A-Za-z0-9]*\b",
        title
    )
    for c in candidates:
        c_clean = c.lower()
        if len(c_clean) >= 2 and c_clean not in ("5g", "4g", "3g", "8gb", "6gb", "4gb", "12gb", "16gb", "128gb", "256gb", "512gb", "1tb", "2k", "4k"):
            tokens.append(c_clean)

    # 2. Key series + number patterns: "iPhone 15", "Pixel 8", "OnePlus 12", "Note 13", "Edge 50", "Galaxy S24"
    series_patterns = [
        r"\biphone\s+(\d+(?:\s*(?:pro\s*max|pro|plus|mini))?)\b",
        r"\bpixel\s+(\d+(?:\s*(?:pro|a))?)\b",
        r"\boneplus\s+(\d+(?:\s*(?:r|pro|t))?)\b",
        r"\bgalaxy\s+([a-z]\d+)\b",
        r"\bnote\s+(\d+(?:\s*pro\+?|\s*pro)?)\b",
        r"\bedge\s+(\d+)\b",
        r"\bm\s*(\d+)\b",
        r"\ba\s*(\d+)\b",
        r"\bmacbook\s+(air|pro)?\s*(m\d|a\d+)?\b",
    ]
    for pat in series_patterns:
        matches = re.findall(pat, title, re.IGNORECASE)
        for m in matches:
            if isinstance(m, tuple):
                m_str = " ".join([x for x in m if x]).strip().lower()
            else:
                m_str = m.strip().lower()
            if m_str:
                tokens.append(m_str)

    return list(dict.fromkeys(tokens))


def extract_variant_attributes(title: str) -> Dict[str, Optional[str]]:
    """
    Extracts storage and RAM attributes to prevent false merging of different hardware tiers
    (e.g. 128GB vs 256GB).
    """
    ram_match = re.search(r"\b(\d+)\s*gb\s*ram\b", title, re.IGNORECASE)
    storage_match = re.search(r"\b(\d+)\s*(?:gb|tb)\s*(?:rom|storage|\b)", title, re.IGNORECASE)

    return {
        "ram": ram_match.group(1) if ram_match else None,
        "storage": storage_match.group(1) if storage_match else None,
    }


def are_offers_same_product(offer_a: MarketplaceOffer, offer_b: MarketplaceOffer) -> Tuple[bool, float]:
    """
    Determines whether two marketplace offers refer to the same physical product.
    Requires:
    1. Matching Brand (or generic similarity)
    2. High fuzzy similarity on normalized titles (RapidFuzz token_set_ratio and token_sort_ratio)
    3. No conflicting hardware tiers (e.g. 128GB cannot merge with 256GB)
    4. No conflicting model generation identifiers (e.g. S23 can NEVER merge with S24)
    """
    if offer_a.marketplace == offer_b.marketplace:
        return False, 0.0

    brand_a = extract_brand(offer_a.title).lower()
    brand_b = extract_brand(offer_b.title).lower()

    if brand_a != "generic" and brand_b != "generic" and brand_a != brand_b:
        return False, 0.0

    norm_a = normalize_title(offer_a.title)
    norm_b = normalize_title(offer_b.title)

    # Check hardware variants (RAM/Storage)
    var_a = extract_variant_attributes(offer_a.title)
    var_b = extract_variant_attributes(offer_b.title)

    if var_a["storage"] and var_b["storage"] and var_a["storage"] != var_b["storage"]:
        return False, 0.0
    if var_a["ram"] and var_b["ram"] and var_a["ram"] != var_b["ram"]:
        return False, 0.0

    # RapidFuzz fuzzy token comparison
    token_sort = fuzz.token_sort_ratio(norm_a, norm_b)
    token_set = fuzz.token_set_ratio(norm_a, norm_b)
    partial = fuzz.partial_ratio(norm_a, norm_b)

    # Check for model code matches (e.g. 'wh-1000xm4' or 'm34' or 's23')
    models_a = extract_model_identifiers(offer_a.title)
    models_b = extract_model_identifiers(offer_b.title)

    # CRITICAL: Strict Model Disjoint Guardrail
    # If both offers specify distinct model generations/series (e.g. ['s24'] vs ['s23'] or ['15'] vs ['14']),
    # they are different hardware models. NEVER merge them regardless of token overlap.
    if models_a and models_b and set(models_a).isdisjoint(set(models_b)):
        return False, 0.0

    common_models = set(models_a).intersection(set(models_b))

    if common_models:
        # With matching model code and same brand, token_set_ratio >= 60 confirms match
        if token_set >= 60.0:
            return True, max(token_set, token_sort)

    composite_score = (token_sort * 0.40) + (token_set * 0.45) + (partial * 0.15)
    threshold = 72.0 if common_models else 80.0

    if composite_score >= threshold or token_set >= 85.0:
        return True, max(composite_score, token_set)

    return False, composite_score


def merge_offers_into_unified_product(
    primary_offer: MarketplaceOffer,
    secondary_offer: Optional[MarketplaceOffer] = None,
) -> UnifiedProduct:
    """
    Merges single or dual offers into a single unified product entity.
    Maintains provenance of both Amazon and Flipkart offers, calculating
    best observed price, aggregate reviews, and comparison metadata.
    """
    amazon_offer: Optional[MarketplaceOffer] = None
    flipkart_offer: Optional[MarketplaceOffer] = None

    if primary_offer.marketplace == Marketplace.AMAZON:
        amazon_offer = primary_offer
    else:
        flipkart_offer = primary_offer

    if secondary_offer:
        if secondary_offer.marketplace == Marketplace.AMAZON:
            amazon_offer = secondary_offer
        else:
            flipkart_offer = secondary_offer

    # Calculate best price & marketplace deal comparison
    if amazon_offer and flipkart_offer:
        if amazon_offer.price < flipkart_offer.price:
            best_price = amazon_offer.price
            best_market = Marketplace.AMAZON
            diff = flipkart_offer.price - amazon_offer.price
            deal_summary = f"Amazon — ₹{best_price:,.0f} (₹{diff:,.0f} lower than Flipkart)"
        elif flipkart_offer.price < amazon_offer.price:
            best_price = flipkart_offer.price
            best_market = Marketplace.FLIPKART
            diff = amazon_offer.price - flipkart_offer.price
            deal_summary = f"Flipkart — ₹{best_price:,.0f} (₹{diff:,.0f} lower than Amazon)"
        else:
            best_price = amazon_offer.price
            best_market = Marketplace.AMAZON
            deal_summary = f"Same Price on Both — ₹{best_price:,.0f}"

        # Aggregate weighted rating
        total_rev = amazon_offer.review_count + flipkart_offer.review_count
        if total_rev > 0:
            agg_rating = (
                (amazon_offer.rating * amazon_offer.review_count)
                + (flipkart_offer.rating * flipkart_offer.review_count)
            ) / total_rev
        else:
            agg_rating = max(amazon_offer.rating, flipkart_offer.rating)

        review_count = total_rev
        original_price = max(
            amazon_offer.original_price or best_price,
            flipkart_offer.original_price or best_price,
        )
        # Select descriptive product title (avoid picking single-word stubs like 'HP' or 'Lenovo')
        t1 = primary_offer.title.strip()
        t2 = secondary_offer.title.strip()
        if len(t1) < 15 and len(t2) >= 15:
            clean_title = t2
        elif len(t2) < 15 and len(t1) >= 15:
            clean_title = t1
        elif 25 <= len(t1) <= 130 and len(t1) >= len(t2):
            clean_title = t1
        elif 25 <= len(t2) <= 130:
            clean_title = t2
        else:
            clean_title = t1 if len(t1) >= len(t2) else t2

        img_list = []
        for img in [primary_offer.image_url, secondary_offer.image_url]:
            if img and img not in img_list:
                img_list.append(img)
        for img in getattr(primary_offer, "images", []) + getattr(secondary_offer, "images", []):
            if img and img not in img_list:
                img_list.append(img)

        # Prioritize live scraped marketplace image (e.g. from Flipkart CDN rukminim/flixcart)
        # over any static catalog fallback
        live_img = None
        for img in img_list:
            if "rukminim" in img or "flixcart" in img:
                live_img = img
                break

        image_url = live_img if live_img else (img_list[0] if img_list else primary_offer.image_url)

        availability = (
            "In Stock"
            if "In Stock" in (primary_offer.availability, secondary_offer.availability)
            else primary_offer.availability
        )
        combined_specs = clean_specifications(
            primary_offer.specifications + secondary_offer.specifications
        )

    else:
        # Single marketplace offer
        active = primary_offer
        best_price = active.price
        best_market = active.marketplace
        deal_summary = f"{active.marketplace.value} — ₹{best_price:,.0f}"
        agg_rating = active.rating
        review_count = active.review_count
        original_price = active.original_price
        clean_title = active.title

        img_list = []
        if active.image_url:
            img_list.append(active.image_url)
        for img in getattr(active, "images", []):
            if img and img not in img_list:
                img_list.append(img)
        image_url = img_list[0] if img_list else active.image_url

        availability = active.availability
        combined_specs = clean_specifications(active.specifications)

    discount_pct = None
    if original_price and original_price > best_price:
        discount_pct = round(((original_price - best_price) / original_price) * 100.0, 1)

    brand = extract_brand(clean_title)
    product_id = f"prod_{uuid.uuid4().hex[:10]}"

    # Initial dummy scoring breakdown (populated later by ranker)
    dummy_breakdown = ScoringBreakdown(
        raw_rating=round(agg_rating, 2),
        review_count=review_count,
        bayesian_rating=round(agg_rating, 2),
        review_confidence_score=0.0,
        price_value_score=0.0,
        requirement_match_score=0.0,
        availability_score=0.0,
        overall_score=0.0,
    )

    return UnifiedProduct(
        id=product_id,
        name=clean_title,
        brand=brand,
        normalized_title=normalize_title(clean_title),
        image_url=image_url,
        images=img_list,
        best_price=best_price,
        original_price=original_price,
        discount_pct=discount_pct,
        rating=round(agg_rating, 1),
        review_count=review_count,
        primary_marketplace=best_market,
        availability=availability,
        amazon_offer=amazon_offer,
        flipkart_offer=flipkart_offer,
        best_observed_deal=deal_summary,
        key_specifications=combined_specs[:8],
        scoring=dummy_breakdown,
    )


def deduplicate_marketplace_offers(
    amazon_offers: List[MarketplaceOffer],
    flipkart_offers: List[MarketplaceOffer],
) -> List[UnifiedProduct]:
    """
    Cross-matches Amazon and Flipkart candidate offers, merging duplicates
    and retaining single-marketplace products.
    """
    unified_products: List[UnifiedProduct] = []
    matched_fk_indices = set()

    for amz in amazon_offers:
        best_match_idx = None
        highest_score = 0.0

        for idx, fk in enumerate(flipkart_offers):
            if idx in matched_fk_indices:
                continue

            is_match, score = are_offers_same_product(amz, fk)
            if is_match and score > highest_score:
                highest_score = score
                best_match_idx = idx

        if best_match_idx is not None:
            # Found pair
            fk_match = flipkart_offers[best_match_idx]
            matched_fk_indices.add(best_match_idx)
            unified = merge_offers_into_unified_product(amz, fk_match)
            unified_products.append(unified)
        else:
            # Amazon only
            unified = merge_offers_into_unified_product(amz)
            unified_products.append(unified)

    # Remaining Flipkart offers not paired
    for idx, fk in enumerate(flipkart_offers):
        if idx not in matched_fk_indices:
            unified = merge_offers_into_unified_product(fk)
            unified_products.append(unified)

    return unified_products
