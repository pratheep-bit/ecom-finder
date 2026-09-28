import re
import urllib.parse
from typing import Dict, Any, List, Optional, Tuple, AsyncGenerator
from backend.app.models.product import (
    SearchRequest,
    SearchResponse,
    ChatRequest,
    ChatResponse,
    UnifiedProduct,
)
from backend.app.services.search import ProductSearchService


class AgentService:
    """
    AI Product Research Agent service.
    Translates conversational user instructions into marketplace parameters,
    executes research workflows, and generates structured agent advice.
    """

    def __init__(self, search_service: Optional[ProductSearchService] = None):
        self.search_service = search_service or ProductSearchService()

    def parse_user_intent(self, message: str) -> Tuple[str, Dict[str, Any]]:
        """
        Parses user intent and extracts search parameters:
        - query
        - max_price
        - min_price
        - min_rating
        - requirements
        """
        text = message.strip()
        lower = text.lower()

        # Check for greeting or generic inquiries
        greetings = ("hi", "hello", "hey", "help", "who are you", "what can you do", "start")
        if lower in greetings or (len(lower.split()) <= 2 and any(g in lower for g in greetings)):
            return "greeting", {}

        params: Dict[str, Any] = {
            "query": "",
            "max_price": None,
            "min_price": None,
            "min_rating": 0.0,
            "requirements": [],
        }

        # 1. Extract Price Ceilings (e.g. "under 70k", "under 70000", "below 50,000", "budget 60k", "within 25000", "less than 1500")
        max_price_match = re.search(
            r"(?:under|below|less than|budget|within|up to|max(?:imum)?(?: price)?|ceiling)\s*(?:of|is|:)?\s*(?:₹|rs\.?|inr)?\s*([0-9]+(?:\.[0-9]+)?)\s*(k|lakh|l)?",
            lower,
        )
        if max_price_match:
            val = float(max_price_match.group(1))
            unit = max_price_match.group(2)
            if unit == "k":
                val *= 1000
            elif unit in ("lakh", "l"):
                val *= 100000
            params["max_price"] = val

        # Handle simple "70k budget" or "70000 budget"
        if not params["max_price"]:
            simple_budget = re.search(r"(\d+(?:\.\d+)?)\s*(k|lakh)?\s*(?:rs|inr|budget)", lower)
            if simple_budget:
                val = float(simple_budget.group(1))
                unit = simple_budget.group(2)
                if unit == "k":
                    val *= 1000
                elif unit == "lakh":
                    val *= 100000
                params["max_price"] = val

        # 2. Extract Minimum Rating (e.g. "4.5 stars", "above 4 star", "4+ stars", "top rated")
        if "top rated" in lower or "best rated" in lower:
            params["min_rating"] = 4.2
        else:
            rating_match = re.search(r"([34](?:\.[0-9])?)\s*(?:\+|plus)?\s*(?:star|rating)", lower)
            if rating_match:
                params["min_rating"] = float(rating_match.group(1))

        # 3. Extract Common Feature Requirements
        req_patterns = [
            (r"\b(16\s*gb(?:\s*ram)?|8\s*gb(?:\s*ram)?|12\s*gb(?:\s*ram)?|32\s*gb(?:\s*ram)?)\b", "RAM"),
            (r"\b(512\s*gb(?:\s*ssd)?|1\s*tb(?:\s*ssd)?|256\s*gb)\b", "Storage"),
            (r"\b(amoled|oled|120hz|144hz|ips|curved display)\b", "Display"),
            (r"\b(5g|4g)\b", "Connectivity"),
            (r"\b(anc|noise cancellation|active noise cancelling)\b", "ANC"),
            (r"\b(rtx\s*\d{4}|gtx\s*\d{4}|dedicated gpu|gaming)\b", "Graphics"),
            (r"\b(snapdragon|tensor|dimensity|bionic|i5|i7|i9|ryzen\s*\d)\b", "Processor"),
            (r"\b(wireless|bluetooth)\b", "Wireless"),
        ]
        for pattern, label in req_patterns:
            m = re.search(pattern, lower)
            if m:
                matched_val = m.group(1).upper()
                params["requirements"].append(matched_val)

        # 4. Clean Product Search Query
        # Remove meta instructions to isolate clean product keywords
        clean_q = re.sub(
            r"\b(find|search|show|get|recommend|suggest|what is|best|top|good|cheap|affordable|for me|me|i want|i need|looking for|buy|please|a|an|the|some|with)\b",
            "",
            lower,
        )
        # Remove price constraints phrases
        clean_q = re.sub(
            r"(?:under|below|less than|budget|within|up to|max(?:imum)?(?: price)?|ceiling)\s*(?:of|is|:)?\s*(?:₹|rs\.?|inr)?\s*[0-9]+(?:\.[0-9]+)?\s*(?:k|lakh|l)?",
            "",
            clean_q,
        )
        clean_q = re.sub(r"\b\d+\s*k\b", "", clean_q)
        clean_q = re.sub(r"(?:₹|rs\.?|inr)\s*\d+", "", clean_q)
        clean_q = re.sub(r"\b(?:top|best)\s+rated\b", "", clean_q)
        clean_q = re.sub(r"[34](?:\.[0-9])?\s*(?:\+|plus)?\s*(?:star|rating)s?", "", clean_q)
        clean_q = re.sub(r"\s+", " ", clean_q).strip()

        # Fallback if query was completely stripped
        if not clean_q or len(clean_q) < 2:
            clean_q = message.strip()

        params["query"] = clean_q
        return "search", params

    async def execute_agent_chat(self, request: ChatRequest) -> ChatResponse:
        """
        Processes a user message and returns conversational advice with ranked product cards.
        """
        intent, params = self.parse_user_intent(request.message)

        if intent == "greeting":
            return ChatResponse(
                reply=(
                    "**Hello! I am your Commerce Research Agent.**\n\n"
                    "I search and analyze products across **Amazon India and Flipkart India** in real-time. "
                    "I deduplicate listings with RapidFuzz and rank them using mathematical **Bayesian Rating Confidence** and value scoring so you never buy fake high-rated or low-review items.\n\n"
                    "**You can ask me:**\n"
                    "* *'Find best smartphone under 70000 with 5G'*\n"
                    "* *'Best HP laptop under 50k for programming'*\n"
                    "* *'Top noise cancelling headphones with ANC'*\n"
                    "* *'Show me party balloons under 500'*"
                ),
                search_params={},
                search_result=None,
                tool_steps=["Loaded commerce domain capabilities", "Ready for research query"],
                suggested_followups=[
                    "Find smartphone under 70,000",
                    "HP laptop under 50,000",
                    "Headphones under 25,000 with ANC",
                    "Party balloons under 500",
                ],
            )

        # Apply user overrides if present
        if request.max_price is not None:
            params["max_price"] = request.max_price
        if request.min_rating is not None:
            params["min_rating"] = request.min_rating

        tool_steps = [
            f"Parsed natural language intent: Target product '{params['query']}'",
            f"Extracted budget constraint: {'₹' + f'{params['max_price']:,.0f}' if params['max_price'] else 'No ceiling'}",
            f"Extracted requirements: {params['requirements'] if params['requirements'] else 'None'}",
            f"Querying Amazon India & Flipkart India live catalogs...",
        ]

        search_req = SearchRequest(
            query=params["query"],
            max_price=params["max_price"],
            min_rating=params["min_rating"] or 0.0,
            requirements=params["requirements"],
        )

        search_result = await self.search_service.execute_search(search_req)

        tool_steps.append(
            f"Retrieved {search_result.analyzed_count} offers (Amazon: {search_result.amazon_count}, Flipkart: {search_result.flipkart_count})"
        )
        tool_steps.append(f"Cross-marketplace deduplication unified into {search_result.deduplicated_count} distinct items")
        tool_steps.append("Executed Bayesian rating confidence & value ranking algorithm")

        # Synthesize conversational AI response
        reply = self._generate_agent_summary(params, search_result)
        followups = self._generate_followups(params, search_result)

        return ChatResponse(
            reply=reply,
            search_params=params,
            search_result=search_result,
            tool_steps=tool_steps,
            suggested_followups=followups,
        )

    async def stream_agent_chat(self, request: ChatRequest) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Streams agent thought progression and tool execution events over SSE.
        """
        intent, params = self.parse_user_intent(request.message)

        if intent == "greeting":
            yield {
                "type": "thought",
                "content": "User greeted or asked for capabilities. Generating welcome guidance.",
            }
            yield {
                "type": "final",
                "response": (
                    "**Hello! I am your Commerce Research Agent.**\n\n"
                    "I search and analyze products across **Amazon India and Flipkart India** simultaneously, "
                    "deduplicating listings and ranking them via **Bayesian Rating Confidence**.\n\n"
                    "Tell me what you are looking for, or pick a sample search below:"
                ),
                "search_result": None,
                "followups": [
                    "Smartphone under 70,000",
                    "HP laptop under 50,000",
                    "Headphones under 25,000 with ANC",
                    "Party balloons under 500",
                ],
            }
            return

        # Tool 1: Intent & Parameter Extraction
        yield {
            "type": "thought",
            "content": f"Analyzing request: Identifying product '{params['query']}', budget ceiling: {('₹' + f'{params['max_price']:,.0f}') if params['max_price'] else 'None'}",
        }

        search_req = SearchRequest(
            query=params["query"],
            max_price=params["max_price"],
            min_rating=params["min_rating"] or 0.0,
            requirements=params["requirements"],
        )

        # Stream search milestones
        yield {
            "type": "tool_call",
            "tool": "marketplace_search",
            "content": f"Querying Amazon India & Flipkart India for '{params['query']}'...",
        }

        search_result = await self.search_service.execute_search(search_req)

        yield {
            "type": "tool_call",
            "tool": "bayesian_ranking",
            "content": f"Analyzed {search_result.analyzed_count} offers. Applying Bayesian prior (m=50, C=4.0) & family deduplication...",
        }

        reply = self._generate_agent_summary(params, search_result)
        followups = self._generate_followups(params, search_result)

        yield {
            "type": "final",
            "response": reply,
            "search_result": search_result.model_dump(),
            "followups": followups,
        }

    def _generate_agent_summary(self, params: Dict[str, Any], result: SearchResponse) -> str:
        """
        Creates a crisp, insightful executive summary for the user.
        """
        if not result.top_5:
            budget_str = f" under ₹{params['max_price']:,.0f}" if params.get("max_price") else ""
            return (
                f"I researched **Amazon India & Flipkart India** for **\"{params['query']}\"**{budget_str}, "
                f"but found 0 products matching all combined criteria.\n\n"
                f"**Suggestions:**\n"
                f"* Try increasing your budget ceiling.\n"
                f"* Lower the minimum star rating requirement.\n"
                f"* Search with slightly broader terms."
            )

        top_prod = result.top_5[0]
        budget_str = f" under **₹{params['max_price']:,.0f}**" if params.get("max_price") else ""
        req_str = f" with **{', '.join(params['requirements'])}**" if params.get("requirements") else ""

        deal_market = top_prod.primary_marketplace.value
        best_price = f"₹{top_prod.best_price:,.0f}"
        rating_info = f"{top_prod.rating:.1f} / 5.0 ({top_prod.review_count:,} reviews)"

        summary = (
            f"I researched **{result.analyzed_count} product offers** across Amazon India and Flipkart India "
            f"for **\"{params['query']}\"**{budget_str}{req_str}.\n\n"
            f"**Top Recommendation:** **{top_prod.name}**\n"
            f"* **Best Price:** {best_price} on **{deal_market}**\n"
            f"* **Confidence:** {rating_info} with high Bayesian reliability\n\n"
            f"Below are the **Top 5 ranked products** based on verified review volume, price value, and feature matching:"
        )
        return summary

    def _generate_followups(self, params: Dict[str, Any], result: SearchResponse) -> List[str]:
        """
        Generates smart contextual follow-up query suggestions.
        """
        followups = []
        q = params.get("query", "")
        max_p = params.get("max_price")

        if max_p and max_p > 20000:
            lower_budget = int(max_p * 0.75)
            followups.append(f"Show options under ₹{lower_budget:,}")

        if "laptop" in q:
            followups.append("Filter for 16GB RAM models")
            followups.append("Gaming laptops with RTX GPU")
        elif any(t in q for t in ("phone", "smartphone", "mobile")):
            followups.append("Show only AMOLED 120Hz phones")
            followups.append("Compare Top 2 smartphones")
        elif "headphone" in q or "audio" in q:
            followups.append("Headphones with 30h+ battery")
        else:
            followups.append("Show under ₹1,000")
            followups.append("Sort by highest review count")

        return followups[:3]
