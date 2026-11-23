# Data Collector 2.0

A multi-tenant, API-first data collection platform built with Flask, MongoDB, Redis/RQ, and Model Context Protocol (MCP) adapters for Claude and ChatGPT.

## Quickstart (Local Development)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate  |  Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Start MongoDB and Redis (or use Docker Compose):
```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d mongo redis
data-collector ensure-indexes
data-collector admin bootstrap --email admin@example.com
```

Run services:
- **REST API**: `dc-api` (default `http://127.0.0.1:8000`)
- **Background Worker**: `dc-worker`
- **MCP Remote HTTP**: `dc-mcp-http` (default `http://127.0.0.1:8001/mcp`)
- **MCP Local Stdio**: `DATA_COLLECTOR_API_KEY=<key> dc-mcp-stdio`

## Testing & Quality Gates
```bash
pytest tests --cov=data_collector --cov-report=term-missing
ruff check data_collector tests
mypy data_collector
bandit -r data_collector -ll
```

## Documentation
- [Current State Audit](docs/architecture/current-state.md)
- [Target Architecture](docs/architecture/target-state.md)
- [Threat Model](docs/architecture/threat-model.md)
- [ADR-0001](docs/adr/0001-incremental-flask-mongodb-refactor.md)
- [MCP Setup Guide](docs/mcp/setup.md)
- [Operations Runbook](docs/operations/runbook.md)
