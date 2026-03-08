"""Source coordination and execution strategies."""

import asyncio
from typing import Dict, List, Optional, Union
from dataclasses import dataclass

from .runner_base import QuestionSourceRunner, CollectionResult
from src.config.collection_goal import QualityRequirements
from src.utils.logging import logger


@dataclass
class SourceRequest:
    """Request to collect from a source."""

    source_name: str
    runner: QuestionSourceRunner
    count: int
    type_filter: Optional[List[str]] = None
    category_filter: Optional[Union[Dict[str, int], List[str]]] = None
    quality_requirements: Optional[QualityRequirements] = None
    existing_question_ids: Optional[set] = None
    time_horizon_hints: Optional[List[str]] = None


@dataclass
class CoordinatorResult:
    """Result from coordinator with collected questions and errors."""

    results: List[CollectionResult]
    errors: List[str]


class SourceCoordinator:
    """Coordinates collection from multiple question sources.

    Handles parallel vs sequential execution and error handling.
    """

    def __init__(self, parallel: bool = True):
        """Initialize coordinator.

        Args:
            parallel: Whether to run sources in parallel
        """
        self.parallel = parallel

    async def collect_from_sources(
        self, requests: List[SourceRequest]
    ) -> List[CollectionResult]:
        """Execute collection from multiple sources.

        Args:
            requests: List of source collection requests

        Returns:
            List of collection results
        """
        if self.parallel:
            return await self._collect_parallel(requests)
        else:
            return await self._collect_sequential(requests)

    async def _collect_parallel(
        self, requests: List[SourceRequest]
    ) -> List[CollectionResult]:
        """Run sources in parallel."""
        tasks = [self._collect_from_source(req) for req in requests]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"{requests[i].source_name}: {result}")
                # Create failed result with error
                valid_results.append(
                    CollectionResult(
                        success=False,
                        questions=[],
                        source_name=requests[i].source_name,
                        requested_count=requests[i].count,
                        actual_count=0,
                        error_message=str(result),
                    )
                )
            else:
                valid_results.append(result)

        return valid_results

    async def _collect_sequential(
        self, requests: List[SourceRequest]
    ) -> List[CollectionResult]:
        """Run sources sequentially."""
        results = []
        for req in requests:
            try:
                result = await self._collect_from_source(req)
                results.append(result)
            except Exception as e:
                logger.error(f"{req.source_name}: {e}")
                results.append(
                    CollectionResult(
                        success=False,
                        questions=[],
                        source_name=req.source_name,
                        requested_count=req.count,
                        actual_count=0,
                        error_message=str(e),
                    )
                )

        return results

    async def _collect_from_source(self, request: SourceRequest) -> CollectionResult:
        """Execute single source collection.

        Args:
            request: Source collection request

        Returns:
            Collection result
        """
        logger.info(
            f"Collecting from '{request.source_name}': {request.count} questions..."
        )

        result = await request.runner.collect(
            count=request.count,
            type_filter=request.type_filter,
            category_filter=request.category_filter,
            quality_requirements=request.quality_requirements,
            existing_question_ids=request.existing_question_ids,
            time_horizon_hints=request.time_horizon_hints,
        )

        if result.success and result.questions:
            logger.info(
                f"✓ '{request.source_name}': collected {len(result.questions)} questions"
            )
        else:
            logger.warning(f"✗ '{request.source_name}': no questions collected")

        return result
