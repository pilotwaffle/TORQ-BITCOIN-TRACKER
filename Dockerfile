# TBWI - Torq Bitcoin Whale Intelligence
# Multi-stage Dockerfile for all services

FROM python:3.11-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN useradd --create-home --shell /bin/bash app

WORKDIR /app

# Copy application code first (needed for pip install -e .)
COPY pyproject.toml ./
COPY src/ ./src/

# Install Python dependencies
RUN pip install --upgrade pip setuptools wheel && \
    pip install -e .

# Change ownership to app user
RUN chown -R app:app /app

USER app

# Default command (can be overridden)
CMD ["python", "-m", "tbwi.api.main"]

# -----------------------------------------------------------------------------
# Service-specific targets
# -----------------------------------------------------------------------------

FROM base AS api
ENV SERVICE=api
CMD ["python", "-m", "tbwi.api.main"]

FROM base AS zmq-listener
ENV SERVICE=zmq-listener
CMD ["python", "-m", "tbwi.services.zmq_listener"]

FROM base AS mempool-listener
ENV SERVICE=mempool-listener
CMD ["python", "-m", "tbwi.services.mempool_listener"]

FROM base AS classifier
ENV SERVICE=classifier
CMD ["python", "-m", "tbwi.services.classifier"]

FROM base AS event-engine
ENV SERVICE=event-engine
CMD ["python", "-m", "tbwi.services.event_engine"]

FROM base AS webhook-dispatcher
ENV SERVICE=webhook-dispatcher
CMD ["python", "-m", "tbwi.services.webhook_dispatcher"]
