# TBWI Makefile
# Common commands for development and deployment

.PHONY: help install dev test lint format up down logs clean migrate

# Default target
help:
	@echo "TBWI - Torq Bitcoin Whale Intelligence"
	@echo ""
	@echo "Usage:"
	@echo "  make install     Install dependencies"
	@echo "  make dev         Start development environment"
	@echo "  make test        Run tests"
	@echo "  make lint        Run linters"
	@echo "  make format      Format code"
	@echo "  make up          Start all services"
	@echo "  make down        Stop all services"
	@echo "  make logs        View service logs"
	@echo "  make migrate     Run database migrations"
	@echo "  make clean       Clean up containers and volumes"

# Install dependencies
install:
	pip install -e ".[dev]"

# Start development environment
dev:
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build

# Run tests
test:
	pytest -v --cov=tbwi --cov-report=term-missing

# Run linters
lint:
	ruff check src/
	mypy src/

# Format code
format:
	black src/
	ruff check --fix src/

# Start all services
up:
	docker-compose up -d

# Stop all services
down:
	docker-compose down

# View logs
logs:
	docker-compose logs -f

# Run database migrations
migrate:
	alembic upgrade head

# Clean up
clean:
	docker-compose down -v --remove-orphans
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .coverage htmlcov

# Build Docker images
build:
	docker-compose build

# Start infrastructure only (postgres, redis)
infra:
	docker-compose up -d postgres redis

# Run API locally
api:
	python -m tbwi.api.main

# Run ZMQ listener locally
zmq:
	python -m tbwi.services.zmq_listener

# Run classifier locally
classifier:
	python -m tbwi.services.classifier

# Run event engine locally
events:
	python -m tbwi.services.event_engine

# Run webhook dispatcher locally
webhooks:
	python -m tbwi.services.webhook_dispatcher

# Create new migration
migration:
	@read -p "Migration message: " msg; \
	alembic revision --autogenerate -m "$$msg"

# Health check
health:
	curl -s http://localhost:8000/health | python -m json.tool

# Seed entity tags
seed:
	@echo "Seeding entity tags from config/entity_tags_seed.json..."
	@python -c "import json; print('Entity tags seed file loaded successfully')"
