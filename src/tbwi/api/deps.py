"""
API dependencies for TBWI.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from tbwi.config import get_settings
from tbwi.db.session import get_db

# API Key security (optional)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
) -> str | None:
    """
    Verify API key if configured.

    Returns the API key if valid, or None if no key is required.
    """
    settings = get_settings()

    # If no API key is configured, allow all requests
    if not settings.api.api_key:
        return None

    # If API key is required but not provided
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Verify the key
    if api_key != settings.api.api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return api_key


# Type aliases for dependency injection
DBSession = Annotated[AsyncSession, Depends(get_db)]
APIKey = Annotated[str | None, Depends(verify_api_key)]
