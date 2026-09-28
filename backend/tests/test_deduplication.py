import pytest
from backend.app.models.product import Marketplace, MarketplaceOffer
from backend.app.deduplication.matcher import (
    are_offers_same_product,
    merge_offers_into_unified_product,
    deduplicate_marketplace_offers,
)


class TestDeduplication:
    def test_same_product_cross_marketplace_matches(self):
        amz = MarketplaceOffer(
            marketplace=Marketplace.AMAZON,
            title="Samsung Galaxy M34 5G (Waterfall Blue, 128 GB, 8 GB RAM)",
            price=16999.0,
            original_price=24499.0,
            rating=4.1,
            review_count=18450,
            url="https://www.amazon.in/dp/B0C7BJJ11",
        )
        fk = MarketplaceOffer(
            marketplace=Marketplace.FLIPKART,
            title="SAMSUNG Galaxy M34 5G (Waterfall Blue, 128 GB) (8 GB RAM)",
            price=16499.0,
            original_price=24499.0,
            rating=4.2,
            review_count=12300,
            url="https://www.flipkart.com/p/itm12345",
        )

        is_match, score = are_offers_same_product(amz, fk)
        assert is_match is True
        assert score >= 80.0

        merged = merge_offers_into_unified_product(amz, fk)
        assert merged.brand == "Samsung"
        assert merged.best_price == 16499.0
        assert merged.primary_marketplace == Marketplace.FLIPKART
        assert merged.amazon_offer is not None
        assert merged.flipkart_offer is not None
        assert "Flipkart" in merged.best_observed_deal
        assert "₹500" in merged.best_observed_deal

    def test_different_storage_tiers_do_not_merge(self):
        amz_128 = MarketplaceOffer(
            marketplace=Marketplace.AMAZON,
            title="Motorola Edge 50 Fusion 5G (Marshmallow Blue, 128 GB, 8 GB RAM)",
            price=20999.0,
            rating=4.5,
            review_count=3200,
            url="https://amazon.in/1",
        )
        fk_256 = MarketplaceOffer(
            marketplace=Marketplace.FLIPKART,
            title="Motorola Edge 50 Fusion 5G (Marshmallow Blue, 256 GB, 8 GB RAM)",
            price=22999.0,
            rating=4.5,
            review_count=5100,
            url="https://flipkart.com/2",
        )

        is_match, _ = are_offers_same_product(amz_128, fk_256)
        assert is_match is False

    def test_deduplicate_pool(self):
        amz_offers = [
            MarketplaceOffer(
                marketplace=Marketplace.AMAZON,
                title="Sony WH-1000XM4 Wireless Noise Cancelling Headphones",
                price=19990.0,
                rating=4.6,
                review_count=18000,
                url="https://amazon.in/sony",
            ),
            MarketplaceOffer(
                marketplace=Marketplace.AMAZON,
                title="Apple AirPods Pro (2nd Generation)",
                price=21990.0,
                rating=4.7,
                review_count=9400,
                url="https://amazon.in/apple",
            ),
        ]
        fk_offers = [
            MarketplaceOffer(
                marketplace=Marketplace.FLIPKART,
                title="SONY WH-1000XM4 Bluetooth Headset with Active Noise Cancellation",
                price=19490.0,
                rating=4.5,
                review_count=8900,
                url="https://flipkart.com/sony",
            ),
        ]

        unified = deduplicate_marketplace_offers(amz_offers, fk_offers)
        # Sony matches across platforms -> 1 merged product, Apple remains 1 product -> total 2
        assert len(unified) == 2
        sony_prod = next(p for p in unified if "sony" in p.name.lower())
        assert sony_prod.amazon_offer is not None
        assert sony_prod.flipkart_offer is not None
        assert sony_prod.best_price == 19490.0
