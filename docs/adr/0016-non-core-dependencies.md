# ADR-0016: Dependencies outside the core

**Status:** Accepted

## Decision

Dependencies outside the core: the CLI uses `typer` and `rich` (plus `ruamel.yaml` once it edits specs); the sidecar uses `fastapi` and `uvicorn`; each first-party plugin depends only on the library it integrates (`openai`, `anthropic`, `pydantic-ai-slim`, `pydantic-monty`, `opentelemetry-sdk` with the OTLP HTTP exporter, `cel-python`); development uses `pytest`, `hypothesis`, `coverage`, `httpx` (FastAPI's test client), `ruff` and `pyright`.

## Why

Widely used, typed tools; each heavy dependency stays out of the core (R6) and is only installed with the package that needs it (C10).
