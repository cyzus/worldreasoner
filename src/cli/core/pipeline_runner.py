"""Unified pipeline execution with progress callbacks.

CLI wrapper that delegates to PipelineExecutor for actual work.
Maintains backward compatibility for existing CLI commands.
"""

from typing import List, Optional, Callable, Dict

from src.config import get_config, Config
from src.core.database import GenericDatabase
from src.pipelines.executor import PipelineExecutor
from src.pipelines.types import PipelineType, PipelineProgress, PipelineResult
from src.services.question_service import QuestionService
from src.utils.logging import logger


class PipelineRunner:
    """Unified pipeline execution with progress callbacks.

    Thin CLI wrapper that delegates to PipelineExecutor for orchestration.
    Maintains backward compatibility for existing CLI commands.

    Usage:
        runner = PipelineRunner(db_path="worldreasoner.db")

        # With progress callback
        def on_progress(p: PipelineProgress):
            print(f"[{p.current}/{p.total}] {p.stage}: {p.message}")

        result = await runner.run(
            PipelineType.EVIDENCE,
            question_ids=["q_1", "q_2"],
            on_progress=on_progress
        )
    """

    def __init__(
        self,
        db_path: str = "worldreasoner.db",
        config: Optional[Config] = None,
    ):
        """Initialize PipelineRunner.

        Args:
            db_path: Path to database file
            config: Optional configuration (uses get_config() if not provided)
        """
        self.db_path = db_path
        self.config = config or get_config()
        self.db = GenericDatabase(db_path)

        # Delegate to executor for orchestration
        self.executor = PipelineExecutor(self.config, db_path)

        # Domain service for question operations
        self.question_service = QuestionService(self.db)

    async def run(
        self,
        pipeline_type: PipelineType,
        question_ids: List[str],
        on_progress: Optional[Callable[[PipelineProgress], None]] = None,
        **kwargs,
    ) -> PipelineResult:
        """Run a pipeline on selected questions.

        Delegates to PipelineExecutor for actual execution.

        Args:
            pipeline_type: Type of pipeline to run
            question_ids: List of question IDs to process
            on_progress: Optional callback for progress updates
            **kwargs: Pipeline-specific configuration

        Returns:
            PipelineResult with processed/failed/skipped items
        """
        return await self.executor.execute(
            pipeline_type, question_ids, on_progress, **kwargs
        )

    async def clear_evidence(
        self,
        question_ids: List[str],
        cascade: bool = True,
    ) -> Dict[str, List[str]]:
        """Clear evidence data for questions.

        Delegates to QuestionService for domain logic.

        Args:
            question_ids: Questions to clear evidence for
            cascade: Also delete orphaned events/articles

        Returns:
            Dict with cleared/failed lists
        """
        results = {"cleared": [], "failed": []}

        for qid in question_ids:
            try:
                self.question_service.clear_evidence(qid, cascade=cascade)
                results["cleared"].append(qid)
            except Exception as e:
                logger.error(f"Failed to clear evidence for {qid}: {e}")
                results["failed"].append({"id": qid, "error": str(e)})

        return results
