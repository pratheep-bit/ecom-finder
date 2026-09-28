from backend.app.scrapers.base import BaseMarketplaceScraper
from backend.app.scrapers.amazon import AmazonScraper
from backend.app.scrapers.flipkart import FlipkartScraper
from backend.app.scrapers.mock_data import generate_mock_offers_for_query

__all__ = [
    "BaseMarketplaceScraper",
    "AmazonScraper",
    "FlipkartScraper",
    "generate_mock_offers_for_query",
]
