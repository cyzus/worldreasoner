"""Backfill ground truth for previously-unresolved Polymarket questions.

When a Polymarket question is ingested while its market is still open, it is
stored with ``ground_truth=None``. Nothing in the normal flow goes back to fill
that in once the market resolves. This module re-fetches such questions from the
Gamma API and copies over the outcome when it has become available.

Shared by the ``wr question refresh-polymarket`` CLI command and the API server's
startup hook.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from src.core.database import GenericDatabase
from src.domain.models import Question
from src.utils.logging import logger


@dataclass
class RefreshResult:
    """Outcome of a Polymarket ground-truth refresh pass."""

    candidates: int = 0  # unresolved polymarket questions examined
    updated: int = 0  # questions that gained ground truth
    still_unresolved: int = 0  # examined but market still open / no outcome
    errors: List[str] = field(default_factory=list)
    updated_ids: List[str] = field(default_factory=list)


def _identifier_for(question: Question) -> Optional[str]:
    """Best identifier to re-fetch a stored Polymarket question by.

    Prefers the stored market/event slug (stable across resolution); falls back
    to the market id encoded in the question id (``polymarket_<market_id>``).
    """
    metadata = question.metadata or {}
    slug = metadata.get("market_slug")
    if slug:
        return str(slug)

    # Fall back to the numeric/condition id embedded in the question id.
    if question.id.startswith("polymarket_"):
        market_id = question.id[len("polymarket_") :]
        # Aggregated events are stored as event_<id>; strip the prefix so the
        # resolver tries the numeric event id.
        if market_id.startswith("event_"):
            return market_id[len("event_") :]
        return market_id
    return None


async def refresh_polymarket_ground_truth(
    db: GenericDatabase,
    limit: Optional[int] = None,
) -> RefreshResult:
    """Re-fetch unresolved Polymarket questions and backfill ground truth.

    Args:
        db: Database to update in place.
        limit: Optional cap on how many unresolved questions to check.

    Returns:
        RefreshResult with counts and the ids that were updated.
    """
    # Import here to avoid a heavy import chain at module load.
    from src.pipelines.collection import PolymarketRunner

    result = RefreshResult()

    # Find stored Polymarket questions that are still unresolved.
    questions = db.get_many(Question, filters={"source": "polymarket"})
    unresolved = [q for q in questions if q.ground_truth is None]
    if limit is not None:
        unresolved = unresolved[:limit]
    result.candidates = len(unresolved)

    if not unresolved:
        return result

    # require_ground_truth=True so the parser actually extracts outcomes.
    runner = PolymarketRunner(require_ground_truth=True)

    for question in unresolved:
        identifier = _identifier_for(question)
        if not identifier:
            result.errors.append(f"{question.id}: no slug/market id to re-fetch")
            continue

        try:
            fetched = await runner.collect_by_identifiers([identifier])
        except Exception as e:  # network or parse failure for this one item
            logger.warning(f"Refresh failed for {question.id}: {e}")
            result.errors.append(f"{question.id}: {e}")
            continue

        # Match the freshly-resolved question back to the stored one by id.
        fresh = next((q for q in fetched.questions if q.id == question.id), None)
        if fresh is None and fetched.questions:
            # Single-result fallback (id can differ if Polymarket reshaped it).
            fresh = fetched.questions[0]

        if fresh is None or fresh.ground_truth is None:
            result.still_unresolved += 1
            continue

        # Backfill the outcome onto the stored question.
        question.ground_truth = fresh.ground_truth
        if fresh.resolution_reasoning:
            question.resolution_reasoning = fresh.resolution_reasoning
        if fresh.resolution_date:
            question.resolution_date = fresh.resolution_date
        db.save(Question, question)

        result.updated += 1
        result.updated_ids.append(question.id)
        logger.info(
            f"Backfilled ground truth for {question.id}: {fresh.ground_truth!r}"
        )

    return result
