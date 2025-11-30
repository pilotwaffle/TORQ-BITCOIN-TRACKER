"""
FastAPI application for TBWI.

Provides REST API for querying whale events, transactions, and entity tags.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tbwi import __version__
from tbwi.api.routes import entities, events, health, streaming, transactions
from tbwi.config import get_settings
from tbwi.db.session import close_db, init_db
from tbwi.logging import get_logger, setup_logging
from tbwi.services.bitcoin_rpc import close_rpc_client
from tbwi.services.message_queue import close_message_queue, get_message_queue

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    settings = get_settings()
    setup_logging(settings.log_level, json_output=settings.environment != "development")

    logger.info("Starting TBWI API", version=__version__)

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Connect to message queue
    try:
        await get_message_queue()
        logger.info("Message queue connected")
    except Exception as e:
        logger.warning("Message queue connection failed (non-fatal)", error=str(e))

    yield

    # Cleanup
    logger.info("Shutting down TBWI API")
    await close_message_queue()
    await close_rpc_client()
    await close_db()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Torq Bitcoin Whale Intelligence API",
        description="Real-time Bitcoin mempool streaming and whale activity detection",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health.router, tags=["Health"])
    app.include_router(events.router, prefix="/api/v1", tags=["Whale Events"])
    app.include_router(transactions.router, prefix="/api/v1", tags=["Transactions"])
    app.include_router(entities.router, prefix="/api/v1", tags=["Entity Tags"])
    app.include_router(streaming.router, prefix="/api/v1", tags=["Streaming"])

    return app


# Create the app instance
app = create_app()


def main() -> None:
    """Main entry point for the API server."""
    settings = get_settings()
    setup_logging(settings.log_level, json_output=settings.environment != "development")

    logger.info(
        "Starting TBWI API Server",
        host=settings.api.host,
        port=settings.api.port,
    )

    uvicorn.run(
        "tbwi.api.main:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.environment == "development",
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
