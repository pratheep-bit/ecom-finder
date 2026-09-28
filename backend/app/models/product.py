from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator


class Marketplace(str, Enum):
    AMAZON = "Amazon"
    FLIPKART = "Flipkart"


class RequirementStatus(str, Enum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    UNKNOWN = "unknown"


class RequirementMatchResult(BaseModel):
    requirement: str
    status: RequirementStatus
    matched_token: Optional[str] = None
    confidence: float = 0.0


class MarketplaceOffer(BaseModel):
    """
    Represents an offer for a product found on a specific marketplace.
    """
    marketplace: Marketplace
    product_id: Optional[str] = None  # ASIN or Flipkart PID
    title: str
    price: float
    original_price: Optional[float] = None
    discount_pct: Optional[float] = None
    rating: float = Field(ge=0.0, le=5.0)
    review_count: int = Field(ge=0)
    url: str
    image_url: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    availability: str = "In Stock"
    specifications: List[str] = Field(default_factory=list)
    scraped_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ScoringBreakdown(BaseModel):
    """
    Transparent scoring breakdown detailing the Bayesian rating,
    review confidence, price/value, requirement matching, and overall score.
    """
    raw_rating: float
    review_count: int
    bayesian_rating: float
    review_confidence_score: float  # 0.0 - 100.0%
    price_value_score: float        # 0.0 - 100.0
    requirement_match_score: float  # 0.0 - 100.0
    availability_score: float       # 0.0 - 100.0
    overall_score: float            # 0.0 - 100.0 (weighted composite)


class UnifiedProduct(BaseModel):
    """
    Unified product entity created after cross-marketplace deduplication and normalization.
    Contains offers from Amazon, Flipkart, or both.
    """
    id: str
    rank: Optional[int] = None
    name: str
    brand: str
    model: Optional[str] = None
    normalized_title: str
    image_url: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    best_price: float
    original_price: Optional[float] = None
    discount_pct: Optional[float] = None
    rating: float
    review_count: int
    primary_marketplace: Marketplace
    availability: str = "In Stock"
    amazon_offer: Optional[MarketplaceOffer] = None
    flipkart_offer: Optional[MarketplaceOffer] = None
    best_observed_deal: str = ""
    key_specifications: List[str] = Field(default_factory=list)
    matched_requirements: List[RequirementMatchResult] = Field(default_factory=list)
    scoring: ScoringBreakdown
    scraped_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MarketplaceStatus(BaseModel):
    marketplace: Marketplace
    status: str  # "ok", "unavailable", "rate_limited", "fallback_used"
    count: int = 0
    message: Optional[str] = None
    latency_ms: Optional[float] = None


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=150, description="Product search term")
    min_price: Optional[float] = Field(None, ge=0.0, description="Minimum price threshold in INR")
    max_price: Optional[float] = Field(None, ge=1.0, description="Budget cap in INR")
    min_rating: Optional[float] = Field(0.0, ge=0.0, le=5.0, description="Minimum star rating filter")
    requirements: List[str] = Field(default_factory=list, description="Target features or specifications")
    allow_over_budget: bool = Field(False, description="Allow slight overrun over maximum price")
    over_budget_pct: float = Field(10.0, ge=0.0, le=50.0, description="Allowed buffer % when over-budget is enabled")

    # Optional custom weights for transparency and customization
    weight_rating: Optional[float] = None
    weight_price: Optional[float] = None
    weight_requirements: Optional[float] = None
    weight_availability: Optional[float] = None

    @field_validator("requirements", mode="before")
    @classmethod
    def clean_requirements(cls, v):
        if isinstance(v, str):
            # Split comma-separated string if provided as single string
            return [x.strip() for x in v.split(",") if x.strip()]
        if isinstance(v, list):
            cleaned = []
            for item in v:
                if isinstance(item, str):
                    for sub in item.split(","):
                        if sub.strip():
                            cleaned.append(sub.strip())
            return cleaned
        return []


class SearchResponse(BaseModel):
    query: str
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_rating: float = 0.0
    requirements: List[str] = Field(default_factory=list)
    analyzed_count: int
    amazon_count: int
    flipkart_count: int
    deduplicated_count: int
    marketplaces_status: List[MarketplaceStatus] = Field(default_factory=list)
    top_5: List[UnifiedProduct] = Field(default_factory=list)
    all_ranked: List[UnifiedProduct] = Field(default_factory=list)
    execution_time_seconds: float
    execution_time_ms: float = 0.0
    scraped_at: str


class ChatMessage(BaseModel):
    role: str  # "user", "assistant", "system"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = Field(default_factory=list)
    conversation_id: Optional[str] = None
    max_price: Optional[float] = None
    min_rating: Optional[float] = None


class ChatResponse(BaseModel):
    reply: str
    search_params: Dict[str, Any] = Field(default_factory=dict)
    search_result: Optional[SearchResponse] = None
    tool_steps: List[str] = Field(default_factory=list)
    suggested_followups: List[str] = Field(default_factory=list)
