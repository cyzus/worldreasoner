"""Prediction market question source runners.

Imports questions directly from prediction markets like Polymarket and Metaculus.
Refactored to use modular client and parser utilities (flat hierarchy pattern).
"""

from typing import List, Optional, Dict, Any, Union
from datetime import datetime, timezone
import json
from pydantic import BaseModel

from .base import QuestionSourceRunner, CollectionResult
from .polymarket_client import PolymarketClient
from .market_parser import MarketParser
from src.domain.models import Question
from src.domain.models.domain import Domain
from src.domain.models.question import QuestionType
from src.config.collection_goal import QualityRequirements
from src.utils.logging import logger
from src.utils.date_utils import parse_iso_datetime


class MarketQuestion(BaseModel):
    """Intermediate representation of a market question."""

    market_id: str
    market_source: str
    question_text: str
    question_type: str
    resolution_criteria: str
    close_time: datetime
    resolution_time: Optional[datetime] = None
    current_probability: Optional[float] = None
    volume_usd: Optional[float] = None
    liquidity_usd: Optional[float] = None
    category: Optional[str] = None
    options: Optional[List[str]] = None
    metadata: Dict[str, Any] = {}


class PolymarketRunner(QuestionSourceRunner):
    """Question source from Polymarket prediction market.
    
    Refactored to use modular utilities:
    - PolymarketClient: HTTP API wrapper
    - MarketParser: Data parsing and validation
    """

    # Default type mapping (maps market types to QuestionType enum values)
    DEFAULT_TYPE_MAP = {
        "binary": QuestionType.BINARY,
        "mcq": QuestionType.MCQ,
    }

    # Map domains to Polymarket tag slugs for API filtering
    # Use proper slugs that can be resolved to tag IDs
    DOMAIN_TO_TAG_SLUGS = {
        Domain.POLITICS: ["politics", "geopolitics", "elections"],
        Domain.FINANCE: ["finance", "economy"],
        Domain.SPORTS: ["sports"],
        Domain.TECH: ["tech", "ai"],
        Domain.CULTURE: ["entertainment","music","movies"],
        Domain.HEALTH: ["health", "pandemic"],
        Domain.SCIENCE: ["science"],
        Domain.BUSINESS: ["business"],
        Domain.CLIMATE: ["climate","weather"],
        Domain.GENERAL: ["all"],
    }

    def __init__(
        self,
        min_volume_usd: float = 0.0,  # Relaxed - many markets lack volume data
        require_ground_truth: bool = True,
        type_map: Optional[Dict[str, QuestionType]] = None,
    ):
        """Initialize Polymarket runner.

        Args:
            min_volume_usd: Minimum trading volume filter (0 = no filter)
            require_ground_truth: If True, fetch resolved markets with outcomes. If False, fetch active future markets.
            type_map: Custom mapping from market question types to QuestionType enum values (uses DEFAULT_TYPE_MAP if not provided)
        """
        super().__init__(source_name="polymarket")
        self.min_volume_usd = min_volume_usd
        self.require_ground_truth = require_ground_truth
        self.type_map = type_map or self.DEFAULT_TYPE_MAP
        
        # Initialize utilities
        self.client = PolymarketClient()
        self.parser = MarketParser(require_ground_truth=require_ground_truth)
    
    async def _fetch_markets_by_category(
        self,
        category_filter: Optional[Union[Dict[str, int], List[str]]],
        limit: int,
        quality_requirements: Optional[QualityRequirements] = None
    ) -> List[MarketQuestion]:
        """Fetch markets by category using tag-based API filtering.

        Uses Polymarket's tag_id parameter to fetch markets for specific domains.

        Args:
            category_filter: Categories to fetch (domain names or dict with counts)
            limit: Total markets to fetch (distributed across categories)
            quality_requirements: Quality constraints

        Returns:
            List of MarketQuestion objects with pre-assigned domains
        """
        if not category_filter:
            # No filter - fetch general markets
            return await self._fetch_markets(limit=limit, quality_requirements=quality_requirements)

        # Parse requested domains and determine per-category limits
        # Use high multiplier to account for deduplication during gap filling
        if isinstance(category_filter, dict):
            requested_domains = [Domain(cat) if isinstance(cat, str) else cat
                                for cat in category_filter.keys()]
            # Use the full limit per category (already multiplied by 20x in collect method)
            # This ensures we fetch enough to have unique questions after deduplication
            category_limits = {domain: limit for domain in requested_domains}
        else:
            requested_domains = [Domain(cat) if isinstance(cat, str) else cat
                                for cat in category_filter]
            # Distribute the limit evenly across categories
            per_domain = max(1, limit // len(requested_domains))
            category_limits = {domain: per_domain for domain in requested_domains}

        all_markets = []

        for domain in requested_domains:
            # Get tag slug for this domain
            tag_slugs = self.DOMAIN_TO_TAG_SLUGS.get(domain)
            if not tag_slugs:
                logger.debug(f"No tag slug mapping for {domain.value}, skipping")
                continue

            per_category_limit = category_limits.get(domain, limit)
            logger.info(f"Fetching up to {per_category_limit} {domain.value} markets using tag '{tag_slugs}'")

            # Fetch markets for this tag
            market_list = await self.client.fetch_markets(
                limit=per_category_limit,
                require_ground_truth=self.require_ground_truth,
                quality_requirements=quality_requirements,
                tag_slugs=tag_slugs  # Use tag_slugs which will be converted to tag_id
            )

            # Parse markets up to the per-category limit
            parsed_for_category = 0
            for market in market_list:
                # Stop if we've collected enough for this category
                if parsed_for_category >= per_category_limit:
                    break

                # Parse dates
                end_date_str = market.get("endDate")
                if not end_date_str:
                    continue

                try:
                    end_date = parse_iso_datetime(end_date_str)
                except Exception:
                    continue

                closed_time = self.parser.parse_close_time(market)
                should_skip, _ = self.parser.should_skip_market(
                    market, end_date, closed_time, quality_requirements
                )

                if should_skip:
                    continue

                # Parse market
                mq = self._parse_single_market(market, end_date, closed_time)
                if mq:
                    # Assign domain from tag (no LLM needed!)
                    mq.metadata["known_domain"] = domain.value
                    all_markets.append(mq)
                    parsed_for_category += 1

            logger.info(f"Parsed {parsed_for_category} {domain.value} markets")

        return all_markets

    def _parse_single_market(self, market: Dict[str, Any], end_date: datetime, closed_time: Optional[datetime]) -> Optional[MarketQuestion]:
        """Parse a single market into MarketQuestion.

        Args:
            market: Market data from API
            end_date: Parsed end date
            closed_time: Parsed closed time (if available)

        Returns:
            MarketQuestion or None if parsing fails
        """
        try:
            question_text = market.get("question")
            if not question_text:
                return None

            # Get description (resolution criteria)
            description = market.get("description", "")
            if not description:
                # Fallback: try to get from events
                events = market.get("events", [])
                if events and isinstance(events, list) and len(events) > 0:
                    description = events[0].get("description", "")

            # Use description as resolution criteria, with fallback
            resolution_criteria = description if description else f"See https://polymarket.com/event/{market.get('slug', '')}"

            # Parse actual outcomes from the API
            outcomes = self.parser.parse_outcomes(market)

            # Determine question type based on market type and outcomes content
            market_type = market.get("marketType", "normal")
            if market_type == "normal":
                # Treat binary outcomes as binary (Yes/No, Up/Down, Win/Lose, etc.)
                if len(outcomes) == 2:
                    question_type = "binary"
                else:
                    question_type = "mcq"
            elif market_type == "scalar":
                # Skip scalar markets (price predictions)
                return None
            else:
                # Unknown market type, check outcomes as fallback
                if len(outcomes) == 2:
                    question_type = "binary"
                else:
                    question_type = "mcq"

            # Extract ground truth for resolved markets
            ground_truth, resolution_reasoning = self.parser.extract_ground_truth(market, outcomes)

            # Get volume
            volume = market.get("volumeNum", 0.0) or 0.0

            # Parse CLOB token IDs for price history
            clob_ids_raw = market.get('clobTokenIds', '[]')
            clob_ids = json.loads(clob_ids_raw) if isinstance(clob_ids_raw, str) else clob_ids_raw

            return MarketQuestion(
                market_id=market.get("conditionId", market.get("id")),
                market_source="polymarket",
                question_text=question_text,
                question_type=question_type,
                resolution_criteria=resolution_criteria,
                close_time=end_date,
                resolution_time=closed_time,
                current_probability=market.get("lastTradePrice"),
                volume_usd=volume if volume > 0 else None,
                liquidity_usd=market.get("liquidityNum"),
                category=market.get("category"),
                options=outcomes,
                metadata={
                    "market_slug": market.get("slug"),
                    "clob_token_ids": clob_ids,  # Store for price history fetching
                    "tags": market.get("tags", []),
                    "active": market.get("active"),
                    "events": market.get("events", []),
                    "categories": market.get("categories", []),
                    "ground_truth": ground_truth,
                    "resolution_reasoning": resolution_reasoning,
                    "closed": market.get("closed", False),
                },
            )
        except Exception as e:
            logger.debug(f"Failed to parse market {market.get('question', 'unknown')}: {e}")
            return None

    async def collect_from_search(
        self,
        search_query: str,
        count: int,
        type_filter: Optional[List[str]] = None,
        quality_requirements: Optional[QualityRequirements] = None,
        existing_question_ids: Optional[set] = None,
    ) -> CollectionResult:
        """Collect questions from Polymarket search results.

        Args:
            search_query: Search query term
            count: Target number of questions
            type_filter: Only collect these question types
            quality_requirements: Quality constraints
            existing_question_ids: Set of existing IDs to skip

        Returns:
            CollectionResult with Polymarket questions from search
        """
        try:
            logger.info(f"PolymarketRunner: Searching Polymarket for '{search_query}'")

            # Search Polymarket
            search_results = await self.client.search_markets(
                query=search_query,
                limit_per_type=count * 2,  # Fetch more to account for filtering
                keep_closed_markets=self.require_ground_truth,
            )

            # Extract markets from events in search results
            events = search_results.get("events", [])
            market_questions = []

            for event in events:
                # Each event contains markets
                markets = event.get("markets", [])

                for market in markets:
                    # Parse dates
                    end_date_str = market.get("endDate")
                    if not end_date_str:
                        continue

                    try:
                        end_date = parse_iso_datetime(end_date_str)
                    except Exception:
                        continue

                    closed_time = self.parser.parse_close_time(market)
                    should_skip, _ = self.parser.should_skip_market(
                        market, end_date, closed_time, quality_requirements
                    )

                    if should_skip:
                        continue

                    # Parse market
                    mq = self._parse_single_market(market, end_date, closed_time)
                    if mq:
                        market_questions.append(mq)

            logger.info(f"Parsed {len(market_questions)} markets from search results")

            # Map to Question model
            questions = []
            for mq in market_questions:
                try:
                    question = self._map_to_question(mq)
                    questions.append(question)
                except Exception as e:
                    logger.warning(f"Failed to map market {mq.market_id}: {e}")

            # Filter by existing IDs
            if existing_question_ids:
                questions = [q for q in questions if q.id not in existing_question_ids]

            # Filter by type if specified
            if type_filter:
                questions = [q for q in questions if q.question_type in type_filter]

            # Take only the requested count
            questions = questions[:count]

            logger.info(f"Collected {len(questions)} questions from search")

            return CollectionResult(
                source_name=self.source_name,
                questions=questions,
                requested_count=count,
                actual_count=len(questions),
                success=True,
            )

        except Exception as e:
            logger.error(f"Failed to collect from Polymarket search: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return CollectionResult(
                source_name=self.source_name,
                questions=[],
                requested_count=count,
                actual_count=0,
                success=False,
                error_message=str(e),
            )

    async def collect(
        self,
        count: int,
        type_filter: Optional[List[str]] = None,
        category_filter: Optional[Union[Dict[str, int], List[str]]] = None,
        quality_requirements: Optional[QualityRequirements] = None,
        existing_question_ids: Optional[set] = None,
    ) -> CollectionResult:
        """Collect questions from Polymarket.

        Args:
            count: Target number of questions
            type_filter: Only collect these question types
            category_filter: Dict mapping categories to number still needed
            quality_requirements: Quality constraints
            existing_question_ids: Set of existing IDs to skip

        Returns:
            CollectionResult with Polymarket questions
        """
        try:
            logger.info(f"PolymarketRunner: Fetching up to {count} questions (require_ground_truth={self.require_ground_truth})")

            # Use tag-based fetching if category filter is provided
            # This eliminates the need for LLM categorization!
            if category_filter:
                logger.info(f"Using tag-based fetching for categories: {category_filter}")
                # Use same multiplier as non-category fetch (count * 20 for ground truth mode)
                fetch_limit = count * 20 if self.require_ground_truth else count * 5
                market_questions = await self._fetch_markets_by_category(
                    category_filter=category_filter,
                    limit=fetch_limit,
                    quality_requirements=quality_requirements
                )
            else:
                # Fetch market questions - fetch many to have options
                fetch_limit = count * 20 if self.require_ground_truth else count * 5
                market_questions = await self._fetch_markets(
                    limit=fetch_limit,
                    quality_requirements=quality_requirements
                )

            # Map to Question model
            questions = []
            for mq in market_questions:
                try:
                    question = self._map_to_question(mq)
                    questions.append(question)
                except Exception as e:
                    logger.warning(f"Failed to map market {mq.market_id}: {e}")

            # Tag with source
            self._tag_questions_with_source(questions)

            # EARLY DEDUPLICATION: Filter duplicates before ANY processing
            # This saves both categorization AND cache lookups
            if existing_question_ids is not None:
                before_dedup = len(questions)
                questions = [q for q in questions if q.id not in existing_question_ids]

                if before_dedup != len(questions):
                    logger.info(f"Early duplicate filter: removed {before_dedup - len(questions)} duplicates before processing")

            if not questions:
                logger.warning("No questions remaining after early deduplication")
                return CollectionResult(
                    source_name=self.source_name,
                    questions=[],
                    requested_count=count,
                    actual_count=0,
                    success=True,
                    metadata={"all_duplicates": True},
                )

            # Filter questions based on criteria
            filtered = self._filter_questions(
                questions,
                type_filter=type_filter,
                category_filter=category_filter,
                quality_requirements=quality_requirements,
            )
            logger.info(f"Filtered from {len(questions)} down to {len(filtered)} questions after applying type/category/quality filters")

            # Smart sampling by type and/or category if filters specified
            if (type_filter or category_filter) and len(filtered) > count:
                final = []

                # Priority 1: Sample by category if category_filter is provided
                # This ensures we get diverse categories instead of all from one category
                if category_filter:
                    by_category = {}
                    for q in filtered:
                        cat = q.domain.value if hasattr(q.domain, 'value') else str(q.domain)
                        if cat not in by_category:
                            by_category[cat] = []
                        by_category[cat].append(q)

                    # Sample evenly from available categories
                    available_categories = list(by_category.keys())
                    cat_idx = 0
                    while len(final) < count and any(by_category.values()):
                        cat = available_categories[cat_idx % len(available_categories)]
                        if by_category[cat]:
                            final.append(by_category[cat].pop(0))
                        cat_idx += 1

                # Priority 2: If no category filter but type filter, sample by type
                elif type_filter:
                    by_type = {}
                    for q in filtered:
                        if q.question_type not in by_type:
                            by_type[q.question_type] = []
                        by_type[q.question_type].append(q)

                    # Sample evenly from available types
                    available_types = list(by_type.keys())
                    type_idx = 0
                    while len(final) < count and any(by_type.values()):
                        qtype = available_types[type_idx % len(available_types)]
                        if by_type[qtype]:
                            final.append(by_type[qtype].pop(0))
                        type_idx += 1
                else:
                    final = filtered
            else:
                # Return up to count
                final = filtered

            logger.info(
                f"Polymarket: {len(final)}/{count} questions collected "
                f"({len(questions)} fetched, {len(filtered)} after filter)"
            )

            return CollectionResult(
                source_name=self.source_name,
                questions=final,
                requested_count=count,
                actual_count=len(final),
                success=True,
                metadata={
                    "markets_fetched": len(market_questions),
                    "questions_mapped": len(questions),
                    "questions_filtered": len(filtered),
                },
            )

        except Exception as e:
            logger.error(f"PolymarketRunner error: {e}")
            return CollectionResult(
                source_name=self.source_name,
                questions=[],
                requested_count=count,
                actual_count=0,
                success=False,
                error_message=str(e),
            )

    async def _fetch_markets(
        self,
        limit: int = 1000,
        quality_requirements: Optional[QualityRequirements] = None
    ) -> List[MarketQuestion]:
        """Fetch markets from Polymarket API.

        Args:
            limit: Maximum markets to fetch
            quality_requirements: Quality constraints (used for date filtering)

        Returns:
            List of MarketQuestion objects
        """
        markets = []

        try:
            # Fetch market list from API using client
            market_list = await self.client.fetch_markets(
                limit=limit,
                require_ground_truth=self.require_ground_truth,
                quality_requirements=quality_requirements
            )

            if not market_list:
                return []

            parsed_count = 0
            skipped_not_closed = 0  # For ground truth mode: markets not yet closed/resolved
            skipped_closed = 0  # For prediction mode: markets already closed
            skipped_past = 0  # Markets with dates outside target range
            skipped_future_close = 0  # Markets with closedTime in the future
            skipped_no_close_time = 0  # Markets without closedTime/umaEndDate
            skipped_volume = 0
            skipped_scalar = 0  # Scalar markets (price predictions)
            failed_parse = 0

            for market in market_list:
                # Parse end date (needed for all markets)
                end_date_str = market.get("endDate")
                if not end_date_str:
                    failed_parse += 1
                    continue

                try:
                    end_date = parse_iso_datetime(end_date_str)
                except Exception as e:
                    failed_parse += 1
                    logger.debug(f"Failed to parse endDate: {e}")
                    continue

                # Parse actual resolution date (try multiple fields for robustness)
                closed_time = self.parser.parse_close_time(market)

                # Filter based on mode (ground truth vs prediction)
                should_skip, skip_reason = self.parser.should_skip_market(market, end_date, closed_time, quality_requirements)
                if should_skip:
                    # Update skip counters based on reason
                    if skip_reason == "not_closed":
                        skipped_not_closed += 1
                    elif skip_reason == "no_close_time":
                        skipped_no_close_time += 1
                        logger.debug(f"Market closed but no resolution time: {market.get('question', 'unknown')[:50]}")
                    elif skip_reason == "future_close":
                        skipped_future_close += 1
                    elif skip_reason == "too_old":
                        skipped_past += 1
                    elif skip_reason == "already_closed":
                        skipped_closed += 1
                    elif skip_reason == "wrong_date":
                        skipped_past += 1
                    continue

                # Get volume (Gamma API provides volumeNum)
                volume = market.get("volumeNum", 0.0) or 0.0

                # Apply volume filter (relaxed - many markets don't have volume data)
                # Only filter if we have volume data AND it's below threshold
                if volume > 0 and volume < self.min_volume_usd:
                    skipped_volume += 1
                    continue

                # Parse market into MarketQuestion
                mq = self._parse_single_market(market, end_date, closed_time)
                if mq is None:
                    # Check if it was a scalar market (already logged in helper)
                    if market.get("marketType") == "scalar":
                        skipped_scalar += 1
                    else:
                        failed_parse += 1
                    continue

                markets.append(mq)
                parsed_count += 1

            if self.require_ground_truth:
                logger.info(
                    f"Polymarket parsing: {parsed_count} markets parsed, "
                    f"{skipped_not_closed} not closed/resolved, {skipped_no_close_time} no resolution time, "
                    f"{skipped_past} too old, {skipped_future_close} future closedTime, "
                    f"{skipped_volume} low volume, {skipped_scalar} scalar markets, {failed_parse} failed"
                )
            else:
                logger.info(
                    f"Polymarket parsing: {parsed_count} markets parsed, "
                    f"{skipped_closed} already closed, {skipped_past} wrong date, "
                    f"{skipped_volume} low volume, {skipped_scalar} scalar markets, {failed_parse} failed"
                )

        except Exception as e:
            logger.error(f"Error fetching Polymarket markets: {e}")

        return markets

    def _map_to_question(self, mq: MarketQuestion) -> Question:
        """Map MarketQuestion to WorldReasoner Question model.
        
        Uses pre-assigned domain from tag-based fetching (no LLM needed).

        Args:
            mq: Market question to map

        Returns:
            Question instance
        """
        # Use pre-assigned domain from tag-based fetching
        if mq.metadata and "known_domain" in mq.metadata:
            domain_str = mq.metadata["known_domain"]
            try:
                domain = Domain(domain_str)
                category = domain_str
            except ValueError:
                domain = Domain.GENERAL
                category = "general"
        else:
            domain = Domain.GENERAL
            category = "general"

        # Extract ground truth from metadata if available
        ground_truth = mq.metadata.get("ground_truth") if mq.metadata else None
        resolution_reasoning = mq.metadata.get("resolution_reasoning") if mq.metadata else None

        # Prepare metadata dict with all Polymarket-specific data
        # Remove fields that are already direct Question parameters to avoid conflicts
        extra_metadata = {k: v for k, v in mq.metadata.items()
                         if k not in ('ground_truth', 'resolution_reasoning')}

        metadata_dict = {
            "source": "polymarket",
            "market_id": mq.market_id,
            "current_probability": mq.current_probability,
            "volume_usd": mq.volume_usd,
            "liquidity_usd": mq.liquidity_usd,
            "category": category,  # Use extracted category from tags
            "options": mq.options,
            **extra_metadata,  # Includes clob_token_ids, tags, and other market data
        }

        return Question(
            id=f"polymarket_{mq.market_id}",
            question_text=mq.question_text,
            question_type=self.type_map.get(mq.question_type, QuestionType.BINARY),
            domain=domain,
            source="polymarket",
            difficulty=self._estimate_difficulty(mq),
            resolution_date=mq.resolution_time or mq.close_time,
            cutoff_date=mq.close_time,
            created_at=datetime.now(timezone.utc),
            ground_truth=ground_truth,  # Use ground truth from metadata
            resolution_reasoning=resolution_reasoning,  # Add resolution reasoning
            resolution_criteria=mq.resolution_criteria,
            target_event_id=None,
            related_event_ids=[],
            options=mq.options,
            metadata=metadata_dict,  # Store all extra fields in metadata
        )

    def _estimate_difficulty(self, mq: MarketQuestion) -> int:
        """Estimate difficulty based on market metrics.

        Args:
            mq: Market question

        Returns:
            Difficulty level (1-5)
        """
        difficulty = 3

        # High volume suggests important question
        if mq.volume_usd and mq.volume_usd > 100000:
            difficulty += 1

        # Probability near 50% = uncertain/hard
        if mq.current_probability:
            uncertainty = abs(0.5 - mq.current_probability)
            if uncertainty < 0.15:  # 35-65%
                difficulty += 1
            elif uncertainty > 0.35:  # <15% or >85%
                difficulty -= 1

        return max(1, min(5, difficulty))


    async def can_provide(
        self,
        question_type: Optional[str] = None,
        category: Optional[str] = None,
    ) -> bool:
        """Check if Polymarket can provide questions of given type/category.

        Args:
            question_type: Question type to check
            category: Category to check

        Returns:
            True if type/category is supported
        """
        # Type support: Polymarket has binary and MCQ, but NOT quantity/timeframe
        if question_type:
            supported = ["binary", "mcq"]
            return question_type.lower() in supported

        # Category support: check if we have a tag slug mapping
        if category:
            try:
                domain = Domain(category) if isinstance(category, str) else category
            except ValueError:
                return False
            return domain in self.DOMAIN_TO_TAG_SLUGS

        return True