import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import logging

from backend.app.config import settings
from backend.app.api.routes import router as api_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("product_finder")

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.APP_NAME} in mode '{settings.SCRAPER_MODE}'...")
    logger.info(f"Bayesian Threshold: {settings.BAYESIAN_MIN_REVIEWS}, Baseline: {settings.BAYESIAN_BASELINE_RATING}")
    yield
    logger.info(f"Shutting down {settings.APP_NAME}...")


app = FastAPI(
    title=settings.APP_NAME,
    description="Full-Stack Product Research Engine for Amazon India & Flipkart India with Bayesian Confidence Ranking",
    version="1.0.0",
    lifespan=lifespan,
)

# Attach rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routes (mounted both at /api and root to support standard and serverless environments)
app.include_router(api_router, prefix="/api")
app.include_router(api_router, prefix="")

# Mount frontend static files if directory exists
frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if not frontend_dir.exists():
    frontend_dir = Path(__file__).resolve().parent.parent.parent / "public"

if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        index_file = frontend_dir / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return {"message": f"{settings.APP_NAME} is running. Frontend index.html not found."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
