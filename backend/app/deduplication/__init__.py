from backend.app.deduplication.matcher import (
    are_offers_same_product,
    merge_offers_into_unified_product,
    deduplicate_marketplace_offers,
)

__all__ = [
    "are_offers_same_product",
    "merge_offers_into_unified_product",
    "deduplicate_marketplace_offers",
]
