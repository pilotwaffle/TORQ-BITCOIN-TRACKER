"""
Health check endpoints for TBWI API.
"""

from datetime import datetime

from fastapi import APIRouter, Response

from tbwi import __version__
from tbwi.config import get_settings
from tbwi.db.session import get_db_session
from tbwi.logging import get_logger
from tbwi.models.schemas import HealthStatus
from tbwi.services.message_queue import get_message_queue
from tbwi.services.bitcoin_rpc import get_rpc_client

logger = get_logger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthStatus)
async def health_check() -> HealthStatus:
    """
    Health check endpoint.

    Returns the status of the API and its dependencies.
    """
    db_status = "unknown"
    redis_status = "unknown"
    zmq_status = "unknown"

    # Check database
    try:
        async with get_db_session() as session:
            await session.execute("SELECT 1")
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
        logger.warning("Database health check failed", error=str(e))

    # Check Redis
    try:
        mq = await get_message_queue()
        if await mq.health_check():
            redis_status = "healthy"
        else:
            redis_status = "unhealthy"
    except Exception as e:
        redis_status = f"unhealthy: {str(e)}"
        logger.warning("Redis health check failed", error=str(e))

    # Check Bitcoin Core RPC
    try:
        rpc = get_rpc_client()
        if await rpc.test_connection():
            zmq_status = "healthy"
        else:
            zmq_status = "unhealthy"
    except Exception as e:
        zmq_status = f"unavailable: {str(e)}"
        # This is not critical - ZMQ listener handles Bitcoin Core

    overall_status = "healthy"
    if "unhealthy" in db_status or "unhealthy" in redis_status:
        overall_status = "degraded"

    return HealthStatus(
        status=overall_status,
        version=__version__,
        database=db_status,
        redis=redis_status,
        zmq=zmq_status,
        timestamp=datetime.utcnow(),
    )


@router.get("/health/live")
async def liveness_probe() -> dict:
    """
    Kubernetes liveness probe endpoint.

    Returns 200 if the service is running.
    """
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness_probe(response: Response) -> dict:
    """
    Kubernetes readiness probe endpoint.

    Returns 200 if the service is ready to accept traffic.
    """
    try:
        # Check database connection
        async with get_db_session() as session:
            await session.execute("SELECT 1")
        return {"status": "ready"}
    except Exception as e:
        response.status_code = 503
        return {"status": "not_ready", "error": str(e)}
