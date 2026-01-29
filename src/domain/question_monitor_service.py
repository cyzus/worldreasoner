"""Question monitoring service for evidence and forecast readiness.

This service monitors:
1. Which questions need evidence collection (unprocessed, meet quality thresholds)
2. Which questions are ready for forecasting (by mode)
3. LLM model usage statistics
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from src.config.pipeline import EvidenceSatisfactionConfig
from src.core.database import GenericDatabase
from src.domain.models.question import Question
from src.domain.models.forecast import Forecast, ForecastMode
from src.domain.models.causal_hypothesis import CausalHypothesis
from src.domain.models.article import Article
from src.domain.service_base import ServiceBase
from src.utils.logging import logger
from src.utils.graph_analysis import calculate_graph_quality


@dataclass
class EvidenceSatisfaction:
    """Evidence satisfaction status for a question."""
    is_satisfied: bool
    graph_depth: int
    article_count: int
    hypothesis_count: int
    missing_requirements: List[str] = field(default_factory=list)


@dataclass
class ForecastToolConfig:
    """Enabled tools for a forecast mode.
    
    Tracks which tool categories are enabled. Extensible for future tools.
    """
    causal_tools: bool = False  # identify_forecast_event, create_causal_link, etc.
    # Future tools can be added here (e.g., web_tools, analysis_tools)


@dataclass
class ForecastReadiness:
    """Forecast readiness for a question."""
    available_modes: List[ForecastMode]
    recommended_mode: ForecastMode
    tool_config: Dict[str, ForecastToolConfig]  # mode name -> tool config
    evidence_status: EvidenceSatisfaction
    temporal_status: Dict  # window_start, window_end, etc.


@dataclass
class ModelUsageStats:
    """LLM model usage statistics."""
    model_name: str
    forecast_count: int
    correct_count: int
    accuracy: Optional[float] = None
    avg_confidence: Optional[float] = None


class QuestionMonitorService(ServiceBase):
    """Monitor questions for evidence needs and forecast readiness.
    
    Provides unified view of:
    - Questions needing evidence collection
    - Evidence satisfaction status
    - Forecast readiness by mode
    - LLM model usage statistics
    """

    def __init__(self, db: GenericDatabase, config: EvidenceSatisfactionConfig = None):
        """Initialize the monitor service.
        
        Args:
            db: Database instance
            config: Evidence satisfaction thresholds (uses defaults if not provided)
        """
        super().__init__(db)
        self.config = config or EvidenceSatisfactionConfig()

    def get_evidence_needs(
        self,
        min_quality_score: Optional[float] = None,
        domain: Optional[str] = None,
        limit: int = 50
    ) -> List[Question]:
        """Get questions that need evidence collection.
        
        Returns questions that:
        - Have ground truth (resolved)
        - Not marked skip_evidence
        - Quality score >= threshold (if specified)
        - Don't have sufficient evidence yet
        
        Args:
            min_quality_score: Minimum quality score filter
            domain: Filter by domain
            limit: Maximum questions to return
            
        Returns:
            List of questions needing evidence
        """
        questions = self.db.get_many(Question)
        
        # Get all hypotheses to check which questions have evidence
        hypotheses = self.db.get_many(CausalHypothesis)
        questions_with_evidence = set()
        for h in hypotheses:
            questions_with_evidence.update(h.discovered_by_question_ids)
        
        needs_evidence = []
        for q in questions:
            # Must be resolved
            if q.ground_truth is None:
                continue
            
            # Not marked for skip
            if q.skip_evidence:
                continue
            
            # Domain filter
            if domain and str(q.domain) != domain and q.domain.value != domain:
                continue
            
            # Quality filter
            if min_quality_score is not None:
                if q.quality_score is None or q.quality_score < min_quality_score:
                    continue
            
            # Check if already has sufficient evidence
            if q.id in questions_with_evidence:
                satisfaction = self.check_satisfaction(q.id)
                if satisfaction.is_satisfied:
                    continue
            
            needs_evidence.append(q)
            
            if len(needs_evidence) >= limit:
                break
        
        return needs_evidence

    def check_satisfaction(self, question_id: str) -> EvidenceSatisfaction:
        """Check if a question's evidence meets satisfaction requirements.
        
        Args:
            question_id: Question ID to check
            
        Returns:
            EvidenceSatisfaction with status and details
        """
        # Get hypotheses for this question
        all_hypotheses = self.db.get_many(CausalHypothesis)
        question_hypotheses = [
            h for h in all_hypotheses
            if question_id in h.discovered_by_question_ids
        ]
        
        hypothesis_count = len(question_hypotheses)
        
        # Get evidence articles
        evidence_article_ids = set()
        for h in question_hypotheses:
            evidence_article_ids.update(h.evidence_article_ids)
        article_count = len(evidence_article_ids)
        
        # Calculate graph depth
        graph_depth = 0
        if question_hypotheses:
            question = self.db.get(Question, question_id)
            target_event_id = question.target_event_id if question else None
            
            if target_event_id:
                quality_metrics = calculate_graph_quality(
                    hypotheses=question_hypotheses,
                    target_event_id=target_event_id,
                    min_depth_for_full_score=self.config.min_graph_depth
                )
                graph_depth = quality_metrics.get('max_depth', 0)
            else:
                # Without target, can't calculate depth properly
                graph_depth = 1 if hypothesis_count > 0 else 0
        
        # Check requirements
        missing = []
        if graph_depth < self.config.min_graph_depth:
            missing.append(f"graph_depth ({graph_depth} < {self.config.min_graph_depth})")
        if article_count < self.config.min_articles:
            missing.append(f"articles ({article_count} < {self.config.min_articles})")
        if hypothesis_count < self.config.min_hypotheses:
            missing.append(f"hypotheses ({hypothesis_count} < {self.config.min_hypotheses})")
        
        return EvidenceSatisfaction(
            is_satisfied=len(missing) == 0,
            graph_depth=graph_depth,
            article_count=article_count,
            hypothesis_count=hypothesis_count,
            missing_requirements=missing
        )

    def get_forecast_readiness(self, question_id: str) -> ForecastReadiness:
        """Get forecast readiness and available modes for a question.
        
        Args:
            question_id: Question ID to check
            
        Returns:
            ForecastReadiness with available modes and tool configs
        """
        question = self.db.get(Question, question_id)
        if not question:
            raise ValueError(f"Question not found: {question_id}")
        
        evidence_status = self.check_satisfaction(question_id)
        
        # Check temporal status
        temporal_status = {}
        try:
            window_start, window_end = question.get_forecast_context_window(self.db)
            temporal_status = {
                "window_start": window_start.isoformat() if window_start else None,
                "window_end": window_end.isoformat() if window_end else None,
                "is_valid": window_start is not None and window_end is not None
            }
        except Exception as e:
            temporal_status = {"is_valid": False, "error": str(e)}
        
        # Determine available modes
        available_modes = []
        tool_config = {}
        
        # KNOWLEDGE_ONLY is always available
        available_modes.append(ForecastMode.KNOWLEDGE_ONLY)
        tool_config[ForecastMode.KNOWLEDGE_ONLY.value] = ForecastToolConfig(causal_tools=True)
        
        # CONTAINER requires evidence satisfaction
        if evidence_status.is_satisfied:
            available_modes.append(ForecastMode.CONTAINER)
            tool_config[ForecastMode.CONTAINER.value] = ForecastToolConfig(causal_tools=True)
        
        # REAL_TIME requires valid temporal window
        if temporal_status.get("is_valid"):
            available_modes.append(ForecastMode.REAL_TIME)
            tool_config[ForecastMode.REAL_TIME.value] = ForecastToolConfig(causal_tools=True)
        
        # Recommend best mode
        if ForecastMode.CONTAINER in available_modes:
            recommended = ForecastMode.CONTAINER
        elif ForecastMode.REAL_TIME in available_modes:
            recommended = ForecastMode.REAL_TIME
        else:
            recommended = ForecastMode.KNOWLEDGE_ONLY
        
        return ForecastReadiness(
            available_modes=available_modes,
            recommended_mode=recommended,
            tool_config=tool_config,
            evidence_status=evidence_status,
            temporal_status=temporal_status
        )

    def get_model_usage_stats(self, model_name: Optional[str] = None) -> List[ModelUsageStats]:
        """Get LLM model usage statistics from forecasts.
        
        Args:
            model_name: Filter to specific model (None for all)
            
        Returns:
            List of ModelUsageStats per model
        """
        forecasts = self.db.get_many(Forecast)
        
        # Aggregate by model
        stats: Dict[str, Dict] = {}
        for f in forecasts:
            name = f.model_name or "unknown"
            
            if model_name and name != model_name:
                continue
            
            if name not in stats:
                stats[name] = {
                    "count": 0,
                    "correct": 0,
                    "confidence_sum": 0.0
                }
            
            stats[name]["count"] += 1
            stats[name]["confidence_sum"] += f.confidence
            
            if f.is_correct is True:
                stats[name]["correct"] += 1
        
        # Convert to dataclass
        result = []
        for name, data in stats.items():
            count = data["count"]
            correct = data["correct"]
            accuracy = correct / count if count > 0 else None
            avg_confidence = data["confidence_sum"] / count if count > 0 else None
            
            result.append(ModelUsageStats(
                model_name=name,
                forecast_count=count,
                correct_count=correct,
                accuracy=accuracy,
                avg_confidence=avg_confidence
            ))
        
        return sorted(result, key=lambda x: x.forecast_count, reverse=True)
