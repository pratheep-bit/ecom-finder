import time
import urllib.parse
from typing import List, Tuple
import httpx
from bs4 import BeautifulSoup

from backend.app.config import settings
from backend.app.models.product import Marketplace, MarketplaceOffer, MarketplaceStatus
from backend.app.normalizers.product import (
    parse_price,
    parse_rating,
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
    Executes live HTTP requests with standard headers, detects anti-bot challenges
    (Akamai Bot Manager, CAPTCHA, 503 Service Unavailable), and compliantly reports status.
    """
    def __init__(self):
        super().__init__(Marketplace.AMAZON, settings.AMAZON_BASE_URL)

    async def search(self, query: str, max_results: int = 40) -> Tuple[List[MarketplaceOffer], MarketplaceStatus]:
        start_time = time.time()
        encoded_query = urllib.parse.quote_plus(query)
        search_url = f"{self.base_url}/s?k={encoded_query}"

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

        # Attempt live HTTP request
        try:
            headers = self.get_headers()
            async with httpx.AsyncClient(headers=headers, timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(search_url)

            elapsed_ms = round((time.time() - start_time) * 1000, 1)

            # Analyze for CAPTCHA / Bot Manager challenge / Rate Limiting
            text = response.text
            is_bot_challenge = (
                "Robot Check" in text
                or "Type the characters you see in this image" in text
                or "bm-verify=" in text
                or "api-services-support@amazon.com" in text
                or response.status_code in (429, 503)
            )

            if is_bot_challenge:
                reason = "Amazon India bot challenge (Akamai bm-verify / Robot Check CAPTCHA) encountered."
                if settings.SCRAPER_MODE == "hybrid":
                    # Compliant fallback: return verified catalog so user can test research algorithm
                    fallback_offers = generate_mock_offers_for_query(query, Marketplace.AMAZON)[:max_results]
                    return fallback_offers, MarketplaceStatus(
                        marketplace=Marketplace.AMAZON,
                        status="fallback_used",
                        count=len(fallback_offers),
                        message=f"{reason} Switched to verified candidate pool (Compliant fallback).",
                        latency_ms=elapsed_ms,
                    )
                else:
                    return [], MarketplaceStatus(
                        marketplace=Marketplace.AMAZON,
                        status="unavailable",
                        count=0,
                        message=reason,
                        latency_ms=elapsed_ms,
                    )

            # Parse live Amazon search results
            result_items = soup.select("[data-component-type='s-search-result']")
            if not result_items:
                result_items = soup.select(".s-asin[data-asin]")
            if not result_items:
                result_items = soup.select("div[data-asin]:has(h2)")

            offers: List[MarketplaceOffer] = []
            for item in result_items:
                if len(offers) >= max_results:
                    break

                asin = item.get("data-asin")
                if not asin:
                    continue

                # Title extraction (handling Amazon split-brand / multi-line layout)
                h2 = item.select_one("h2")
                h2_text = h2.get_text(strip=True) if h2 else ""

                # Look for full product description in anchor / span
                desc_text = ""
                for a_desc in item.select("a.a-text-normal, span.a-text-normal, [class*='s-line-clamp'], h2 a"):
                    candidate = a_desc.get_text(strip=True)
                    if (
                        candidate
                        and candidate != h2_text
                        and "₹" not in candidate
                        and "stars" not in candidate
                        and "ratings" not in candidate.lower()
                        and "bought in past" not in candidate.lower()
                        and "let us know" not in candidate.lower()
                    ):
                        desc_text = candidate
                        break

                if h2_text and desc_text:
                    if desc_text.lower().startswith(h2_text.lower()):
                        title = desc_text
                    elif len(h2_text) < 20:
                        title = f"{h2_text} {desc_text}".strip()
                    else:
                        title = desc_text if len(desc_text) > len(h2_text) else h2_text
                elif desc_text:
                    title = desc_text
                else:
                    title = h2_text

                if not title or len(title) < 2:
                    continue

                # Price
                price_whole = item.select_one(".a-price-whole")
                price = parse_price(price_whole.get_text(strip=True)) if price_whole else None
                if not price:
                    continue

                # Filter out accessories (cases, covers, screen guards, cables) or sub-category junk
                if is_accessory_or_irrelevant(title, query, price):
                    continue

                # Original Price & Discount
                orig_price_elem = item.select_one(".a-price.a-text-price .a-offscreen")
                orig_price = parse_price(orig_price_elem.get_text(strip=True)) if orig_price_elem else None
                discount_pct = parse_discount_pct(price, orig_price)

                # Rating
                rating_elem = item.select_one("i.a-icon-star-small span, i.a-icon-star, .a-icon-alt")
                rating = parse_rating(rating_elem.get_text(strip=True)) if rating_elem else 4.0

                # Review count
                review_elem = item.select_one(
                    "a[href*='#customerReviews'] span, .s-underline-text, [aria-label*='stars'] + span"
                )
                reviews = parse_review_count(review_elem.get_text(strip=True)) if review_elem else 50

                # Images (extract primary and secondary for carousel)
                img_elem = item.select_one("img.s-image")
                img_url = img_elem.get("src") if img_elem else None
                card_images = []
                if img_url:
                    card_images.append(img_url)
                for im in item.select("img"):
                    s = im.get("src")
                    if s and s.startswith("http") and "media-amazon.com" in s and s not in card_images and len(s) > 15:
                        card_images.append(s)

                # Product URL: Always prefer canonical ASIN direct product link (avoids sponsored /sspa/click redirects)
                if asin:
                    product_url = f"https://www.amazon.in/dp/{asin}"
                elif href and "/dp/" in href:
                    asin_match = re.search(r"/dp/([A-Z0-9]{10})", href)
                    if asin_match:
                        product_url = f"https://www.amazon.in/dp/{asin_match.group(1)}"
                    elif href.startswith("http"):
                        product_url = href
                    else:
                        product_url = f"{self.base_url}{href if href.startswith('/') else '/' + href}"
                elif href and href.startswith("http") and "/sspa/click" not in href:
                    product_url = href
                elif href and len(href) > 2 and "/sspa/click" not in href:
                    product_url = f"{self.base_url}{href if href.startswith('/') else '/' + href}"
                else:
                    encoded_t = urllib.parse.quote_plus(title.split("(")[0].strip())
                    product_url = f"https://www.amazon.in/s?k={encoded_t}"

                # Specs snippet from search highlight bullets
                spec_elements = item.select(".a-size-base.a-color-base, .a-list-item")
                specs = clean_specifications([s.get_text(strip=True) for s in spec_elements[:5]])

                offer = MarketplaceOffer(
                    marketplace=Marketplace.AMAZON,
                    product_id=asin,
                    title=title,
                    price=price,
                    original_price=orig_price,
                    discount_pct=discount_pct,
                    rating=rating,
                    review_count=reviews,
                    url=product_url,
                    image_url=img_url,
                    images=card_images,
                    availability="In Stock",
                    specifications=specs,
                )
                offers.append(offer)

            if offers:
                return offers, MarketplaceStatus(
                    marketplace=Marketplace.AMAZON,
                    status="ok",
                    count=len(offers),
                    message="Live search successful",
                    latency_ms=elapsed_ms,
                )

            # If 0 items parsed from live HTML (e.g. Amazon changed DOM layout)
            if settings.SCRAPER_MODE == "hybrid":
                fallback_offers = generate_mock_offers_for_query(query, Marketplace.AMAZON)[:max_results]
                return fallback_offers, MarketplaceStatus(
                    marketplace=Marketplace.AMAZON,
                    status="fallback_used",
                    count=len(fallback_offers),
                    message="0 items parsed from live HTML. Used fallback candidate catalog.",
                    latency_ms=elapsed_ms,
                )

            return [], MarketplaceStatus(
                marketplace=Marketplace.AMAZON,
                status="unavailable",
                count=0,
                message="No products found on Amazon search page",
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
                    message=f"Live Amazon request error: {str(e)[:80]}. Used fallback catalog.",
                    latency_ms=elapsed_ms,
                )

            return [], MarketplaceStatus(
                marketplace=Marketplace.AMAZON,
                status="unavailable",
                count=0,
                message=f"Amazon connection error: {str(e)}",
                latency_ms=elapsed_ms,
            )
