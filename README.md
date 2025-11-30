# Torq Bitcoin Whale Intelligence (TBWI)

A production-grade system for streaming live Bitcoin transactions, detecting whale activity, and exposing signals via API and webhooks.

## Overview

TBWI provides real-time intelligence on significant Bitcoin blockchain activity:

- **Stream** live Bitcoin mempool transactions from Bitcoin Core via ZMQ
- **Classify** transactions by type (exchange deposits, withdrawals, OTC moves)
- **Cluster** transactions into meaningful whale events
- **Alert** AI trading agents and analytics systems via REST API and webhooks

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Bitcoin Core   │────▶│  ZMQ Listener   │────▶│    Classifier   │
│    (testnet)    │     │                 │     │                 │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                              ┌──────────────────────────┘
                              ▼
                        ┌─────────────────┐     ┌─────────────────┐
                        │  Event Engine   │────▶│    Webhook      │
                        │  (Clustering)   │     │   Dispatcher    │
                        └────────┬────────┘     └─────────────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │   REST API      │────▶ AI Agents / n8n
                        │   (FastAPI)     │
                        └─────────────────┘
```

## Features

### Transaction Classification
- **Exchange Deposit Candidate**: Large transactions to known exchange addresses
- **Exchange Withdrawal Candidate**: Large transactions from exchange addresses
- **OTC-Like Move**: Large single-output transactions to unknown addresses

### Whale Events
- **WH_EXCHANGE_SINGLE_DEPOSIT**: Single massive deposit (≥1000 BTC default)
- **WH_EXCHANGE_DEPOSIT_BURST**: Multiple deposits in short time window
- **WH_EXCHANGE_BULK_OUTFLOW**: Multiple withdrawals indicating accumulation
- **WH_OTC_LARGE_MOVE**: Large OTC-style transfers

### API Endpoints
- `GET /api/v1/whale-events` - Query whale events with filtering
- `GET /api/v1/whale-events/{id}` - Get specific event details
- `GET /api/v1/transactions/{txid}` - Get classified transaction
- `POST /api/v1/entity-tags` - Add/update entity tags
- `GET /agent/whale_events/latest` - Agent-optimized endpoint

## Quick Start

### Prerequisites
- Docker and Docker Compose
- 50GB+ disk space for Bitcoin testnet data

### 1. Clone and Configure

```bash
git clone https://github.com/torq/tbwi.git
cd tbwi

# Copy environment template
cp .env.example .env

# Edit configuration as needed
nano .env
```

### 2. Start Services

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Check health
curl http://localhost:8000/health
```

### 3. Wait for Bitcoin Sync

The Bitcoin Core node needs to sync with the testnet. Monitor progress:

```bash
docker-compose logs -f bitcoin-core
```

### 4. Access the API

Once running, access the API documentation:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Configuration

### Environment Variables

Key configuration options (see `.env.example` for full list):

| Variable | Default | Description |
|----------|---------|-------------|
| `BITCOIN_NETWORK` | `testnet` | Network: mainnet, testnet, regtest |
| `MIN_TX_THRESHOLD_BTC` | `10` | Minimum BTC to process |
| `LARGE_TX_THRESHOLD_BTC` | `50` | Large transaction threshold |
| `SINGLE_DEPOSIT_THRESHOLD_BTC` | `1000` | Single deposit event threshold |
| `WEBHOOK_URLS` | | Comma-separated webhook URLs |
| `API_API_KEY` | | API key for authentication |

### YAML Configuration

Additional configuration via `config.yaml`:

```yaml
network: testnet
min_tx_threshold_btc: 10
large_tx_threshold_btc: 50

whale_event_thresholds:
  single_deposit_btc: 1000
  deposit_burst:
    min_tx_count: 10
    min_total_btc: 1000
    window_minutes: 10
```

## Development

### Local Development

```bash
# Start infrastructure only
docker-compose up -d postgres redis

# Install dependencies
pip install -e ".[dev]"

# Run services locally
python -m tbwi.api.main
python -m tbwi.services.zmq_listener
python -m tbwi.services.classifier
python -m tbwi.services.event_engine
```

### Development Mode with Hot Reload

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

This enables:
- Source code mounting with hot reload
- pgAdmin at http://localhost:5050
- Redis Commander at http://localhost:8081

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "Description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

### Running Tests

```bash
pytest
pytest --cov=tbwi --cov-report=html
```

## API Usage

### Query Whale Events

```bash
# Get recent events
curl http://localhost:8000/api/v1/whale-events?limit=10

# Filter by type
curl http://localhost:8000/api/v1/whale-events?event_type=WH_EXCHANGE_DEPOSIT_BURST

# Filter by entity
curl http://localhost:8000/api/v1/whale-events?entity_label=Binance
```

### Add Entity Tags

```bash
curl -X POST http://localhost:8000/api/v1/entity-tags \
  -H "Content-Type: application/json" \
  -d '{
    "address": "bc1q...",
    "label": "Binance",
    "category": "exchange_deposit",
    "confidence": 0.95
  }'
```

### Webhook Payload

Events are delivered to configured webhooks with this format:

```json
{
  "event_id": "uuid",
  "event_type": "WH_EXCHANGE_DEPOSIT_BURST",
  "created_at": "2024-01-15T10:30:00Z",
  "network": "mainnet",
  "summary": "Binance received 4,200 BTC across 18 deposits",
  "total_value_btc": 4200.0,
  "total_value_usd": 250000000.0,
  "entities": [{"label": "Binance", "category": "exchange"}],
  "txids": ["txid1", "txid2", "..."]
}
```

## Production Deployment

### Security Checklist

- [ ] Set strong `API_API_KEY`
- [ ] Configure `API_CORS_ORIGINS` restrictively
- [ ] Use strong database password
- [ ] Don't expose Bitcoin RPC publicly
- [ ] Use HTTPS for webhooks
- [ ] Configure firewall rules

### Mainnet Configuration

```bash
# In .env
BITCOIN_NETWORK=mainnet
BITCOIN_RPC_PORT=8332
```

### Monitoring

The system exposes Prometheus metrics. Key metrics:
- `tbwi_transactions_processed_total`
- `tbwi_whale_events_created_total`
- `tbwi_zmq_connection_status`
- `tbwi_rpc_latency_seconds`

## Project Structure

```
tbwi/
├── src/tbwi/
│   ├── api/              # FastAPI application
│   │   ├── main.py       # App entry point
│   │   ├── deps.py       # Dependencies
│   │   └── routes/       # API endpoints
│   ├── db/               # Database layer
│   │   ├── models.py     # SQLAlchemy models
│   │   ├── session.py    # Session management
│   │   └── repository.py # Data access
│   ├── models/           # Pydantic schemas
│   ├── services/         # Core services
│   │   ├── zmq_listener.py
│   │   ├── classifier.py
│   │   ├── event_engine.py
│   │   └── webhook_dispatcher.py
│   ├── config.py         # Configuration
│   └── logging.py        # Structured logging
├── alembic/              # Database migrations
├── config/               # Configuration files
├── docker-compose.yml    # Production compose
├── docker-compose.dev.yml # Development overrides
└── Dockerfile            # Multi-stage build
```

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## Support

- Issues: https://github.com/torq/tbwi/issues
- Documentation: https://github.com/torq/tbwi/wiki
