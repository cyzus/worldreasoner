"""Service for managing forecasting context from MCP request headers.

This service handles parsing, validation, and caching of forecasting context
that is provided via MCP connection metadata/headers.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

from src.domain.models import Question
from src.services.service_base import ServiceBase
from src.utils.date_utils import parse_flexible_datetime
from src.utils.logging import logger


@dataclass
class ForecastContext:
    """Forecasting context extracted from MCP request headers.

    Attributes:
        question_id: The question to forecast
        simulated_date: The simulated "today" date for forecasting
        knowledge_cutoff: The LLM's training data cutoff (optional)
        session_id: Unique session identifier
        model_name: Name of the model making the forecast (default: "unknown")
        forecast_mode: Mode of forecasting (default: "container")
        db_path: Optional database path for per-request DB switching
        question: Cached Question object (loaded on first access)
    """

    question_id: str
    simulated_date: datetime
    knowledge_cutoff: Optional[datetime]
    session_id: str
    model_name: str = "unknown"
    forecast_mode: str = "container"
    db_path: Optional[str] = None
    question: Optional[Question] = None


class ForecastContextService(ServiceBase):
    """Service for managing forecasting context.

    Handles:
    - Parsing context from MCP request headers
    - Validating context (date consistency, required fields)
    - Loading and caching question data
    """

    def parse_context_from_headers(self, headers: Dict[str, str]) -> ForecastContext:
        """Extract forecasting context from MCP request headers.

        Expected headers:
        - X-Question-ID (required): Question to forecast
        - X-Simulated-Date (required): Simulated "today" date
        - X-Knowledge-Cutoff (optional): LLM's training data cutoff
        - X-Session-ID (optional): Unique session identifier
        - X-Model-Name (optional): Model name
        - X-Forecast-Mode (optional): Forecast mode
        - X-Database-Path (optional): Database path for per-request switching

        Args:
            headers: Dictionary of request headers

        Returns:
            ForecastContext object

        Raises:
            ValueError: If required headers are missing or invalid
        """
        # Extract headers (case-insensitive normalization)
        normalized_headers = {k.lower(): v for k, v in headers.items()}
        question_id = normalized_headers.get("x-question-id")
        simulated_date_str = normalized_headers.get("x-simulated-date")
        knowledge_cutoff_str = normalized_headers.get("x-knowledge-cutoff")
        session_id = normalized_headers.get("x-session-id")
        model_name = normalized_headers.get("x-model-name")
        forecast_mode = normalized_headers.get("x-forecast-mode")
        db_path = normalized_headers.get("x-database-path")

        # Validate required fields
        if not question_id:
            raise ValueError(
                "Forecasting context not initialized. "
                "Client must provide X-Question-ID header when connecting."
            )

        if not simulated_date_str:
            raise ValueError(
                "Simulated date not initialized. "
                "Client must provide X-Simulated-Date header when connecting. "
                "This header represents the simulated 'today' date (must be before the question's resolution date)."
            )

        # Parse dates
        simulated_date = parse_flexible_datetime(simulated_date_str)
        
        knowledge_cutoff = None
        if knowledge_cutoff_str and knowledge_cutoff_str.lower() != "unknown":
            knowledge_cutoff = parse_flexible_datetime(knowledge_cutoff_str)

        # Generate session ID if not provided
        if not session_id:
            session_id = (
                f"session_{question_id}_{int(datetime.now(timezone.utc).timestamp())}"
            )
            logger.warning(f"No session_id in headers, generated new one: {session_id}")

        return ForecastContext(
            question_id=question_id,
            simulated_date=simulated_date,
            knowledge_cutoff=knowledge_cutoff,
            session_id=session_id,
            model_name=model_name or "unknown",
            forecast_mode=forecast_mode or "container",
            db_path=db_path,
            question=None,  # Loaded on demand
        )

    def parse_context_from_env(self) -> ForecastContext:
        """Extract forecasting context from environment variables.

        Used by the stdio MCP server transport, where HTTP headers are not
        available. The ForecastAgent sets these env vars before spawning the
        subprocess.

        Expected env vars (same keys as headers, uppercase with underscores):
            WR_QUESTION_ID, WR_SIMULATED_DATE, WR_KNOWLEDGE_CUTOFF,
            WR_SESSION_ID, WR_MODEL_NAME, WR_FORECAST_MODE, WR_DATABASE_PATH
        """
        import os

        headers = {}
        env_to_header = {
            "WR_QUESTION_ID": "x-question-id",
            "WR_SIMULATED_DATE": "x-simulated-date",
            "WR_KNOWLEDGE_CUTOFF": "x-knowledge-cutoff",
            "WR_SESSION_ID": "x-session-id",
            "WR_MODEL_NAME": "x-model-name",
            "WR_FORECAST_MODE": "x-forecast-mode",
            "WR_DATABASE_PATH": "x-database-path",
        }
        for env_key, header_key in env_to_header.items():
            val = os.environ.get(env_key)
            if val:
                headers[header_key] = val

        return self.parse_context_from_headers(headers)

    def validate_context(self, context: ForecastContext) -> None:
        """Validate forecasting context for logical consistency.

        Validation checks:
        - If knowledge_cutoff is provided, it must be before simulated_date
          (LLM must be "deployed" after its training ends)

        Args:
            context: ForecastContext to validate

        Raises:
            ValueError: If context is invalid
        """
        # Validate knowledge cutoff < simulated date if provided
        if (
            context.knowledge_cutoff
            and context.knowledge_cutoff >= context.simulated_date
        ):
            logger.error(
                f"Invalid dates: knowledge_cutoff {context.knowledge_cutoff.date()} "
                f"must be before simulated_date {context.simulated_date.date()}"
            )
            raise ValueError(
                f"Knowledge cutoff ({context.knowledge_cutoff.date()}) must be BEFORE "
                f"simulated date ({context.simulated_date.date()}). "
                f"The LLM must be 'deployed' after its training ends."
            )

    def get_question_for_context(self, context: ForecastContext) -> Question:
        """Load question for the given context.

        Uses cached question if available, otherwise loads from database.

        Args:
            context: ForecastContext with question_id

        Returns:
            Question object

        Raises:
            ValueError: If question not found
        """
        # Return cached question if available
        if context.question:
            return context.question

        # Use database from context if provided, otherwise use default db
        db = self.get_db(context.db_path)
        question = db.get(Question, context.question_id)

        if not question:
            raise ValueError(f"Question not found: {context.question_id}")

        # Cache question in context
        context.question = question

        return question
