"""
Transaction endpoints for TBWI API.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status

from tbwi.api.deps import APIKey, DBSession
from tbwi.db.repository import TransactionRepository
from tbwi.logging import get_logger
from tbwi.models.schemas import ClassifiedTransaction, TransactionType

logger = get_logger(__name__)
router = APIRouter()


@router.get("/transactions/{txid}", response_model=ClassifiedTransaction)
async def get_transaction(
    txid: str,
    db: DBSession,
    api_key: APIKey,
) -> ClassifiedTransaction:
    """
    Get a classified transaction by txid.
    """
    repo = TransactionRepository(db)
    tx = await repo.get_by_txid(txid)

    if tx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction {txid} not found",
        )

    return tx


@router.get("/transactions", response_model=list[ClassifiedTransaction])
async def get_transactions(
    db: DBSession,
    api_key: APIKey,
    since: datetime | None = Query(
        None, description="Filter transactions since this timestamp"
    ),
    primary_type: TransactionType | None = Query(
        None, description="Filter by primary transaction type"
    ),
    network: str | None = Query(
        None, description="Filter by network (mainnet, testnet, regtest)"
    ),
    min_value_btc: float | None = Query(
        None, ge=0, description="Minimum transaction value in BTC"
    ),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of transactions"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> list[ClassifiedTransaction]:
    """
    Get classified transactions with optional filtering.

    Returns a list of classified transactions sorted by seen_at (newest first).
    """
    repo = TransactionRepository(db)

    transactions = await repo.get_recent(
        network=network,
        primary_type=primary_type.value if primary_type else None,
        since=since,
        limit=limit,
        offset=offset,
    )

    # Apply min_value filter if specified (post-query)
    if min_value_btc is not None:
        transactions = [
            tx for tx in transactions if tx.total_value_out_btc >= min_value_btc
        ]

    return transactions


@router.get("/transactions/stats/recent")
async def get_transaction_stats(
    db: DBSession,
    api_key: APIKey,
    hours: int = Query(24, ge=1, le=168, description="Hours to look back"),
    network: str | None = Query(None, description="Filter by network"),
) -> dict:
    """
    Get statistics for recent classified transactions.
    """
    from datetime import timedelta

    repo = TransactionRepository(db)
    since = datetime.utcnow() - timedelta(hours=hours)

    transactions = await repo.get_recent(
        network=network,
        since=since,
        limit=10000,  # Get all for stats
    )

    if not transactions:
        return {
            "period_hours": hours,
            "network": network or "all",
            "total_transactions": 0,
            "total_btc": 0,
            "total_usd": None,
            "by_type": {},
        }

    total_btc = sum(tx.total_value_out_btc for tx in transactions)
    total_usd = sum(tx.total_value_usd or 0 for tx in transactions)

    by_type = {}
    for tx in transactions:
        tx_type = tx.primary_type.value
        if tx_type not in by_type:
            by_type[tx_type] = {"count": 0, "total_btc": 0}
        by_type[tx_type]["count"] += 1
        by_type[tx_type]["total_btc"] += tx.total_value_out_btc

    return {
        "period_hours": hours,
        "network": network or "all",
        "total_transactions": len(transactions),
        "total_btc": total_btc,
        "total_usd": total_usd if total_usd > 0 else None,
        "by_type": by_type,
    }
