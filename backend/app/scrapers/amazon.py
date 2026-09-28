import time
import urllib.parse
from typing import List, Tuple
import httpx
from bs4 import BeautifulSoup

from backend.app.config import settings
from backend.app.models.product import Marketplace, MarketplaceOffer, MarketplaceStatus
from backend.app.normalizers.product import (
    parse_price,
    parse_review_count,
    parse_discount_pct,
    clean_specifications,
    is_accessory_or_irrelevant,
)
from backend.app.scrapers.base import BaseMarketplaceScraper
from backend.app.scrapers.mock_data import generate_mock_offers_for_query


class AmazonScraper(BaseMarketplaceScraper):
    """
    Amazon India marketplace search adapter.
    Routes through ScraperAPI residential proxy when SCRAPERAPI_KEY is set,
    so Vercel deployments get real results instead of CAPTCHA fallback.
    Falls back to curated catalog if scraping fails.
    """
    def __init__(self):
        super().__init__(Marketplace.AMAZON, settings.AMAZON_BASE_URL)

    def _build_request_url(self, search_url: str) -> str:
        """
        If SCRAPERAPI_KEY is configured, wrap the target URL through ScraperAPI
        which uses residential IPs not blocked by Amazon's bot manager.
        """
        key = getattr(settings, "SCRAPERAPI_KEY", None)
        if key:
            encoded = urllib.parse.quote_plus(search_url)
            return f"https://api.scraperapi.com/?api_key={key}&url={encoded}&country_code=in&render=false"
        return search_url

    async def search(self, query: str, max_results: int = 40) -> Tuple[List[MarketplaceOffer], MarketplaceStatus]:
        start_time = time.time()
        encoded_query = urllib.parse.quote_plus(query)
        raw_search_url = f"{self.base_url}/s?k={encoded_query}"

        if settings.SCRAPER_MODE == "mock":
            offers = generate_mock_offers_for_query(query, Marketplace.AMAZON)[:max_results]
            elapsed_ms = round((time.time() - start_time) * 1000, 1)
            return offers, MarketplaceStatus(
                marketplace=Marketplace.AMAZON,
                status="ok",
                count=len(offers),
                message="Mock mode catalog utilized",
                latency_ms=elapsed_ms,
            )

        try:
            request_url = self._build_request_url(raw_search_url)
            headers = self.get_headers()
            async with httpx.AsyncClient(headers=headers, timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(request_url)

            elapsed_ms = round((time.time() - start_time) * 1000, 1)
            text = response.text

            # Detect CAPTCHA / bot challenge (only for direct requests, not ScraperAPI)
            is_bot_challenge = (
                "Robot Check" in text
                or "Type the characters you see in this image" in text
                or "bm-verify=" in text
                or "api-services-support@amazon.com" in text
                or response.status_code in (429, 503)
            )

            if is_bot_challenge:
                reason = "Amazon India bot challenge (CAPTCHA) encountered. No ScraperAPI key configured."
                if settings.SCRAPER_MODE == "hybrid":
                    fallback_offers = generate_mock_offers_for_query(query, Marketplace.AMAZON)[:max_results]
                    return fallback_offers, MarketplaceStatus(
                        marketplace=Marketplace.AMAZON,
                        status="fallback_used",
                        count=len(fallback_offers),
                        message=f"{reason} Set SCRAPERAPI_KEY in environment to enable real scraping.",
                        latency_ms=elapsed_ms,
                    )
                return [], MarketplaceStatus(
                    marketplace=Marketplace.AMAZON,
                    status="unavailable",
                    count=0,
                    message=reason,
                    latency_ms=elapsed_ms,
                )

            soup = BeautifulSoup(text, "html.parser")

            # Parse live Amazon search result cards
            result_items = (
                soup.select("[data-component-type='s-search-result']")
                or soup.select(".s-asin[data-asin]")
                or soup.select("div[data-asin]:has(h2)")
            )

            offers: List[MarketplaceOffer] = []
            for item in result_items:
                if len(offers) >= max_results:
                    break

                asin = item.get("data-asin", "").strip()
                if not asin:
                    continue

                # Title
                h2 = item.select_one("h2")
                title = ""
                if h2:
                    span = h2.select_one("span")
                    title = span.get_text(strip=True) if span else h2.get_text(strip=True)
                if not title or len(title) < 4:
                    continue

                # Price
                price_whole = item.select_one(".a-price-whole")
                price_fraction = item.select_one(".a-price-fraction")
                current_price = None
                if price_whole:
                    price_str = price_whole.get_text(strip=True).replace(",", "").replace(".", "")
                    frac = price_fraction.get_text(strip=True) if price_fraction else "00"
                    try:
                        current_price = float(f"{price_str}.{frac}")
                    except ValueError:
                        pass

                if not current_price:
                    for span in item.select(".a-price .a-offscreen"):
                        p = parse_price(span.get_text(strip=True))
                        if p and p > 0:
                            current_price = p
                            break

                if not current_price:
                    continue

                # MRP / original price
                orig_elem = item.select_one(".a-text-price .a-offscreen, .a-price.a-text-price .a-offscreen")
                original_price = parse_price(orig_elem.get_text(strip=True)) if orig_elem else None
                if original_price and original_price <= current_price:
                    original_price = None

                discount_pct = parse_discount_pct(current_price, original_price)

                # Filter accessories
                if is_accessory_or_irrelevant(title, query, current_price):
                    continue

                # Rating
                rating_elem = item.select_one(".a-icon-alt")
                rating = 4.0
                if rating_elem:
                    try:
                        rating = float(rating_elem.get_text(strip=True).split()[0])
                        rating = max(1.0, min(5.0, rating))
                    except (ValueError, IndexError):
                        pass

                # Reviews
                rev_elem = item.select_one("[aria-label*='ratings'], .a-size-base.s-underline-text")
                review_count = parse_review_count(rev_elem.get_text(strip=True)) if rev_elem else 100

                # Image — Amazon uses data-src for lazy loading
                img_elem = (
                    item.select_one("img.s-image")
                    or item.select_one(".s-product-image-container img")
                    or item.select_one("img[data-src]")
                    or item.select_one("img[src]")
                )
                img_url = None
                if img_elem:
                    img_url = (
                        img_elem.get("src")
                        or img_elem.get("data-src")
                        or img_elem.get("data-a-dynamic-image", "").split('"')[1]
                    )
                    # Upscale: replace thumbnail size with large
                    if img_url:
                        import re as _re
                        img_url = _re.sub(r"\._[A-Z0-9_,]+_\.", "._SL1500_.", img_url)

                # Specs from bullet features
                feature_bullets = item.select(".a-list-item")
                specs = clean_specifications([b.get_text(strip=True) for b in feature_bullets])

                product_url = f"https://www.amazon.in/dp/{asin}"

                offers.append(MarketplaceOffer(
                    marketplace=Marketplace.AMAZON,
                    product_id=f"amz_{asin}",
                    title=title,
                    price=current_price,
                    original_price=original_price,
                    discount_pct=discount_pct,
                    rating=rating,
                    review_count=review_count,
                    url=product_url,
                    image_url=img_url,
                    images=[img_url] if img_url else [],
                    availability="In Stock",
                    specifications=specs,
                ))

            if offers:
                return offers, MarketplaceStatus(
                    marketplace=Marketplace.AMAZON,
                    status="ok",
                    count=len(offers),
                    message="Live Amazon scraping successful",
                    latency_ms=elapsed_ms,
                )

            # Zero results parsed → fallback
            if settings.SCRAPER_MODE == "hybrid":
                fallback_offers = generate_mock_offers_for_query(query, Marketplace.AMAZON)[:max_results]
                return fallback_offers, MarketplaceStatus(
                    marketplace=Marketplace.AMAZON,
                    status="fallback_used",
                    count=len(fallback_offers),
                    message="0 items parsed from Amazon HTML (page structure may have changed). Using fallback catalog.",
                    latency_ms=elapsed_ms,
                )

            return [], MarketplaceStatus(
                marketplace=Marketplace.AMAZON,
                status="unavailable",
                count=0,
                message="No products parsed from Amazon search page",
                latency_ms=elapsed_ms,
            )

        except Exception as e:
            elapsed_ms = round((time.time() - start_time) * 1000, 1)
            if settings.SCRAPER_MODE == "hybrid":
                fallback_offers = generate_mock_offers_for_query(query, Marketplace.AMAZON)[:max_results]
                return fallback_offers, MarketplaceStatus(
                    marketplace=Marketplace.AMAZON,
                    status="fallback_used",
                    count=len(fallback_offers),
                    message=f"Amazon request error: {str(e)[:100]}. Using fallback catalog.",
                    latency_ms=elapsed_ms,
                )
            return [], MarketplaceStatus(
                marketplace=Marketplace.AMAZON,
                status="unavailable",
                count=0,
                message=f"Amazon connection error: {str(e)}",
                latency_ms=elapsed_ms,
            )
