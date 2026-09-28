import json
import logging
from typing import Dict, Any
from fastapi import APIRouter, Request, HTTPException, Depends
from sse_starlette.sse import EventSourceResponse

from backend.app.config import settings
from backend.app.models.product import SearchRequest, SearchResponse, ChatRequest, ChatResponse
from backend.app.services.search import ProductSearchService
from backend.app.services.agent import AgentService

logger = logging.getLogger("product_finder.api")
router = APIRouter(tags=["search"])

search_service = ProductSearchService()
agent_service = AgentService(search_service=search_service)


@router.post("/search", response_model=SearchResponse)
async def search_products(request: SearchRequest) -> SearchResponse:
    """
    Standard REST endpoint: executes research across Amazon and Flipkart India,
    applies Bayesian ranking, filters, and returns top 5 ranked products.
    """
    try:
        response = await search_service.execute_search(request)
        return response
    except Exception as e:
        logger.error(f"Search endpoint failure: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Search pipeline encountered an error: {str(e)}")


@router.post("/search/stream")
async def search_products_stream(request: SearchRequest):
    """
    Server-Sent Events (SSE) streaming endpoint:
    Streams live backend milestones (Amazon status, Flipkart status,
    candidate normalization, deduplication, scoring, ranking) to the frontend.
    """
    async def event_generator():
        try:
            async for event in search_service.execute_search_stream(request):
                yield {
                    "event": "message",
                    "data": json.dumps(event),
                }
        except Exception as e:
            logger.error(f"SSE stream error: {e}", exc_info=True)
            yield {
                "event": "error",
                "data": json.dumps({"stage": "error", "message": str(e)}),
            }

    return EventSourceResponse(event_generator())


@router.post("/chat", response_model=ChatResponse)
async def agent_chat(request: ChatRequest) -> ChatResponse:
    """
    Conversational AI agent endpoint: takes natural language instructions,
    orchestrates search across marketplaces, and replies with structured recommendations.
    """
    try:
        response = await agent_service.execute_agent_chat(request)
        return response
    except Exception as e:
        logger.error(f"Agent chat failure: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Agent workflow error: {str(e)}")


@router.post("/chat/stream")
async def agent_chat_stream(request: ChatRequest):
    """
    Streaming AI agent chat endpoint:
    Streams agent thoughts, tool executions, and final structured response over SSE.
    """
    async def chat_event_generator():
        try:
            async for event in agent_service.stream_agent_chat(request):
                yield {
                    "event": "message",
                    "data": json.dumps(event),
                }
        except Exception as e:
            logger.error(f"Agent stream error: {e}", exc_info=True)
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "message": str(e)}),
            }

    return EventSourceResponse(chat_event_generator())


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Operational health check and adapter configuration.
    """
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "scraper_mode": settings.SCRAPER_MODE,
        "amazon_base_url": settings.AMAZON_BASE_URL,
        "flipkart_base_url": settings.FLIPKART_BASE_URL,
        "weights": {
            "rating_confidence": settings.WEIGHT_RATING_CONFIDENCE,
            "price_value": settings.WEIGHT_PRICE_VALUE,
            "requirements": settings.WEIGHT_REQUIREMENTS,
            "availability": settings.WEIGHT_AVAILABILITY,
        },
        "bayesian_threshold": settings.BAYESIAN_MIN_REVIEWS,
        "bayesian_baseline_rating": settings.BAYESIAN_BASELINE_RATING,
    }


@router.get("/config")
async def get_config() -> Dict[str, Any]:
    """
    Returns current ranking weights, Bayesian parameters, and budget defaults.
    """
    return {
        "bayesian_min_reviews": settings.BAYESIAN_MIN_REVIEWS,
        "bayesian_baseline_rating": settings.BAYESIAN_BASELINE_RATING,
        "default_weights": {
            "rating": settings.WEIGHT_RATING_CONFIDENCE,
            "price": settings.WEIGHT_PRICE_VALUE,
            "requirements": settings.WEIGHT_REQUIREMENTS,
            "availability": settings.WEIGHT_AVAILABILITY,
        },
        "default_over_budget_allowance_pct": settings.DEFAULT_OVER_BUDGET_ALLOWANCE_PCT,
    }
