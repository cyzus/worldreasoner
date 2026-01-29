"""Service for managing forecasting context from MCP request headers.

This service handles parsing, validation, and caching of forecasting context
that is provided via MCP connection metadata/headers.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from src.domain.models import Question
from src.domain.service_base import ServiceBase
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
        # Extract headers (case-insensitive)
        question_id = headers.get("x-question-id") or headers.get("X-Question-ID")
        simulated_date_str = headers.get("x-simulated-date") or headers.get(
            "X-Simulated-Date"
        )
        knowledge_cutoff_str = headers.get("x-knowledge-cutoff") or headers.get(
            "X-Knowledge-Cutoff"
        )
        session_id = headers.get("x-session-id") or headers.get("X-Session-ID")
        model_name = headers.get("x-model-name") or headers.get("X-Model-Name")
        forecast_mode = headers.get("x-forecast-mode") or headers.get("X-Forecast-Mode")
        db_path = headers.get("x-database-path") or headers.get("X-Database-Path")

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
        knowledge_cutoff = (
            parse_flexible_datetime(knowledge_cutoff_str)
            if knowledge_cutoff_str
            else None
        )

        # Generate session ID if not provided
        if not session_id:
            session_id = f"session_{question_id}_{int(datetime.now().timestamp())}"
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
