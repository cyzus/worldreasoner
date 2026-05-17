"""Service for forecast validation and submission.

This service handles all forecast submission operations, including prediction
validation, forecast creation, and graph linking.
"""

from typing import Tuple, Any, Optional, Dict, List
from datetime import datetime, timezone
import sqlite3

from src.domain.models import Question, Forecast
from src.domain.models.question import QuestionType
from src.domain.models.forecast import ForecastMode
from src.services.service_base import ServiceBase
from src.utils.logging import logger


class ForecastSubmissionService(ServiceBase):
    """Service for forecast validation and submission.

    Handles:
    - Prediction validation based on question type
    - Forecast creation and persistence
    - Graph element linking (events and hypotheses)
    """

    def validate_prediction(
        self, question: Question, prediction: str
    ) -> Tuple[bool, Any, Optional[str]]:
        """Validate and parse prediction based on question type.

        Args:
            question: Question being forecasted
            prediction: Prediction string to validate

        Returns:
            Tuple of (valid, parsed_value, error_msg) where:
            - valid: True if prediction is valid
            - parsed_value: Parsed prediction value (type depends on question type)
            - error_msg: Error message if invalid, None otherwise
        """
        try:
            # Parse prediction based on question type
            if question.question_type == QuestionType.BINARY:
                valid_true = ["true", "yes", "1"]
                valid_false = ["false", "no", "0"]
                prediction_lower = prediction.lower().strip()

                if self._has_named_binary_options(question):
                    option_by_lower = {
                        str(option).strip().lower(): option
                        for option in question.options or []
                    }
                    if prediction_lower in option_by_lower:
                        parsed_prediction = option_by_lower[prediction_lower]
                    elif prediction_lower in valid_true:
                        parsed_prediction = question.options[0]
                    elif prediction_lower in valid_false:
                        parsed_prediction = question.options[1]
                    else:
                        return (
                            False,
                            None,
                            f"Invalid binary prediction '{prediction}'. "
                            f"Expected one of: {question.options}",
                        )
                elif prediction_lower not in valid_true + valid_false:
                    return (
                        False,
                        None,
                        f"Invalid binary prediction '{prediction}'. "
                        f"Expected one of: {valid_true + valid_false}",
                    )
                else:
                    parsed_prediction = prediction_lower in valid_true
            elif question.question_type == QuestionType.MCQ:
                parsed_prediction = prediction
            elif question.question_type == QuestionType.QUANTITY:
                parsed_prediction = float(prediction)
            else:
                parsed_prediction = prediction
        except ValueError as e:
            options_text = ""
            if question.question_type == QuestionType.MCQ and question.options:
                options_text = f" Valid options are: {question.options}"
            return (
                False,
                None,
                f"Invalid prediction format for {question.question_type.value}: {e}.{options_text}",
            )

        if not question.validate_prediction(parsed_prediction):
            options_text = ""
            if question.question_type == QuestionType.MCQ and question.options:
                options_text = f" Valid options are: {question.options}"

            return (
                False,
                None,
                (
                    f"Invalid prediction format for question type {question.question_type.value}. "
                    f"Expected format: {question.question_type.value}.{options_text}"
                ),
            )

        return True, parsed_prediction, None

    @staticmethod
    def _has_named_binary_options(question: Question) -> bool:
        """Return True for two-outcome questions whose labels are not Yes/No."""
        if not question.options or len(question.options) != 2:
            return False

        normalized_options = {str(option).strip().lower() for option in question.options}
        return normalized_options not in (
            {"yes", "no"},
            {"true", "false"},
            {"1", "0"},
        )

    def create_forecast(
        self,
        question_id: str,
        session_id: str,
        prediction: Any,
        confidence: float,
        reasoning: str,
        articles_accessed: List[str],
        simulated_date: datetime,
        target_event_id: Optional[str] = None,
        model_name: str = "unknown",
        mode: str = "container",
        db_path: Optional[str] = None,
        evaluation_metadata: Optional[dict] = None,
    ) -> Forecast:
        """Create and save a forecast.

        Args:
            question_id: Question being forecasted
            session_id: Session identifier
            prediction: Parsed prediction value
            confidence: Confidence level (0-1)
            reasoning: Reasoning for the prediction
            articles_accessed: List of article IDs accessed
            simulated_date: Simulated "today" date
            target_event_id: Optional target event ID (from question)
            model_name: Name of the model making the forecast
            mode: Forecast mode (e.g., "container", "api")
            db_path: Optional database path for per-request DB switching

        Returns:
            Created Forecast object
        """
        # Generate forecast ID
        forecast_id = (
            f"fcst_{question_id}_{int(datetime.now(timezone.utc).timestamp())}"
        )

        # Create forecast object
        forecast = Forecast(
            id=forecast_id,
            session_id=session_id,
            question_id=question_id,
            target_event_id=target_event_id,
            prediction=prediction,
            confidence=confidence,
            reasoning=reasoning,
            timestamp=datetime.now(timezone.utc),
            simulated_date=simulated_date,
            articles_accessed=articles_accessed or [],
            searches_performed=[],  # Could track this if needed
            model_name=model_name,
            mode=ForecastMode(mode),
            db=db_path,
            evaluation_metadata=evaluation_metadata,
        )

        # Save forecast to appropriate database
        forecast_db = self.get_db(db_path)
        forecast_db.save(Forecast, forecast)
        logger.info(f"Forecast saved to database: {forecast_id}")

        return forecast

    def link_forecast_graph(
        self, forecast_id: str, session_id: str, db_path: Optional[str] = None
    ) -> Dict[str, int]:
        """Link forecast graph elements (events and hypotheses) to forecast.

        Updates all ForecastEvent and ForecastHypothesis objects for this session
        to reference the forecast_id.

        Args:
            forecast_id: Forecast ID to link to
            session_id: Session ID to filter graph elements
            db_path: Optional database path for per-request DB switching

        Returns:
            Dictionary with counts of linked elements:
            - events: Number of events linked
            - hypotheses: Number of hypotheses linked
        """
        from src.domain.models.forecast_graph import ForecastEvent, ForecastHypothesis

        forecast_db = self.get_db(db_path)

        try:
            # Get all forecast events for this session
            events = forecast_db.get_many(
                ForecastEvent, filters={"session_id": session_id}
            )
            for event in events:
                event.forecast_id = forecast_id
                forecast_db.save(ForecastEvent, event)

            # Get all forecast hypotheses for this session
            hypotheses = forecast_db.get_many(
                ForecastHypothesis, filters={"session_id": session_id}
            )
            for hyp in hypotheses:
                hyp.forecast_id = forecast_id
                forecast_db.save(ForecastHypothesis, hyp)

            logger.info(
                f"Linked {len(events)} events and {len(hypotheses)} hypotheses to forecast {forecast_id}"
            )

            return {"events": len(events), "hypotheses": len(hypotheses)}
        except (KeyError, ValueError, sqlite3.Error) as e:
            logger.warning(f"Could not link forecast graph to forecast_id: {e}")
            return {"events": 0, "hypotheses": 0}
