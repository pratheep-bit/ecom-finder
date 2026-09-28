import pytest
from backend.app.normalizers.product import (
    parse_price,
    parse_rating,
    parse_review_count,
    parse_discount_pct,
    extract_brand,
    normalize_title,
    clean_specifications,
)


class TestParsers:
    def test_parse_price_indian_rupees(self):
        assert parse_price("₹18,499") == 18499.0
        assert parse_price("Rs. 24,999.00") == 24999.0
        assert parse_price("₹1,25,000") == 125000.0
        assert parse_price(18499) == 18499.0
        assert parse_price("₹ 999") == 999.0
        assert parse_price("Invalid") is None
        assert parse_price(None) is None

    def test_parse_rating(self):
        assert parse_rating("4.7 out of 5 stars") == 4.7
        assert parse_rating("4.7 ★") == 4.7
        assert parse_rating("4.5") == 4.5
        assert parse_rating(4.8) == 4.8
        assert parse_rating("6.5") is None  # Out of bounds
        assert parse_rating("No rating") is None
        assert parse_rating(None) is None

    def test_parse_review_count(self):
        assert parse_review_count("12,430 reviews") == 12430
        assert parse_review_count("(12,430)") == 12430
        assert parse_review_count("12.4K reviews") == 12400
        assert parse_review_count("1.2M ratings") == 1200000
        assert parse_review_count("10,705 Ratings & 766 Reviews") == 10705
        assert parse_review_count(450) == 450
        assert parse_review_count("") == 0
        assert parse_review_count(None) == 0

    def test_parse_discount_pct(self):
        # 20,000 down to 15,000 is 25% discount
        assert parse_discount_pct(15000, 20000) == 25.0
        assert parse_discount_pct(18499, 18499) is None
        assert parse_discount_pct(10000, None, "24% off") == 24.0

    def test_extract_brand(self):
        assert extract_brand("Samsung Galaxy M34 5G") == "Samsung"
        assert extract_brand("Motorola Edge 50 Fusion") == "Motorola"
        assert extract_brand("OnePlus Nord CE4") == "OnePlus"
        assert extract_brand("Sony WH-1000XM4 Wireless") == "Sony"
        assert extract_brand("Generic Bluetooth Earbuds") == "Generic"

    def test_normalize_title(self):
        raw = "Samsung Galaxy M34 5G (Waterfall Blue, 128 GB) [Deal of the Day]"
        norm = normalize_title(raw)
        assert "deal of the day" not in norm
        assert "waterfall blue" not in norm
        assert "samsung galaxy m34 5g" in norm

    def test_clean_specifications(self):
        raw_specs = ["", "  ", "8 GB RAM", "Add to Compare", "128 GB ROM", "Ratings", "8 GB RAM"]
        cleaned = clean_specifications(raw_specs)
        assert cleaned == ["8 GB RAM", "128 GB ROM"]
