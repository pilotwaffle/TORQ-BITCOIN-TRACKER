"""
Trading Signals API endpoints for TBWI.

Provides actionable BULLISH/BEARISH/NEUTRAL signals from whale activity.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Query

from tbwi.api.deps import APIKey, DBSession
from tbwi.db.repository import TransactionRepository, WhaleEventRepository
from tbwi.logging import get_logger
from tbwi.models.schemas import (
    SignalDirection,
    SignalSeverity,
    TradingSignal,
)
from tbwi.services.signal_generator import SignalGenerator

logger = get_logger(__name__)
router = APIRouter()

# Global signal generator instance
_signal_generator = SignalGenerator()


@router.get("/signals", response_model=list[TradingSignal])
async def get_trading_signals(
    db: DBSession,
    api_key: APIKey,
    hours: int = Query(24, ge=1, le=168, description="Hours to look back"),
    direction: SignalDirection | None = Query(
        None, description="Filter by signal direction (BULLISH, BEARISH, NEUTRAL)"
    ),
    min_severity: SignalSeverity | None = Query(
        None, description="Minimum severity level"
    ),
    min_btc: float | None = Query(
        None, ge=0, description="Minimum BTC value"
    ),
    limit: int = Query(50, ge=1, le=200, description="Maximum signals to return"),
) -> list[TradingSignal]:
    """
    Get actionable trading signals from recent whale activity.

    Signals are derived from:
    - Exchange deposits (BEARISH - sell pressure)
    - Exchange withdrawals (BULLISH - accumulation)
    - Deposit bursts (VERY BEARISH - coordinated selling)
    - OTC moves (NEUTRAL - off-book)
    - Programmatic splits (NEUTRAL - institutional)

    Returns signals sorted by severity and recency.
    """
    since = datetime.utcnow() - timedelta(hours=hours)

    # Get recent transactions
    tx_repo = TransactionRepository(db)
    transactions = await tx_repo.get_recent(
        since=since,
        limit=1000,  # Get more to generate signals from
    )

    # Generate signals from transactions
    signals: list[TradingSignal] = []
    generator = SignalGenerator()

    for tx in transactions:
        signal = generator.generate_signal_from_transaction(tx)
        if signal:
            # Apply filters
            if direction and signal.signal != direction:
                continue
            if min_btc and signal.total_btc < min_btc:
                continue
            if min_severity:
                severity_order = {
                    SignalSeverity.LOW: 0,
                    SignalSeverity.MEDIUM: 1,
                    SignalSeverity.HIGH: 2,
                    SignalSeverity.CRITICAL: 3,
                }
                if severity_order.get(signal.severity, 0) < severity_order.get(min_severity, 0):
                    continue

            signals.append(signal)

    # Sort by severity (critical first) then by time (newest first)
    severity_order = {
        SignalSeverity.CRITICAL: 0,
        SignalSeverity.HIGH: 1,
        SignalSeverity.MEDIUM: 2,
        SignalSeverity.LOW: 3,
    }
    signals.sort(key=lambda s: (severity_order.get(s.severity, 4), -s.created_at.timestamp()))

    return signals[:limit]


@router.get("/signals/summary")
async def get_signal_summary(
    db: DBSession,
    api_key: APIKey,
    hours: int = Query(24, ge=1, le=168, description="Hours to look back"),
) -> dict:
    """
    Get a summary of trading signals for the time period.

    Returns aggregated signal counts and net direction.
    """
    since = datetime.utcnow() - timedelta(hours=hours)

    tx_repo = TransactionRepository(db)
    transactions = await tx_repo.get_recent(since=since, limit=1000)

    generator = SignalGenerator()

    # Count signals by direction and severity
    bullish_count = 0
    bearish_count = 0
    neutral_count = 0
    bullish_btc = 0.0
    bearish_btc = 0.0
    critical_signals = []

    for tx in transactions:
        signal = generator.generate_signal_from_transaction(tx)
        if signal:
            if signal.signal == SignalDirection.BULLISH:
                bullish_count += 1
                bullish_btc += signal.total_btc
            elif signal.signal == SignalDirection.BEARISH:
                bearish_count += 1
                bearish_btc += signal.total_btc
            else:
                neutral_count += 1

            if signal.severity == SignalSeverity.CRITICAL:
                critical_signals.append({
                    "summary": signal.summary,
                    "direction": signal.signal.value,
                    "btc": signal.total_btc,
                })

    # Calculate net sentiment
    total_directional = bullish_count + bearish_count
    if total_directional == 0:
        net_sentiment = "NEUTRAL"
        sentiment_score = 0.5
    else:
        bullish_ratio = bullish_count / total_directional
        if bullish_ratio > 0.6:
            net_sentiment = "BULLISH"
        elif bullish_ratio < 0.4:
            net_sentiment = "BEARISH"
        else:
            net_sentiment = "MIXED"
        sentiment_score = bullish_ratio

    # BTC-weighted sentiment
    total_btc = bullish_btc + bearish_btc
    if total_btc > 0:
        btc_weighted_sentiment = bullish_btc / total_btc
    else:
        btc_weighted_sentiment = 0.5

    return {
        "period_hours": hours,
        "net_sentiment": net_sentiment,
        "sentiment_score": round(sentiment_score, 2),
        "btc_weighted_sentiment": round(btc_weighted_sentiment, 2),
        "signal_counts": {
            "bullish": bullish_count,
            "bearish": bearish_count,
            "neutral": neutral_count,
            "total": bullish_count + bearish_count + neutral_count,
        },
        "btc_volume": {
            "bullish_btc": round(bullish_btc, 2),
            "bearish_btc": round(bearish_btc, 2),
            "net_btc": round(bullish_btc - bearish_btc, 2),
        },
        "critical_alerts": critical_signals[:5],  # Top 5 critical
        "interpretation": _generate_summary_interpretation(
            net_sentiment, bullish_btc, bearish_btc, len(critical_signals)
        ),
    }


@router.get("/signals/latest", response_model=TradingSignal | None)
async def get_latest_signal(
    db: DBSession,
    api_key: APIKey,
    direction: SignalDirection | None = Query(
        None, description="Filter by direction"
    ),
    min_severity: SignalSeverity | None = Query(
        SignalSeverity.MEDIUM, description="Minimum severity"
    ),
) -> TradingSignal | None:
    """
    Get the most recent significant trading signal.

    Useful for quick dashboard status checks.
    """
    since = datetime.utcnow() - timedelta(hours=6)

    tx_repo = TransactionRepository(db)
    transactions = await tx_repo.get_recent(since=since, limit=100)

    generator = SignalGenerator()
    severity_order = {
        SignalSeverity.LOW: 0,
        SignalSeverity.MEDIUM: 1,
        SignalSeverity.HIGH: 2,
        SignalSeverity.CRITICAL: 3,
    }

    best_signal: TradingSignal | None = None
    best_severity = -1

    for tx in transactions:
        signal = generator.generate_signal_from_transaction(tx)
        if signal:
            if direction and signal.signal != direction:
                continue
            if min_severity:
                if severity_order.get(signal.severity, 0) < severity_order.get(min_severity, 0):
                    continue

            sig_severity = severity_order.get(signal.severity, 0)
            if sig_severity > best_severity:
                best_signal = signal
                best_severity = sig_severity

    return best_signal


def _generate_summary_interpretation(
    sentiment: str, bullish_btc: float, bearish_btc: float, critical_count: int
) -> str:
    """Generate human-readable interpretation of signal summary."""
    if critical_count > 0:
        prefix = f"ALERT: {critical_count} critical signal(s) detected. "
    else:
        prefix = ""

    net_btc = bullish_btc - bearish_btc

    if sentiment == "BULLISH":
        return (
            f"{prefix}Net bullish sentiment. {net_btc:,.0f} BTC more withdrawn "
            "than deposited to exchanges. Supply leaving exchanges supports price."
        )
    elif sentiment == "BEARISH":
        return (
            f"{prefix}Net bearish sentiment. {-net_btc:,.0f} BTC more deposited "
            "to exchanges than withdrawn. Potential sell pressure building."
        )
    elif sentiment == "MIXED":
        return (
            f"{prefix}Mixed signals. Roughly balanced exchange flows. "
            "No clear directional bias from whale activity."
        )
    else:
        return (
            f"{prefix}Neutral/low activity period. "
            "Insufficient directional signals to determine sentiment."
        )
