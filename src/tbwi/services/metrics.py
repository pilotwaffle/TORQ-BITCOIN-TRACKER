"""
Prometheus metrics for TBWI.

Provides metrics collection and exposition for monitoring.
"""

from __future__ import annotations

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Info,
    start_http_server,
    REGISTRY,
    CollectorRegistry,
)

from tbwi.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Application Info
# =============================================================================

APP_INFO = Info("tbwi", "TBWI application information")
APP_INFO.info({
    "version": "1.0.0",
    "service": "tbwi",
})


# =============================================================================
# ZMQ Listener Metrics
# =============================================================================

ZMQ_CONNECTION_STATUS = Gauge(
    "tbwi_zmq_connection_status",
    "ZMQ connection status (1=connected, 0=disconnected)",
    ["endpoint"],
)

ZMQ_MESSAGES_RECEIVED = Counter(
    "tbwi_zmq_messages_received_total",
    "Total ZMQ messages received",
    ["topic"],
)

ZMQ_MESSAGES_MISSED = Counter(
    "tbwi_zmq_messages_missed_total",
    "Total ZMQ messages missed (detected via sequence numbers)",
    ["topic"],
)


# =============================================================================
# Transaction Processing Metrics
# =============================================================================

TX_PROCESSED = Counter(
    "tbwi_transactions_processed_total",
    "Total transactions processed from ZMQ stream",
)

TX_FILTERED = Counter(
    "tbwi_transactions_filtered_total",
    "Transactions that passed the minimum threshold filter",
)

TX_PARSE_ERRORS = Counter(
    "tbwi_transaction_parse_errors_total",
    "Transaction parsing errors",
)

TX_PROCESSING_TIME = Histogram(
    "tbwi_transaction_processing_seconds",
    "Time to parse and process a transaction",
    buckets=(0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)


# =============================================================================
# Classification Metrics
# =============================================================================

TX_CLASSIFIED = Counter(
    "tbwi_transactions_classified_total",
    "Total transactions classified",
    ["primary_type"],
)

TX_CLASSIFICATION_TIME = Histogram(
    "tbwi_transaction_classification_seconds",
    "Time to classify and enrich a transaction",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
)


# =============================================================================
# Whale Event Metrics
# =============================================================================

WHALE_EVENTS_CREATED = Counter(
    "tbwi_whale_events_created_total",
    "Total whale events created",
    ["event_type"],
)

WHALE_EVENT_VALUE_BTC = Histogram(
    "tbwi_whale_event_value_btc",
    "Value of whale events in BTC",
    buckets=(100, 500, 1000, 5000, 10000, 50000, 100000),
)

WHALE_EVENT_TX_COUNT = Histogram(
    "tbwi_whale_event_transaction_count",
    "Number of transactions per whale event",
    buckets=(1, 2, 5, 10, 20, 50, 100),
)

EVENT_LATENCY = Histogram(
    "tbwi_event_latency_seconds",
    "Time from transaction seen to event creation",
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)


# =============================================================================
# Webhook Metrics
# =============================================================================

WEBHOOK_DELIVERIES = Counter(
    "tbwi_webhook_deliveries_total",
    "Total webhook delivery attempts",
    ["status"],
)

WEBHOOK_DELIVERY_TIME = Histogram(
    "tbwi_webhook_delivery_seconds",
    "Webhook delivery time",
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)

WEBHOOK_RETRIES = Counter(
    "tbwi_webhook_retries_total",
    "Total webhook retry attempts",
)


# =============================================================================
# Database Metrics
# =============================================================================

DB_CONNECTIONS_ACTIVE = Gauge(
    "tbwi_db_connections_active",
    "Active database connections",
)

DB_QUERY_TIME = Histogram(
    "tbwi_db_query_seconds",
    "Database query time",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)


# =============================================================================
# Redis/Message Queue Metrics
# =============================================================================

MQ_MESSAGES_PUBLISHED = Counter(
    "tbwi_mq_messages_published_total",
    "Total messages published to message queue",
    ["channel"],
)

MQ_MESSAGES_CONSUMED = Counter(
    "tbwi_mq_messages_consumed_total",
    "Total messages consumed from message queue",
    ["channel"],
)

MQ_CONSUMER_LAG = Gauge(
    "tbwi_mq_consumer_lag",
    "Message queue consumer lag (pending messages)",
    ["channel", "consumer_group"],
)


# =============================================================================
# Price Oracle Metrics
# =============================================================================

PRICE_FETCH_TIME = Histogram(
    "tbwi_price_fetch_seconds",
    "Time to fetch BTC price",
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0),
)

PRICE_FETCH_ERRORS = Counter(
    "tbwi_price_fetch_errors_total",
    "Price fetch errors",
    ["source"],
)

CURRENT_BTC_PRICE = Gauge(
    "tbwi_current_btc_price_usd",
    "Current BTC price in USD",
)


# =============================================================================
# Entity Tag Metrics
# =============================================================================

ENTITY_TAGS_TOTAL = Gauge(
    "tbwi_entity_tags_total",
    "Total entity tags in database",
    ["category"],
)

ENTITY_TAG_LOOKUPS = Counter(
    "tbwi_entity_tag_lookups_total",
    "Entity tag lookups",
    ["result"],  # hit, miss
)


# =============================================================================
# API Metrics
# =============================================================================

API_REQUESTS = Counter(
    "tbwi_api_requests_total",
    "Total API requests",
    ["method", "endpoint", "status"],
)

API_REQUEST_TIME = Histogram(
    "tbwi_api_request_seconds",
    "API request processing time",
    ["method", "endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
)

API_ACTIVE_CONNECTIONS = Gauge(
    "tbwi_api_active_connections",
    "Active API connections",
)

WEBSOCKET_CONNECTIONS = Gauge(
    "tbwi_websocket_connections",
    "Active WebSocket connections",
)


# =============================================================================
# Anomaly Detection Metrics
# =============================================================================

ANOMALIES_DETECTED = Counter(
    "tbwi_anomalies_detected_total",
    "Total anomalies detected",
    ["anomaly_type"],
)


# =============================================================================
# Metrics Server
# =============================================================================

_metrics_server_started = False


def start_metrics_server(port: int = 9090, addr: str = "0.0.0.0") -> None:
    """
    Start the Prometheus metrics HTTP server.

    Args:
        port: Port to listen on (default: 9090)
        addr: Address to bind to (default: 0.0.0.0)
    """
    global _metrics_server_started
    if _metrics_server_started:
        logger.warning("Metrics server already started")
        return

    try:
        start_http_server(port, addr)
        _metrics_server_started = True
        logger.info("Prometheus metrics server started", port=port, addr=addr)
    except Exception as e:
        logger.error("Failed to start metrics server", error=str(e))


def get_metrics_registry() -> CollectorRegistry:
    """Get the default metrics registry."""
    return REGISTRY
