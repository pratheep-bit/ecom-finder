import random
import time
from abc import ABC, abstractmethod
from typing import List, Tuple, Dict, Any, Optional

from backend.app.config import settings
from backend.app.models.product import Marketplace, MarketplaceOffer, MarketplaceStatus


USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


class BaseMarketplaceScraper(ABC):
    """
    Abstract base adapter for marketplace scrapers.
    Defines common header generation, rate limiting, and extraction interface.
    """
    def __init__(self, marketplace: Marketplace, base_url: str):
        self.marketplace = marketplace
        self.base_url = base_url
        self.timeout = settings.REQUEST_TIMEOUT_SECONDS

    def get_headers(self) -> Dict[str, str]:
        """
        Generates standard polite browser request headers.
        """
        ua = random.choice(USER_AGENTS)
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
        }

    @abstractmethod
    async def search(self, query: str, max_results: int = 40) -> Tuple[List[MarketplaceOffer], MarketplaceStatus]:
        """
        Asynchronously searches the marketplace and returns candidates and operational status.
        """
        pass
