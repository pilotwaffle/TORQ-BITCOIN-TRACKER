"""
Entity tag endpoints for TBWI API.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from tbwi.api.deps import APIKey, DBSession
from tbwi.db.repository import EntityTagRepository
from tbwi.logging import get_logger
from tbwi.models.schemas import EntityCategory, EntityTag, EntityTagCreate

logger = get_logger(__name__)
router = APIRouter()


@router.get("/entity-tags", response_model=list[EntityTag])
async def get_entity_tags(
    db: DBSession,
    api_key: APIKey,
    category: EntityCategory | None = Query(
        None, description="Filter by entity category"
    ),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of tags"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> list[EntityTag]:
    """
    Get entity tags with optional filtering.
    """
    repo = EntityTagRepository(db)
    return await repo.list_all(
        category=category.value if category else None,
        limit=limit,
        offset=offset,
    )


@router.get("/entity-tags/{address}", response_model=EntityTag)
async def get_entity_tag(
    address: str,
    db: DBSession,
    api_key: APIKey,
) -> EntityTag:
    """
    Get entity tag for a specific address.
    """
    repo = EntityTagRepository(db)
    tag = await repo.get_by_address(address)

    if tag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No entity tag found for address {address}",
        )

    return tag


@router.post("/entity-tags", response_model=EntityTag, status_code=status.HTTP_201_CREATED)
async def create_entity_tag(
    tag: EntityTagCreate,
    db: DBSession,
    api_key: APIKey,
) -> EntityTag:
    """
    Create or update an entity tag.

    If a tag already exists for the address, it will be updated.
    """
    repo = EntityTagRepository(db)
    return await repo.upsert(tag)


@router.get("/entity-tags/by-label/{label}", response_model=list[EntityTag])
async def get_entity_tags_by_label(
    label: str,
    db: DBSession,
    api_key: APIKey,
) -> list[EntityTag]:
    """
    Get all entity tags for a specific label (e.g., 'Binance').
    """
    repo = EntityTagRepository(db)
    tags = await repo.get_by_label(label)

    if not tags:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No entity tags found for label '{label}'",
        )

    return tags


@router.get("/entity-tags/lookup")
async def lookup_addresses(
    db: DBSession,
    api_key: APIKey,
    addresses: str = Query(
        ..., description="Comma-separated list of addresses to lookup"
    ),
) -> dict:
    """
    Lookup entity tags for multiple addresses.

    Returns a mapping of address -> entity info for known addresses.
    """
    address_list = [a.strip() for a in addresses.split(",") if a.strip()]

    if len(address_list) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 100 addresses per request",
        )

    repo = EntityTagRepository(db)
    tags = await repo.get_by_addresses(address_list)

    return {
        "found": len(tags),
        "total_requested": len(address_list),
        "entities": {
            addr: {
                "label": tag.label,
                "category": tag.category.value if hasattr(tag.category, 'value') else tag.category,
                "confidence": tag.confidence,
            }
            for addr, tag in tags.items()
        },
    }
