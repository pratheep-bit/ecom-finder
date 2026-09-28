import asyncio
import re
import time
from datetime import datetime, timezone
from typing import AsyncGenerator, Dict, Any, List, Optional
import statistics

from backend.app.config import settings
from backend.app.models.product import (
    Marketplace,
    MarketplaceOffer,
    MarketplaceStatus,
    SearchRequest,
    SearchResponse,
    UnifiedProduct,
)
from backend.app.scrapers.amazon import AmazonScraper
from backend.app.scrapers.flipkart import FlipkartScraper
from backend.app.normalizers.product import is_accessory_or_irrelevant
from backend.app.deduplication.matcher import deduplicate_marketplace_offers
from backend.app.ranking.scorer import calculate_product_scores


class ProductSearchService:
    """
    Orchestrates the entire product research and ranking workflow:
    Scraping -> Normalization -> Deduplication -> Filtering -> Bayesian Scoring -> Ranking.
    """
    def __init__(self):
        self.amazon_scraper = AmazonScraper()
        self.flipkart_scraper = FlipkartScraper()

    async def execute_search(self, request: SearchRequest) -> SearchResponse:
        """
        Executes a complete search run and returns the final SearchResponse.
        """
        start_time = time.time()
        search_query = self._build_marketplace_query(request)

        # 1. Concurrent scraping across both marketplaces
        amz_task = asyncio.create_task(
            self.amazon_scraper.search(search_query, max_results=settings.MAX_RESULTS_PER_MARKETPLACE)
        )
        fk_task = asyncio.create_task(
            self.flipkart_scraper.search(search_query, max_results=settings.MAX_RESULTS_PER_MARKETPLACE)
        )

        (amz_offers, amz_status), (fk_offers, fk_status) = await asyncio.gather(amz_task, fk_task)

        # 2. Cross-Marketplace Deduplication
        unified_pool = deduplicate_marketplace_offers(amz_offers, fk_offers)

        # 3. Filter candidates by budget and minimum rating
        filtered_products = self._apply_filters(unified_pool, request)

        # 4. Rank candidates using Bayesian rating, review confidence, and price value
        ranked_products = self._score_and_rank_products(filtered_products, request)

        # 5. Extract top 5 with family diversity (no duplicate color clones)
        top_5 = self._select_diverse_top_5(ranked_products)
        for rank_idx, prod in enumerate(top_5, 1):
            prod.rank = rank_idx

        elapsed = round(time.time() - start_time, 2)

        return SearchResponse(
            query=request.query,
            min_price=request.min_price,
            max_price=request.max_price,
            min_rating=request.min_rating or 0.0,
            requirements=request.requirements,
            analyzed_count=len(amz_offers) + len(fk_offers),
            amazon_count=len(amz_offers),
            flipkart_count=len(fk_offers),
            deduplicated_count=len(unified_pool),
            marketplaces_status=[amz_status, fk_status],
            top_5=top_5,
            all_ranked=ranked_products,
            execution_time_seconds=elapsed,
            execution_time_ms=round(elapsed * 1000.0, 1),
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )

    async def execute_search_stream(self, request: SearchRequest) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Server-Sent Events (SSE) generator streaming real backend execution milestones.
        No fabricated percentages; streams real event states.
        """
        start_time = time.time()
        search_query = self._build_marketplace_query(request)

        yield {
            "stage": "init",
            "message": f"Searching Amazon India & Flipkart India for '{search_query}'...",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Amazon search
        yield {"stage": "searching_amazon", "message": "Querying Amazon India..."}
        amz_offers, amz_status = await self.amazon_scraper.search(
            search_query, max_results=settings.MAX_RESULTS_PER_MARKETPLACE
        )
        yield {
            "stage": "amazon_complete",
            "status": amz_status.status,
            "count": len(amz_offers),
            "message": f"Amazon India: {len(amz_offers)} products retrieved ({amz_status.message})",
        }

        # Flipkart search
        yield {"stage": "searching_flipkart", "message": "Querying Flipkart India..."}
        fk_offers, fk_status = await self.flipkart_scraper.search(
            search_query, max_results=settings.MAX_RESULTS_PER_MARKETPLACE
        )
        yield {
            "stage": "flipkart_complete",
            "status": fk_status.status,
            "count": len(fk_offers),
            "message": f"Flipkart India: {len(fk_offers)} products retrieved ({fk_status.message})",
        }

        total_scraped = len(amz_offers) + len(fk_offers)
        yield {
            "stage": "analyzing",
            "message": f"Normalizing and cross-matching {total_scraped} total candidates...",
        }

        # Deduplication
        unified_pool = deduplicate_marketplace_offers(amz_offers, fk_offers)
        overlap_count = (len(amz_offers) + len(fk_offers)) - len(unified_pool)
        yield {
            "stage": "deduplicated",
            "count": len(unified_pool),
            "overlap_count": overlap_count,
            "message": f"Deduplicated to {len(unified_pool)} distinct products ({overlap_count} cross-marketplace matches).",
        }

        # Filtering
        yield {"stage": "filtering", "message": "Applying budget constraints and minimum rating filter..."}
        filtered_products = self._apply_filters(unified_pool, request)
        yield {
            "stage": "filtered",
            "count": len(filtered_products),
            "message": f"{len(filtered_products)} products passed budget (₹{request.max_price:,.0f}) and rating (≥{request.min_rating} stars) criteria.",
        }

        # Scoring & Bayesian confidence
        yield {
            "stage": "scoring",
            "message": "Calculating Bayesian weighted ratings, review confidence & value scores...",
        }
        ranked_products = self._score_and_rank_products(filtered_products, request)

        top_5 = self._select_diverse_top_5(ranked_products)
        for rank_idx, prod in enumerate(top_5, 1):
            prod.rank = rank_idx

        elapsed = round(time.time() - start_time, 2)

        final_response = SearchResponse(
            query=request.query,
            min_price=request.min_price,
            max_price=request.max_price,
            min_rating=request.min_rating or 0.0,
            requirements=request.requirements,
            analyzed_count=total_scraped,
            amazon_count=len(amz_offers),
            flipkart_count=len(fk_offers),
            deduplicated_count=len(unified_pool),
            marketplaces_status=[amz_status, fk_status],
            top_5=top_5,
            all_ranked=ranked_products,
            execution_time_seconds=elapsed,
            execution_time_ms=round(elapsed * 1000.0, 1),
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )

        yield {
            "stage": "complete",
            "message": f"Identified Top 5 products in {elapsed}s.",
            "data": final_response.model_dump(),
        }

    def _build_marketplace_query(self, request: SearchRequest) -> str:
        """
        Enriches product search queries with declared budget constraints.
        When users declare a budget (e.g. max_price=70000), targeting marketplace queries
        ensures live search results surface flagship tier products rather than generic cheap items.
        """
        clean_q = request.query.strip()
        has_price_filter = any(w in clean_q.lower() for w in ("under", "below", "between", "rs", "inr", "₹", "budget", "k", "000"))
        if not has_price_filter and request.max_price and request.max_price >= 5000:
            if request.min_price and request.min_price > 0:
                return f"{clean_q} {int(request.min_price)} to {int(request.max_price)}"
            return f"{clean_q} under {int(request.max_price)}"
        return clean_q

    def _select_diverse_top_5(self, ranked_products: List[UnifiedProduct]) -> List[UnifiedProduct]:
        """
        Extracts up to 5 top products while ensuring product model family diversity,
        so users never get 5 color variants of the exact same device.
        """
        distinct_top_5: List[UnifiedProduct] = []
        seen_families = set()

        for prod in ranked_products:
            family = self._extract_product_family(prod.name, prod.brand)
            if family not in seen_families:
                seen_families.add(family)
                distinct_top_5.append(prod)
                if len(distinct_top_5) == 5:
                    break

        # If distinct families were fewer than 5, fill remainder with next best products
        if len(distinct_top_5) < 5:
            for prod in ranked_products:
                if prod not in distinct_top_5:
                    distinct_top_5.append(prod)
                    if len(distinct_top_5) == 5:
                        break

        return distinct_top_5

    def _extract_product_family(self, name: str, brand: str) -> str:
        """
        Normalizes a product name into a base family string (e.g. 'boltt evo', 'galaxy s24')
        by stripping colors, storage sizes, RAM, and packaging words.
        """
        clean = re.sub(r"\(.*?\)", "", name.lower())
        clean = re.sub(r"\b\d+\s*gb\b|\b\d+\s*tb\b|\b\d+\s*ram\b|\b\d+\s*rom\b", "", clean)
        clean = re.sub(r"\b(black|white|blue|green|red|purple|gold|silver|titanium|gray|grey|yellow|pink|orange|berry|lavender|arctic|midnight)\b", "", clean)
        clean = re.sub(r"[^\w\s]", " ", clean)
        tokens = [w for w in clean.split() if len(w) > 1 and w not in ("edition", "series", "lite", "plus", "pro", "max", "ultra", "5g", "4g")]
        return " ".join(tokens[:2]) if len(tokens) >= 2 else clean.strip()[:20]

    def _apply_filters(self, products: List[UnifiedProduct], request: SearchRequest) -> List[UnifiedProduct]:
        """
        Enforces maximum price, minimum price, category floors, accessory exclusion,
        and minimum star rating constraints.
        """
        filtered = []
        max_budget = request.max_price

        # Calculate maximum budget ceiling
        if max_budget and max_budget > 0:
            if request.allow_over_budget:
                tolerance = 1.0 + (request.over_budget_pct / 100.0)
                effective_max_price = max_budget * tolerance
            else:
                effective_max_price = max_budget
        else:
            effective_max_price = None

        min_rating = request.min_rating or 0.0

        for p in products:
            # 1. Filter out accessories (cases, covers, cables, tempered glass) or sub-category junk
            if is_accessory_or_irrelevant(p.name, request.query, p.best_price):
                continue

            # 2. Maximum budget constraint
            if effective_max_price is not None and p.best_price > effective_max_price:
                continue

            # 3. Explicit Minimum Price constraint
            if request.min_price is not None and p.best_price < request.min_price:
                continue

            # 4. Rating constraint
            if p.rating < min_rating:
                continue

            filtered.append(p)

        # Graceful fallback: If strict rating filter eliminated all items within budget,
        # relax the rating filter so the user still gets the top available products within budget
        if not filtered and min_rating > 0.0:
            for p in products:
                if is_accessory_or_irrelevant(p.name, request.query, p.best_price):
                    continue
                if effective_max_price is not None and p.best_price > effective_max_price:
                    continue
                if request.min_price is not None and p.best_price < request.min_price:
                    continue
                filtered.append(p)

        return filtered

    def _score_and_rank_products(
        self,
        products: List[UnifiedProduct],
        request: SearchRequest,
    ) -> List[UnifiedProduct]:
        """
        Calculates multi-dimensional scoring breakdowns and sorts products descending by overall score.
        """
        if not products:
            return []

        # Determine median candidate price for relative value scaling
        all_prices = [p.best_price for p in products if p.best_price > 0]
        median_price = statistics.median(all_prices) if all_prices else 0.0

        scored_products: List[UnifiedProduct] = []

        for p in products:
            scoring, matched_reqs = calculate_product_scores(
                price=p.best_price,
                original_price=p.original_price,
                rating=p.rating,
                review_count=p.review_count,
                title=p.name,
                specifications=p.key_specifications,
                requirements=request.requirements,
                availability=p.availability,
                has_amazon=p.amazon_offer is not None,
                has_flipkart=p.flipkart_offer is not None,
                max_price=request.max_price,
                median_pool_price=median_price,
                weight_rating=request.weight_rating,
                weight_price=request.weight_price,
                weight_requirements=request.weight_requirements,
                weight_availability=request.weight_availability,
                baseline_rating=settings.BAYESIAN_BASELINE_RATING,
                confidence_threshold=settings.BAYESIAN_MIN_REVIEWS,
            )

            p.scoring = scoring
            p.matched_requirements = matched_reqs
            scored_products.append(p)

        # Sort descending by overall_score, tie-breaking with review_confidence_score and best_price
        scored_products.sort(
            key=lambda item: (
                item.scoring.overall_score,
                item.scoring.review_confidence_score,
                -item.best_price,
            ),
            reverse=True,
        )

        return scored_products
