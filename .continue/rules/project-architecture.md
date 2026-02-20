# Project Architecture Overview

## Core Components
- **Exporter Module**: Handles Redfish API interactions, metric collection, and Prometheus exposure.
- **Docker Setup**: Containerized for easy deployment and testing.
- **Mock Server**: Simulates Redfish endpoints for testing.

## Key Files
- `compose.yaml`: Defines services, networks, and volumes.
- `prometheus.yaml`: Prometheus scraping configuration.
- `exporter/main.py`: Entry point for the exporter.

## Best Practices
- Use `config-localdev.yaml` for local overrides.
- Keep `pyproject.toml` updated with dependencies.
- Add new tests for every feature/bugfix.

## Project Structure

```
├── compose.yaml
├── config-localdev.yaml
├── config.yaml.example
├── Dockerfile
├── exporter
│   ├── api.py
│   ├── auth.py
│   ├── config.py
│   ├── health.py
│   ├── __init__.py
│   ├── main.py
│   ├── metrics.py
│   ├── redfish.py
│   └── utils.py
├── __init__.py
├── justfile
├── LICENSE
├── __main__.py
├── pyproject.toml
├── README.md
├── redfish-exporter.service
├── renovate.json
├── tests
│   ├── conftest.py
│   ├── mock_server
│   │   ├── compose.yaml
│   │   └── README.md
│   ├── test_api.py
│   ├── test_auth.py
│   ├── test_config.py
│   ├── test_health.py
│   ├── test_metrics.py
│   ├── test_redfish.py
│   └── test_utils.py
└── uv.lock
```

