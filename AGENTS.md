# AGENTS.md - Coding Agent Guidelines

## Commands

**Setup & Run:**
```bash
just setup          # First-time setup (deps + Docker image)
just start          # Start all services (Ollama + FastAPI + Vite)
just backend        # Start FastAPI only (port 8000)
just frontend       # Start Vite only (port 5173)
just stop           # Stop all services
```

**Testing & Code Quality:**
```bash
pytest tests/ -v                                    # All tests
pytest tests/test_api_endpoints.py::test_name -v   # Single test
just lint                                           # Check code (ruff)
just format                                         # Format code (ruff)
```

## Architecture

**Core Stack:**
- **Backend**: FastAPI (`src/api/main.py`) with Stripe webhooks, SQLAlchemy ORM, SQLite database
- **Frontend**: Vite React (`src/client_portal/`) for task submission & tracking
- **LLM Service**: Multi-model routing (`src/llm_service.py`) - OpenAI cloud + local Ollama
- **Execution**: Docker sandbox (`src/agent_execution/docker_sandbox.py`) for secure code execution
- **Vector DB**: ChromaDB (`src/experience_vector_db.py`) for RAG few-shot learning
- **Database**: SQLite (`data/tasks.db`) with models in `src/api/models.py`

**Key Modules:**
- `src/agent_execution/executor.py` - Task execution with retries
- `src/agent_execution/planning.py` - Research & planning workflow
- `src/agent_execution/arena.py` - A/B testing agents (local vs cloud)
- `src/agent_execution/market_scanner.py` - Async marketplace scraping
- `src/utils/telemetry.py` - OpenTelemetry observability
- `src/utils/logger.py` - Rotating file logging
- `src/distillation/` - Model fine-tuning data collection

## Code Style

**Imports:** Standard lib → Third-party → Local. Use type hints (`from typing import Optional, Dict, List`). Import from parent packages with `from ..module import`.

**Naming:** `snake_case` for functions/vars, `PascalCase` for classes/enums. Constants are `UPPER_CASE`. Prefix private methods with `_`.

**Types:** Use Pydantic models (`BaseModel`) for API schemas. Add return type hints to all functions. Use `Optional[T]` for nullable types.

**Error Handling:** Use `raise HTTPException(status_code=400, detail="msg")` in API handlers. Log errors with `logger.error()` before raising. Use try/except/finally for resource cleanup (especially async contexts).

**Async:** Use `async with` context managers for resources. Mark async functions with `@task` decorator (Traceloop). Never block event loop with sync I/O.

**Formatting:** Max line 100 chars. Use ruff formatter. Docstrings for classes/public functions with Args/Returns/Raises sections.

**Database:** Use SQLAlchemy models with `.to_dict()` methods. Always close sessions. Use dependency injection: `def endpoint(db: Session = Depends(get_db))`.

See `CLAUDE.md` for detailed architecture & `REPOSITORY_ANALYSIS.md` for known issues.
