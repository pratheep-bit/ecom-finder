import pytest
from backend.app.models.product import (
    RequirementStatus,
    UnifiedProduct,
    Marketplace,
    ScoringBreakdown,
    SearchRequest,
)
from backend.app.ranking.scorer import (
    evaluate_requirements,
    match_single_requirement,
)
from backend.app.services.search import ProductSearchService


def make_sample_product(name: str, price: float, specs: list, rating: float = 4.3):
    return UnifiedProduct(
        id=f"test_{price}",
        name=name,
        brand="Brand",
        normalized_title=name.lower(),
        best_price=price,
        rating=rating,
        review_count=1000,
        primary_marketplace=Marketplace.AMAZON,
        availability="In Stock",
        key_specifications=specs,
        scoring=ScoringBreakdown(
            raw_rating=rating,
            review_count=1000,
            bayesian_rating=rating,
            review_confidence_score=90.0,
            price_value_score=80.0,
            requirement_match_score=80.0,
            availability_score=90.0,
            overall_score=85.0,
        ),
    )


class TestBudgetAndRequirements:
    def test_budget_hard_constraint_default(self):
        """
        By default, max_price is a strict cap.
        A ₹24,999 product must NOT enter top candidates when budget is ₹20,000.
        """
        service = ProductSearchService()
        prods = [
            make_sample_product("Budget Phone A", 18499.0, []),
            make_sample_product("Budget Phone B", 19999.0, []),
            make_sample_product("Overbudget Phone C", 20050.0, []),
            make_sample_product("Overbudget Phone D", 24999.0, []),
        ]
        req = SearchRequest(query="phone", max_price=20000.0, allow_over_budget=False)
        filtered = service._apply_filters(prods, req)

        prices = [p.best_price for p in filtered]
        assert 18499.0 in prices
        assert 19999.0 in prices
        assert 20050.0 not in prices
        assert 24999.0 not in prices

    def test_budget_overrun_when_explicitly_allowed(self):
        """
        When allow_over_budget is True with 10% buffer:
        Max allowed is 20,000 * 1.10 = 22,000.
        ₹20,050 is allowed, but ₹24,999 is still rejected.
        """
        service = ProductSearchService()
        prods = [
            make_sample_product("Budget Phone A", 18499.0, []),
            make_sample_product("Slightly Over Phone B", 20500.0, []),
            make_sample_product("Way Over Phone C", 24999.0, []),
        ]
        req = SearchRequest(
            query="phone",
            max_price=20000.0,
            allow_over_budget=True,
            over_budget_pct=10.0,
        )
        filtered = service._apply_filters(prods, req)
        prices = [p.best_price for p in filtered]
        assert 18499.0 in prices
        assert 20500.0 in prices
        assert 24999.0 not in prices

    def test_generic_requirements_phone(self):
        title = "Samsung Galaxy M34 5G (128 GB, 8 GB RAM)"
        specs = ["8 GB RAM", "128 GB ROM", "120Hz Super AMOLED Display", "50MP Camera", "5G Enabled"]
        reqs = ["8GB RAM", "AMOLED", "5G"]

        results, score = evaluate_requirements(title, specs, reqs)
        assert score >= 90.0
        assert len(results) == 3
        for r in results:
            assert r.status == RequirementStatus.MATCHED

    def test_generic_requirements_laptop(self):
        title = "HP Victus Gaming Laptop (RTX 3050 GPU, 16GB RAM, 512GB SSD)"
        specs = ["16GB RAM", "512GB SSD", "NVIDIA GeForce RTX 3050 GPU", "144Hz FHD"]
        reqs = ["16GB RAM", "RTX GPU"]

        results, score = evaluate_requirements(title, specs, reqs)
        assert score >= 90.0
        assert all(r.status == RequirementStatus.MATCHED for r in results)

    def test_generic_requirements_headphones(self):
        title = "Sony WH-1000XM4 Wireless Noise Cancelling Headphones"
        specs = ["Active Noise Cancellation (ANC)", "Wireless Bluetooth", "30 Hours Battery Life"]
        reqs = ["ANC", "wireless", "30h battery"]

        results, score = evaluate_requirements(title, specs, reqs)
        assert score >= 85.0

    def test_unknown_status_when_data_is_unverifiable(self):
        """
        Section 10: If the user's requirement cannot be reliably verified
        from scraped data, mark it 'Unknown' rather than claiming that the product has the feature.
        """
        title = "Basic Earbuds Generic"
        specs = []  # No specs available
        req = "Waterproof IPX8"

        res = match_single_requirement(req, title, specs)
        assert res.status == RequirementStatus.UNKNOWN

    def test_accessory_exclusion_and_price_floor(self):
        """
        Tests that accessories like cases, covers, cables, and tempered glasses
        are excluded when the query is for a smartphone.
        """
        from backend.app.normalizers.product import is_accessory_or_irrelevant

        # Cases, covers, tempered glass, cables are accessories
        assert is_accessory_or_irrelevant("Shockproof Back Cover for iPhone 15 Pro", "smartphone", 299.0) is True
        assert is_accessory_or_irrelevant("Tempered Glass Screen Protector for Samsung Galaxy", "smartphone", 199.0) is True
        assert is_accessory_or_irrelevant("Fast Charging Type-C Cable for Smartphone", "smartphone", 349.0) is True

        # Genuine smartphone is NOT an accessory
        assert is_accessory_or_irrelevant("Samsung Galaxy S24 5G (8GB RAM, 256GB)", "smartphone", 67999.0) is False
        assert is_accessory_or_irrelevant("OnePlus 12 5G (12GB RAM, 256GB)", "smartphone", 64999.0) is False

    def test_70k_budget_rejects_300rs_junk(self):
        """
        When user specifies max_price = 70,000 for a smartphone:
        A ₹300 item (e.g. mobile accessory or toy) must be completely filtered out.
        """
        service = ProductSearchService()
        prods = [
            make_sample_product("Mobile Tempered Glass 300rs", 300.0, []),
            make_sample_product("Dummy Mobile Toy 299rs", 299.0, []),
            make_sample_product("Redmi 10A Budget Phone", 7999.0, []),
            make_sample_product("OnePlus 12 5G Flagship", 64999.0, []),
            make_sample_product("Samsung Galaxy S24 5G", 67999.0, []),
        ]
        req = SearchRequest(query="smartphone", max_price=70000.0)
        filtered = service._apply_filters(prods, req)
        prices = [p.best_price for p in filtered]

        # ₹300 items are eliminated
        assert 300.0 not in prices
        assert 299.0 not in prices
        # Flagship phones within the ₹70,000 tier are preserved
        assert 64999.0 in prices
        assert 67999.0 in prices

    def test_family_diversity_in_top_5(self):
        """
        Ensures that 5 color variants of the same phone do not monopolize all 5 spots.
        """
        service = ProductSearchService()
        color_clones = [
            make_sample_product("Boltt Evo (Berry Red, 64 GB)", 7400.0, []),
            make_sample_product("Boltt Evo (Lavender Bloom, 64 GB)", 7400.0, []),
            make_sample_product("Boltt Evo (Sky Blue, 64 GB)", 7400.0, []),
            make_sample_product("Boltt Evo (Arctic White, 64 GB)", 7400.0, []),
            make_sample_product("Boltt Evo (Midnight Black, 64 GB)", 7400.0, []),
            make_sample_product("Samsung Galaxy M34 5G", 16999.0, []),
            make_sample_product("Motorola Edge 50 Fusion", 21999.0, []),
            make_sample_product("OnePlus Nord CE4 Lite", 19499.0, []),
            make_sample_product("iQOO Z9 5G", 18499.0, []),
        ]
        top_5 = service._select_diverse_top_5(color_clones)
        assert len(top_5) == 5
        names = [p.name for p in top_5]
        # Only 1 Boltt Evo should be present, not 5!
        boltt_count = sum(1 for n in names if "Boltt Evo" in n)
        assert boltt_count == 1
