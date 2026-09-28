import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration loaded from environment variables or .env file.
    All weights and thresholds are fully configurable.
    """
    APP_NAME: str = "Product Finder API"
    APP_ENV: str = "development"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:5500",
        "*"
    ]

    # Scraper runtime mode:
    # "live": strictly live HTTP requests to marketplaces
    # "hybrid": attempts live scraping first; falls back to curated high-fidelity catalog if blocked by WAF/CAPTCHA
    # "mock": deterministic candidate catalog for tests and offline usage
    SCRAPER_MODE: str = "hybrid"
    REQUEST_TIMEOUT_SECONDS: float = 12.0
    MAX_RESULTS_PER_MARKETPLACE: int = 40
    # Optional: ScraperAPI key for residential IP proxying (bypasses Amazon/Flipkart bot protection)
    # Get free key at https://www.scraperapi.com — 1000 free requests/month
    SCRAPERAPI_KEY: str = ""
    AMAZON_BASE_URL: str = "https://www.amazon.in"
    FLIPKART_BASE_URL: str = "https://www.flipkart.com"

    # Bayesian rating confidence defaults
    BAYESIAN_MIN_REVIEWS: int = 50
    BAYESIAN_BASELINE_RATING: float = 4.0

    # Default ranking weights (normalized dynamically if user overrides)
    WEIGHT_RATING_CONFIDENCE: float = 0.40
    WEIGHT_PRICE_VALUE: float = 0.30
    WEIGHT_REQUIREMENTS: float = 0.20
    WEIGHT_AVAILABILITY: float = 0.10

    # Budget settings
    DEFAULT_OVER_BUDGET_ALLOWANCE_PCT: float = 10.0

    # Rate limiting
    RATE_LIMIT_SEARCH: str = "30/minute"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
