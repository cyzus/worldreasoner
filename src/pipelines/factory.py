"""Pipeline factory for consistent configuration.

Centralizes pipeline creation to avoid duplicate configuration logic
across CLI and backend API.
"""

from src.config import Config
from src.config.database import DatabaseConfig
from src.config.pipeline import EvidencePipelineConfig, EvidenceSatisfactionConfig
from src.pipelines.types import PipelineType


class PipelineFactory:
    """Factory for creating configured pipeline instances."""

    @staticmethod
    def create_evidence_pipeline(
        config: Config, db_path: str, adaptive: bool = False, **kwargs
    ):
        """Create configured evidence pipeline.

        Args:
            config: Global configuration
            db_path: Path to database
            adaptive: Whether to use adaptive multi-agent mode
            **kwargs: Pipeline-specific configuration overrides
        """
        from src.pipelines.evidence import EvidencePipeline

        satisfaction_kwargs = {}
        if "min_evidence_articles" in kwargs:
            satisfaction_kwargs["min_articles"] = kwargs["min_evidence_articles"]

        evidence_config = EvidencePipelineConfig(
            satisfaction=EvidenceSatisfactionConfig(**satisfaction_kwargs),
            evidence_window_days=kwargs.get("evidence_window_days", 365),
            include_expert_analysis=True,
        )

        database_config = DatabaseConfig(db_path=db_path)

        # Adaptive mode uses agent-based evidence collection
        if adaptive:
            return EvidencePipeline(
                evidence_config=evidence_config,
                database_config=database_config,
                enable_persistence=True,
                agent_max_steps=kwargs.get("agent_max_steps", 30),
                min_graph_depth=kwargs.get("min_graph_depth", 3),
                min_quality_score=kwargs.get("min_quality_score"),
            )
        else:
            # Basic mode uses fixed stages
            return EvidencePipeline(
                evidence_config=evidence_config,
                database_config=database_config,
                enable_persistence=True,
            )

    @staticmethod
    def create(pipeline_type: PipelineType, config: Config, db_path: str, **kwargs):
        """Create pipeline by type.

        Args:
            pipeline_type: Type of pipeline to create
            config: Global configuration
            db_path: Path to database
            **kwargs: Pipeline-specific configuration

        Returns:
            Configured pipeline instance

        Raises:
            NotImplementedError: If pipeline type is not yet supported by factory
        """
        if pipeline_type in [PipelineType.EVIDENCE, PipelineType.ADAPTIVE_EVIDENCE]:
            return PipelineFactory.create_evidence_pipeline(
                config,
                db_path,
                adaptive=(pipeline_type == PipelineType.ADAPTIVE_EVIDENCE),
                **kwargs,
            )

        # Other pipeline types (FORECAST, COLLECTION, etc.) don't use factory yet
        # They're created inline in the executor
        raise NotImplementedError(
            f"Pipeline type {pipeline_type} not yet in factory. "
            f"Factory currently supports: EVIDENCE, ADAPTIVE_EVIDENCE"
        )
