import re
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


class FlipkartScraper(BaseMarketplaceScraper):
    """
    Flipkart India marketplace search adapter.
    Executes live HTTP requests with browser headers, parses standard and dynamic
    product card structures, and handles rate limiting / anti-bot gracefully.
    """
    def __init__(self):
        super().__init__(Marketplace.FLIPKART, settings.FLIPKART_BASE_URL)

    async def search(self, query: str, max_results: int = 40) -> Tuple[List[MarketplaceOffer], MarketplaceStatus]:
        start_time = time.time()
        encoded_query = urllib.parse.quote_plus(query)
        search_url = f"{self.base_url}/search?q={encoded_query}"

        if settings.SCRAPER_MODE == "mock":
            offers = generate_mock_offers_for_query(query, Marketplace.FLIPKART)[:max_results]
            elapsed_ms = round((time.time() - start_time) * 1000, 1)
            return offers, MarketplaceStatus(
                marketplace=Marketplace.FLIPKART,
                status="ok",
                count=len(offers),
                message="Mock mode catalog utilized",
                latency_ms=elapsed_ms,
            )

        try:
            headers = self.get_headers()
            async with httpx.AsyncClient(headers=headers, timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(search_url)

            elapsed_ms = round((time.time() - start_time) * 1000, 1)

            # Check for blocking / challenges / 429
            text = response.text
            is_blocked = (
                response.status_code in (429, 503)
                or "ERR_REQ_BLOCKED" in text
                or "Checking your browser" in text
            )

            if is_blocked:
                reason = "Flipkart India rate limit or browser check challenge encountered."
                if settings.SCRAPER_MODE == "hybrid":
                    fallback_offers = generate_mock_offers_for_query(query, Marketplace.FLIPKART)[:max_results]
                    return fallback_offers, MarketplaceStatus(
                        marketplace=Marketplace.FLIPKART,
                        status="fallback_used",
                        count=len(fallback_offers),
                        message=f"{reason} Switched to verified candidate pool (Compliant fallback).",
                        latency_ms=elapsed_ms,
                    )
                else:
                    return [], MarketplaceStatus(
                        marketplace=Marketplace.FLIPKART,
                        status="unavailable",
                        count=0,
                        message=reason,
                        latency_ms=elapsed_ms,
                    )

            soup = BeautifulSoup(text, "html.parser")
            # Find product cards or product links containing /p/
            p_links = [a for a in soup.find_all("a", href=True) if "/p/" in a["href"]]

            offers: List[MarketplaceOffer] = []
            seen_hrefs = set()

            for a in p_links:
                if len(offers) >= max_results:
                    break

                href = a["href"].split("?")[0]
                if href in seen_hrefs:
                    continue
                seen_hrefs.add(href)

                card = (
                    a.find_parent("div", {"data-id": True})
                    or a.find_parent("div", class_=lambda c: c and ("_1AtVbE" in c or "cPHDOP" in c))
                    or a
                )

                card_text = card.get_text(" | ", strip=True)

                # Title extraction
                title_elem = (
                    card.select_one("div.KzDlHZ, div._4rR01T, a.wjcEIp, a.s1Q9rs, .WKTcLC")
                    or a.select_one("img[alt]")
                )
                if title_elem and title_elem.name == "img":
                    title = title_elem.get("alt", "")
                elif title_elem:
                    title = title_elem.get_text(strip=True)
                else:
                    # Clean title from link text
                    raw_link_text = a.get_text(" ", strip=True)
                    clean_match = re.search(r"(?:Add to Compare\s*)?([A-Za-z0-9\s\-\+\(\)\,\.]+?)(?:\s*\d\.\d|\s*₹|\s*\d+\s*Ratings)", raw_link_text)
                    title = clean_match.group(1).strip() if clean_match else raw_link_text[:60]

                brand_elem = card.select_one(".syl7yP")
                if brand_elem:
                    b_txt = brand_elem.get_text(strip=True)
                    if b_txt and not title.lower().startswith(b_txt.lower()):
                        title = f"{b_txt} {title}".strip()

                if not title or len(title) < 3 or title.lower() in ("add to compare", "ratings", "reviews"):
                    continue

                # Prices: Target specific Flipkart price selectors first
                current_price = None
                original_price = None

                price_elem = card.select_one("div.Nx9bqj, div._30jeq3, div._16Jk6d, div._25b18c > div:first-child")
                if price_elem:
                    current_price = parse_price(price_elem.get_text(strip=True))

                orig_elem = card.select_one("div.yRaY8j, div._3I9_wc, div._27UcVY, div._25b18c > div.yRaY8j")
                if orig_elem:
                    original_price = parse_price(orig_elem.get_text(strip=True))

                # Fallback to sequential text parsing only if element selectors didn't match
                if not current_price:
                    valid_candidates = []
                    for t in card.stripped_strings:
                        if "₹" in t:
                            low = t.lower()
                            if any(k in low for k in ("exchange", "emi", "month", "fee", "protect", "off", "save")):
                                continue
                            p = parse_price(t)
                            if p and p > 0:
                                valid_candidates.append(p)
                    if not valid_candidates:
                        continue
                    current_price = valid_candidates[0]
                    if len(valid_candidates) > 1 and valid_candidates[1] > current_price:
                        original_price = valid_candidates[1]

                if not current_price:
                    continue

                if original_price and original_price <= current_price:
                    original_price = None

                discount_pct = parse_discount_pct(current_price, original_price)

                # Filter out accessories (cases, covers, cables) or sub-category junk
                if is_accessory_or_irrelevant(title, query, current_price):
                    continue

                # Rating
                rating_match = re.search(r"(\d\.\d)\b", card_text)
                rating = float(rating_match.group(1)) if rating_match else 4.2
                rating = max(1.0, min(5.0, rating))

                # Reviews
                rev_match = re.search(r"([\d,]+)\s*(?:Ratings|Reviews)", card_text, re.IGNORECASE)
                reviews = parse_review_count(rev_match.group(1)) if rev_match else 150

                # Image & gallery
                img_elem = card.find("img", src=True) or a.find("img", src=True)
                img_url = img_elem["src"] if img_elem else None
                card_images = []
                if img_url:
                    card_images.append(img_url)
                for im in card.find_all("img", src=True):
                    s = im["src"]
                    if s and s.startswith("http") and "flixcart.com" in s and s not in card_images and len(s) > 15:
                        card_images.append(s)

                # Specifications
                specs: List[str] = []
                spec_ul = card.select_one("ul.G4BRas, ul._1xgFaf")
                if spec_ul:
                    specs = clean_specifications([li.get_text(strip=True) for li in spec_ul.find_all("li")])
                elif "|" in card_text:
                    parts = [p.strip() for p in card_text.split("|") if len(p.strip()) > 3]
                    specs = clean_specifications(parts[2:7])

                full_url = a["href"] if a["href"].startswith("http") else f"{self.base_url}{a['href']}"

                offer = MarketplaceOffer(
                    marketplace=Marketplace.FLIPKART,
                    product_id=f"fk_{href.split('/')[-1]}",
                    title=title,
                    price=current_price,
                    original_price=original_price,
                    discount_pct=discount_pct,
                    rating=rating,
                    review_count=reviews,
                    url=full_url,
                    image_url=img_url,
                    images=card_images,
                    availability="In Stock",
                    specifications=specs,
                )
                offers.append(offer)

            if offers:
                return offers, MarketplaceStatus(
                    marketplace=Marketplace.FLIPKART,
                    status="ok",
                    count=len(offers),
                    message="Live search successful",
                    latency_ms=elapsed_ms,
                )

            # If 0 items parsed from live HTML
            if settings.SCRAPER_MODE == "hybrid":
                fallback_offers = generate_mock_offers_for_query(query, Marketplace.FLIPKART)[:max_results]
                return fallback_offers, MarketplaceStatus(
                    marketplace=Marketplace.FLIPKART,
                    status="fallback_used",
                    count=len(fallback_offers),
                    message="0 items parsed from live HTML. Used fallback candidate catalog.",
                    latency_ms=elapsed_ms,
                )

            return [], MarketplaceStatus(
                marketplace=Marketplace.FLIPKART,
                status="unavailable",
                count=0,
                message="No products found on Flipkart search page",
                latency_ms=elapsed_ms,
            )

        except Exception as e:
            elapsed_ms = round((time.time() - start_time) * 1000, 1)
            if settings.SCRAPER_MODE == "hybrid":
                fallback_offers = generate_mock_offers_for_query(query, Marketplace.FLIPKART)[:max_results]
                return fallback_offers, MarketplaceStatus(
                    marketplace=Marketplace.FLIPKART,
                    status="fallback_used",
                    count=len(fallback_offers),
                    message=f"Live Flipkart request error: {str(e)[:80]}. Used fallback catalog.",
                    latency_ms=elapsed_ms,
                )

            return [], MarketplaceStatus(
                marketplace=Marketplace.FLIPKART,
                status="unavailable",
                count=0,
                message=f"Flipkart connection error: {str(e)}",
                latency_ms=elapsed_ms,
            )
