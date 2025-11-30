# TBWI - Torq Bitcoin Whale Intelligence
# Multi-stage Dockerfile for all services

FROM python:3.11-slim as base

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

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --upgrade pip setuptools wheel && \
    pip install -e .

# Copy application code
COPY src/ ./src/

# Change ownership to app user
RUN chown -R app:app /app

USER app

# Default command (can be overridden)
CMD ["python", "-m", "tbwi.api.main"]

# -----------------------------------------------------------------------------
# Service-specific targets
# -----------------------------------------------------------------------------

FROM base as api
ENV SERVICE=api
CMD ["python", "-m", "tbwi.api.main"]

FROM base as zmq-listener
ENV SERVICE=zmq-listener
CMD ["python", "-m", "tbwi.services.zmq_listener"]

FROM base as classifier
ENV SERVICE=classifier
CMD ["python", "-m", "tbwi.services.classifier"]

FROM base as event-engine
ENV SERVICE=event-engine
CMD ["python", "-m", "tbwi.services.event_engine"]

FROM base as webhook-dispatcher
ENV SERVICE=webhook-dispatcher
CMD ["python", "-m", "tbwi.services.webhook_dispatcher"]
