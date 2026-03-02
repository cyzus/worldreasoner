# WorldReasoner - Agent Coding Guidelines

This document provides guidance for AI agents working in the WorldReasoner codebase.

## Build, Lint & Test Commands

```bash
# Install dependencies
uv pip install -e .

# Run all tests
uv run pytest

# Run single test file
uv run pytest tests/unit/test_gap_analyzer.py

# Run single test function
uv run pytest tests/unit/test_gap_analyzer.py::test_find_gaps

# Run tests with verbose output
uv run pytest -v

# Run tests matching a pattern
uv run pytest -k "test_find"

# Run tests in a specific directory
uv run pytest tests/unit/

# Run tests excluding integration tests
uv run pytest -m "not integration"

# Run only slow tests
uv run pytest -m slow

# Run integration tests (requires external services)
uv run pytest -m integration

# Type checking
uv run mypy src/

# Linting with auto-fix
uv run ruff check src/ --fix

# Linting with strict rules
uv run ruff check src/ --strict

# Run CLI entry point
uv run wr --help

# Run backend server
uv run worldreasoner --help

# Run MCP forecasting server
uv run worldreasoner-mcp-forecast --help

# Format code
uv run ruff format src/
```

## Code Style Guidelines

### Imports
- Use absolute imports: `from src.domain.models import Question`
- Group in order: stdlib → third-party → local
- Sort alphabetically within groups
- Example:
  ```python
  import logging
  from pathlib import Path
  from typing import Optional
  
  import pydantic
  from loguru import logger
  
  from src.domain.services import QuestionService
  ```

### Formatting
- Use ruff for formatting: `uv run ruff format src/`
- Maximum line length: 88 characters (ruff default)
- Use 4 spaces for indentation (not tabs)
- Add trailing commas for multi-line collections
- Use f-strings for string formatting

### Types
- Use type hints for all function parameters and return values
- Prefer `Optional[X]` over `X | None`
- Use concrete types: `List[str]`, `Dict[str, int]` (not `list`, `dict`)
- Use `Any` sparingly - prefer specific types
- Define custom types for complex structures using TypeAlias

### Naming Conventions
- Classes: `PascalCase` (e.g., `QuestionService`)
- Functions/methods: `snake_case` (e.g., `get_evidence_status`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `MAX_RETRY_COUNT`)
- Private methods: prefix with `_` (e.g., `_internal_method`)
- Private classes: prefix with `_` (e.g., `_BaseService`)
- Files: `snake_case.py` (e.g., `question_service.py`)

### Error Handling
- Use exceptions for unexpected errors, not return codes
- Provide helpful error messages with context
- Log errors with appropriate level: `logger.error()`, `logger.warning()`
- Use custom exception classes for domain-specific errors
- Catch specific exceptions, avoid bare `except:`
- Example:
  ```python
  try:
      result = await service.get_question(question_id)
  except QuestionNotFoundError:
      logger.warning(f"Question {question_id} not found")
      raise
  except DatabaseError as e:
      logger.error(f"Database error: {e}")
      raise RuntimeError("Failed to fetch question") from e
  ```

### Database Patterns
- Use `GenericDatabase` for all database operations
- Always check if item exists before accessing: `if not item:`
- Use `not_found_response()` helper in tools for consistent errors
- Use transactions for multi-step operations
- Log all database operations at debug level

### Tool Development
- Inherit from `DatabaseAwareTool` for tools needing DB access
- Inherit from `CollectorAwareTool` for tools that collect results
- Use `ToolResponseMixin` for standardized JSON responses
- Define `name`, `description`, `inputs`, `output_type` class attributes
- Use pydantic for input validation
- Document all tool parameters with descriptions

### Service Layer
- Domain services go in `src/domain/`, not CLI layer
- Services should be pure business logic (no CLI dependencies)
- Use `ServiceBase` as base class for new services
- Pass db instance to services, avoid singleton patterns
- Keep services focused on single responsibility

### Testing
- Use fixtures from `tests/conftest.py`: `test_db_path`, `persistent_test_db_path`
- Mock external dependencies (LLMs, web requests)
- Mark integration tests with `@pytest.mark.integration`
- Test one thing per test function
- Use descriptive test names: `test_should_return_question_when_exists`
- Group related tests in classes
- Use `pytest.raises` for exception testing

## Architecture Overview

### Key Directories
- `src/domain/` - Pure business logic, database models
- `src/core/` - Infrastructure services (temporal, database)
- `src/tools/` - Agent tools (inherit from smolagents Tool)
- `src/pipelines/` - Pipeline orchestration
- `src/cli/` - CLI wrappers (delegate to domain services)
- `backend/` - FastAPI server
- `tests/` - Test fixtures and test cases
- `migrations/` - Database migrations

### Core Patterns
- **Events vs Articles**: Events are causal graph nodes, articles are documentation
- **Temporal Access**: Use `TemporalFilterService` for time-based filtering
- **Provenance**: Tag data with `question_id` for tracking

### Key Services
- `QuestionService` - Question CRUD and evidence management
- `TemporalGateway` - Time-based access control for forecasting
- `OutcomeEventService` - Outcome tracking (events with `is_outcome=True`)
- `ForecastSubmissionService` - Forecast validation and storage

## Troubleshooting

| Symptom | Solution |
|---------|----------|
| Collector has 0 items | Use `if self.collector is not None:` not `if self.collector:` |
| Test shows 0 outputs | Use `result.outputs` not `stage.tool.collected_items` |
| Windows encoding errors | Use ASCII only in logs, or set UTF-8 encoding |
| Missing DB column | Run migration: `python migrations/add_*.py` |
| Import errors | Ensure `uv pip install -e .` was run |
| Type check errors | Run `uv run mypy src/` to see details |

## Dependencies
- **smolagents**: Agent framework with LiteLLM
- **pydantic**: Data validation
- **loguru**: Logging
- **pytest-asyncio**: Async testing
- **fastapi**: Web framework
- **typer**: CLI framework
