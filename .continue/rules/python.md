# AI Agent Rules: Redfish Prometheus Exporter

## Overview
This document defines the rules and conventions for the Prometheus Exporter agent, designed for querying and exposing metrics from multiple hosts concurrently.

You are an expert Python developer assisting with a Prometheus Exporter project that collects hardware metrics via the Redfish API. 
Your primary goals are maintainability, readability, and extensibility.

---

## Rules

Always adhere to the following rules:

## 1. Core Architecture & Concurrency
- **Exporter Role:** This application is a Prometheus Exporter. Metrics are scraped and formatted for a Prometheus Time Series Database (TSDB).
- **Asynchronous Execution:** The exporter queries many hosts concurrently. You MUST use asynchronous programming (`asyncio`, `aiohttp`). 
- **Isolation (Non-blocking):** Ensure that host queries are strictly isolated. A timeout or failure on one host must NEVER block the event loop or affect the scraping of other hosts. Do not use threads; use async coroutines.
- **Extensibility:** Currently, the exporter only fetches power metrics. Design the code (using appropriate patterns) so that adding new metric categories (e.g., thermal, memory, disk) later is seamless.

## 2. Tech Stack & Dependencies
- **Allowed Libraries:** `prometheus_client`, `asyncio`, `aiohttp`, `dataclasses`, `logging`.
- **Dependency Constraint:** DO NOT introduce or use any new external Python modules or libraries. If a task seems impossible without a new module, you MUST ask the user for permission first.

## 3. Specific Module Logic
- **`health.py` (Circuit Breaker):** Use the `HostHealth` class to track host reachability. Mark unreachable hosts as `Failure` and reachable ones as `Success`. Before querying a host, check its status to prevent unnecessary network requests to offline hosts.

## 4. Clean Code Principles
- **DRY (Don't Repeat Yourself):** If logic is used twice, extract it into a dedicated function or method immediately.
- **Dataclasses:** Use `@dataclass` for data structures and internal data passing wherever it makes sense to improve structure and readability.
- **Docstrings:** Write concise, to-the-point docstrings. Only add them where they provide value (summarizing purpose). Avoid overly complex or verbose documentation.

## 5. Testing
- **Test Coverage:** EVERY function and method must have a corresponding test in the `tests/` directory.
- Assume the use of `pytest` and `pytest-asyncio` based on the project structure. Keep tests isolated and mock external HTTP calls (e.g., using the `mock_server`).
- **Mock_server:** Use `config-localdev.yaml` for tests.

## 6. Tooling & Workflow
- **Linting & Formatting:** The project strictly uses `ruff`. You must write code that complies with `ruff check` and `ruff format`. Assume the user runs `just lint` and `just format`.
- **Type checker:** The project strictly uses `mypy -m exporter`. You must write code that has no issues.
- **Documentation:** API documentation is generated using `pdoc -o docs .`. Ensure docstrings are compatible with `pdoc`.
