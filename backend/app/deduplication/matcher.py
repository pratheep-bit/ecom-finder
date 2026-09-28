import re
import uuid
from typing import List, Optional, Tuple, Dict, Set
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

# ─────────────────────────────────────────────────────────────────────────────
# Generic noise tokens that MUST NOT influence fuzzy matching.
# These tokens are shared across MANY different products (iPhone, Pixel, Galaxy…)
# and contribute to false cross-product matches when left in the title string.
# ─────────────────────────────────────────────────────────────────────────────
_NOISE_TOKENS: Set[str] = {
    # Connectivity
    "5g", "4g", "3g", "lte", "wifi", "wi-fi", "bluetooth",
    # Storage sizes — caught separately by extract_variant_attributes
    "128gb", "256gb", "512gb", "64gb", "32gb", "1tb", "2tb",
    "rom", "storage",
    # RAM sizes
    "4gb", "6gb", "8gb", "12gb", "16gb",
    "ram",
    # Display
    "amoled", "oled", "lcd", "ips", "2k", "4k", "fhd", "hd",
    "60hz", "90hz", "120hz", "144hz",
    # Common marketing suffixes
    "india", "edition", "version", "new", "official", "latest",
    # Common colors — color words must NOT cause cross-product false matches
    "black", "white", "blue", "green", "red", "gold", "silver", "graphite",
    "midnight", "starlight", "purple", "yellow", "lavender", "coral",
    "titanium", "natural", "hazel", "obsidian", "sage", "mint",
    "onyx", "ivory", "phantom", "prism", "emerald", "flowy",
    # Camera
    "mp", "camera",
}

_NOISE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in sorted(_NOISE_TOKENS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _strip_noise(title: str) -> str:
    """
    Removes generic noise tokens from a title string, leaving only
    brand-identifying and model-identifying tokens for fuzzy comparison.
    Parenthetical color/storage like (Blue, 128 GB) are also removed.
    """
    cleaned = _NOISE_RE.sub(" ", title)
    cleaned = re.sub(r"\(.*?\)", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def extract_model_identifiers(title: str) -> List[str]:
    """
    Extracts alphanumeric model designations or key identifiers from a product title:
    e.g. 'Galaxy S24', 'iPhone 15', 'RTX 4060', 'WH-1000XM4', 'Edge 50 Pro', 'S23'
    """
    tokens = []
    candidates = re.findall(
        r"\b[A-Za-z0-9]+-[A-Za-z0-9]+\b|\b[A-Za-z]+[0-9]+[A-Za-z0-9]*\b|\b[0-9]+[A-Za-z]+[A-Za-z0-9]*\b",
        title
    )
    for c in candidates:
        c_clean = c.lower()
        if len(c_clean) >= 2 and c_clean not in _NOISE_TOKENS:
            tokens.append(c_clean)

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
        r"\biqoo\s+(\d+)\b",
        r"\bxiaomi\s+(\d+)\b",
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
    Determines whether two marketplace offers refer to the SAME physical product.

    Rules (all must pass):
    1. Different marketplaces (Amazon vs Flipkart only)
    2. Same brand — if both have a known brand, they MUST match exactly
    3. No conflicting hardware variants (128 GB != 256 GB)
    4. No conflicting model generation identifiers (S23 != S24, iPhone 15 != iPhone 14)
    5. High fuzzy similarity on NOISE-STRIPPED titles
       (generic tokens like 5G, 8 GB RAM are stripped so they cannot cause false matches)
    6. Common model identifiers must exist in the intersection
    """
    if offer_a.marketplace == offer_b.marketplace:
        return False, 0.0

    # Rule 2: Strict brand matching
    brand_a = extract_brand(offer_a.title).lower()
    brand_b = extract_brand(offer_b.title).lower()
    if brand_a != "generic" and brand_b != "generic" and brand_a != brand_b:
        return False, 0.0

    # Rule 3: Hardware variant guard
    var_a = extract_variant_attributes(offer_a.title)
    var_b = extract_variant_attributes(offer_b.title)
    if var_a["storage"] and var_b["storage"] and var_a["storage"] != var_b["storage"]:
        return False, 0.0
    if var_a["ram"] and var_b["ram"] and var_a["ram"] != var_b["ram"]:
        return False, 0.0

    # Rule 4: Model generation guard
    models_a = extract_model_identifiers(offer_a.title)
    models_b = extract_model_identifiers(offer_b.title)
    # If both sides have model identifiers and they are completely disjoint -> different products
    if models_a and models_b and set(models_a).isdisjoint(set(models_b)):
        return False, 0.0

    common_models = set(models_a).intersection(set(models_b))

    # Rule 5: Fuzzy similarity on NOISE-STRIPPED titles
    stripped_a = _strip_noise(offer_a.title)
    stripped_b = _strip_noise(offer_b.title)

    token_sort = fuzz.token_sort_ratio(stripped_a, stripped_b)
    token_set  = fuzz.token_set_ratio(stripped_a, stripped_b)
    partial    = fuzz.partial_ratio(stripped_a, stripped_b)

    # Rule 6: Common model identifier shortcut
    # If both titles share an explicit model code (e.g. 's23', 'wh-1000xm4'),
    # a high token_sort on stripped titles is sufficient to confirm a match.
    if common_models:
        if token_sort >= 75.0 or token_set >= 70.0:
            return True, max(token_sort, token_set)

    # Final composite threshold — raised to prevent cross-product false merges
    composite = (token_sort * 0.45) + (token_set * 0.40) + (partial * 0.15)
    # 90 when no model overlap; 80 when partial model overlap exists
    threshold = 80.0 if common_models else 90.0

    if composite >= threshold or token_set >= 92.0:
        return True, max(composite, token_set)

    return False, composite


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

    if amazon_offer and flipkart_offer:
        if amazon_offer.price < flipkart_offer.price:
            best_price = amazon_offer.price
            best_market = Marketplace.AMAZON
            diff = flipkart_offer.price - amazon_offer.price
            deal_summary = f"Amazon — \u20b9{best_price:,.0f} (\u20b9{diff:,.0f} lower than Flipkart)"
        elif flipkart_offer.price < amazon_offer.price:
            best_price = flipkart_offer.price
            best_market = Marketplace.FLIPKART
            diff = amazon_offer.price - flipkart_offer.price
            deal_summary = f"Flipkart — \u20b9{best_price:,.0f} (\u20b9{diff:,.0f} lower than Amazon)"
        else:
            best_price = amazon_offer.price
            best_market = Marketplace.AMAZON
            deal_summary = f"Same Price on Both — \u20b9{best_price:,.0f}"

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

        # Build image list — Amazon CDN image comes first (correct product image)
        img_list: List[str] = []
        for img in [amazon_offer.image_url] + list(getattr(amazon_offer, "images", [])):
            if img and img not in img_list:
                img_list.append(img)
        for img in [flipkart_offer.image_url] + list(getattr(flipkart_offer, "images", [])):
            if img and img not in img_list:
                img_list.append(img)

        image_url = img_list[0] if img_list else primary_offer.image_url

        availability = (
            "In Stock"
            if "In Stock" in (primary_offer.availability, secondary_offer.availability)
            else primary_offer.availability
        )
        combined_specs = clean_specifications(
            primary_offer.specifications + secondary_offer.specifications
        )

    else:
        active = primary_offer
        best_price = active.price
        best_market = active.marketplace
        deal_summary = f"{active.marketplace.value} — \u20b9{best_price:,.0f}"
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
    matched_fk_indices: set = set()

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
            fk_match = flipkart_offers[best_match_idx]
            matched_fk_indices.add(best_match_idx)
            unified = merge_offers_into_unified_product(amz, fk_match)
            unified_products.append(unified)
        else:
            unified = merge_offers_into_unified_product(amz)
            unified_products.append(unified)

    for idx, fk in enumerate(flipkart_offers):
        if idx not in matched_fk_indices:
            unified = merge_offers_into_unified_product(fk)
            unified_products.append(unified)

    return unified_products
