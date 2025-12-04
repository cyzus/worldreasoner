"""Prediction market question source runners.

Imports questions directly from prediction markets like Polymarket and Metaculus.
"""

from typing import List, Optional, Dict, Any, Union
from datetime import datetime, timezone
import json
import aiohttp
from pydantic import BaseModel

from .base import QuestionSourceRunner, CollectionResult
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
    """Question source from Polymarket prediction market."""

    # Use Gamma API as per official documentation
    API_BASE = "https://gamma-api.polymarket.com"

    # Default type mapping (maps market types to QuestionType enum values)
    DEFAULT_TYPE_MAP = {
        "boolean": QuestionType.BOOLEAN,
        "binary": QuestionType.BOOLEAN,
        "multiple_choice": QuestionType.MCQ,
    }

    # Default category to domain mapping
    DEFAULT_CATEGORY_MAP = {
        "finance": Domain.FINANCE,
        "technology": Domain.TECH,
        "tech": Domain.TECH,
        "politics": Domain.POLITICS,
        "science": Domain.SCIENCE,
        "sports": Domain.SPORTS,
        "other": Domain.GENERAL,
    }

    def __init__(
        self,
        min_volume_usd: float = 0.0,  # Relaxed - many markets lack volume data
        use_agent_enhancement: bool = True,
        require_ground_truth: bool = True,
        type_map: Optional[Dict[str, QuestionType]] = None,
        category_map: Optional[Dict[str, Domain]] = None,
    ):
        """Initialize Polymarket runner.

        Args:
            min_volume_usd: Minimum trading volume filter (0 = no filter)
            use_agent_enhancement: Use LLM agent to categorize and enhance questions
            require_ground_truth: If True, fetch resolved markets with outcomes. If False, fetch active future markets.
            type_map: Custom mapping from market question types to QuestionType enum values (uses DEFAULT_TYPE_MAP if not provided)
            category_map: Custom mapping from market categories to Domain enum values (uses DEFAULT_CATEGORY_MAP if not provided)
        """
        super().__init__(source_name="polymarket")
        self.min_volume_usd = min_volume_usd
        self.use_agent_enhancement = use_agent_enhancement
        self.require_ground_truth = require_ground_truth
        self.type_map = type_map or self.DEFAULT_TYPE_MAP
        self.category_map = category_map or self.DEFAULT_CATEGORY_MAP

        # Cache categorizations across multiple collect() calls to avoid re-categorizing
        self._categorization_cache: Dict[str, tuple] = {}  # question_id -> (domain, category)

    def _get_lookback_days(self, quality_requirements: Optional[QualityRequirements]) -> int:
        """Get lookback days from quality requirements.

        Args:
            quality_requirements: Quality constraints

        Returns:
            Number of days to look back for market data
        """
        lookback_days = 180  # Default to last 6 months
        if quality_requirements and quality_requirements.min_resolution_days < 0:
            lookback_days = abs(quality_requirements.min_resolution_days)
        return lookback_days

    def _parse_market_close_time(self, market: Dict[str, Any]) -> Optional[datetime]:
        """Parse actual resolution date from market data.

        Tries multiple fields in priority order:
        1. umaEndDate (newer markets, ISO format)
        2. closedTime (older markets)

        Args:
            market: Market data from API

        Returns:
            Parsed datetime or None if unable to parse
        """
        closed_time = None

        # Try umaEndDate first (newer markets, already ISO format)
        if market.get("umaEndDate"):
            try:
                closed_time = parse_iso_datetime(market.get("umaEndDate"))
            except Exception as e:
                logger.debug(f"Failed to parse umaEndDate: {e}")

        # Fall back to closedTime (older markets)
        if not closed_time and market.get("closedTime"):
            try:
                closed_time_str = market.get("closedTime")
                # Handle format: "2020-11-02 16:31:01+00"
                if " " in closed_time_str and "+" in closed_time_str:
                    closed_time_str = closed_time_str.replace(" ", "T").replace("+00", "+00:00")
                closed_time = datetime.fromisoformat(closed_time_str)
            except Exception as e:
                logger.debug(f"Failed to parse closedTime: {e}")

        return closed_time

    def _parse_market_outcomes(self, market: Dict[str, Any]) -> List[str]:
        """Parse outcomes from market data.

        Args:
            market: Market data from API

        Returns:
            List of outcome strings
        """
        try:
            outcomes_str = market.get("outcomes", '["Yes", "No"]')
            outcomes = json.loads(outcomes_str)
            if not isinstance(outcomes, list) or len(outcomes) == 0:
                outcomes = ["Yes", "No"]  # Fallback
            return outcomes
        except Exception as e:
            logger.debug(f"Failed to parse outcomes for market {market.get('question', 'unknown')}: {e}")
            return ["Yes", "No"]  # Fallback

    def _extract_ground_truth(self, market: Dict[str, Any], outcomes: List[str]) -> tuple[Optional[str], Optional[str]]:
        """Extract ground truth and resolution reasoning from resolved market.

        Args:
            market: Market data from API
            outcomes: List of possible outcomes

        Returns:
            Tuple of (ground_truth, resolution_reasoning)
        """
        ground_truth = None
        resolution_reasoning = None

        if not market.get("closed") or not self.require_ground_truth:
            return ground_truth, resolution_reasoning

        try:
            outcome_prices_str = market.get("outcomePrices", "")
            if outcome_prices_str:
                outcome_prices = json.loads(outcome_prices_str)

                # Find the winning outcome (price = "1" means it won)
                for idx, price in enumerate(outcome_prices):
                    if price == "1" and idx < len(outcomes):
                        ground_truth = outcomes[idx]
                        break

                # Add resolution reasoning
                if ground_truth:
                    resolved_by = market.get("resolvedBy", "")
                    auto_resolved = market.get("automaticallyResolved", False)
                    resolution_method = "automatically" if auto_resolved else "manually"
                    resolution_reasoning = f"Market resolved {resolution_method} to '{ground_truth}'"
        except Exception as e:
            logger.debug(f"Failed to parse ground truth for market {market.get('question', 'unknown')}: {e}")

        return ground_truth, resolution_reasoning

    def _should_skip_market(
        self,
        market: Dict[str, Any],
        end_date: datetime,
        closed_time: Optional[datetime],
        quality_requirements: Optional[QualityRequirements]
    ) -> tuple[bool, str]:
        """Check if market should be skipped based on filters.

        Args:
            market: Market data from API
            end_date: Market end date
            closed_time: Market closed time (if available)
            quality_requirements: Quality constraints

        Returns:
            Tuple of (should_skip, reason)
        """
        from datetime import timedelta

        if self.require_ground_truth:
            # For ground truth: need closed markets with resolved outcomes
            # Check 1: Must be closed (resolved)
            if not market.get("closed"):
                return True, "not_closed"

            # Check 2: Must have outcome prices (indicates actual resolution)
            outcome_prices_str = market.get("outcomePrices", "")
            if not outcome_prices_str or outcome_prices_str == "[]":
                return True, "not_closed"

            # Check 3: Must have actual resolution time for accurate filtering
            if not closed_time:
                return True, "no_close_time"

            # Check 4: closedTime must be within time window
            now = datetime.now(timezone.utc)
            lookback_days = self._get_lookback_days(quality_requirements)
            min_date = now - timedelta(days=lookback_days)

            if closed_time > now:
                return True, "future_close"
            if closed_time < min_date:
                return True, "too_old"
        else:
            # For predictions: need open markets with future resolution
            if market.get("closed"):
                return True, "already_closed"

            if end_date < datetime.now(timezone.utc):
                return True, "wrong_date"

        return False, ""

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
            outcomes = self._parse_market_outcomes(market)

            # Determine question type based on market type and outcomes content
            market_type = market.get("marketType", "normal")
            if market_type == "normal":
                # Check if it's a true boolean (Yes/No) or binary MCQ
                if outcomes == ["Yes", "No"]:
                    question_type = "boolean"
                else:
                    question_type = "multiple_choice"
            elif market_type == "scalar":
                # Skip scalar markets (price predictions)
                return None
            else:
                # Unknown market type, check outcomes as fallback
                if outcomes == ["Yes", "No"]:
                    question_type = "boolean"
                else:
                    question_type = "multiple_choice"

            # Extract ground truth for resolved markets
            ground_truth, resolution_reasoning = self._extract_ground_truth(market, outcomes)

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

    async def _fetch_market_list_from_api(
        self,
        session: aiohttp.ClientSession,
        limit: int,
        quality_requirements: Optional[QualityRequirements]
    ) -> List[Dict[str, Any]]:
        """Fetch raw market list from Polymarket API.

        Args:
            session: HTTP session
            limit: Maximum markets to fetch
            quality_requirements: Quality constraints

        Returns:
            List of market dictionaries from API
        """
        url = f"{self.API_BASE}/markets"
        params = {
            "limit": limit,
            "offset": 0,
        }

        # For ground truth, query closed markets sorted by actual resolution time
        if self.require_ground_truth:
            from datetime import timedelta
            lookback_days = self._get_lookback_days(quality_requirements)

            # Query only closed markets, sorted by closedTime (most recent first)
            params["closed"] = "true"
            params["order"] = "closedTime"
            params["ascending"] = "false"
            logger.info(f"API filtering for closed markets sorted by closedTime (most recent first)")

        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as response:
            if response.status != 200:
                logger.error(f"Polymarket Gamma API returned {response.status}")
                return []

            # Gamma API returns array directly
            market_list = await response.json()

            if not isinstance(market_list, list):
                logger.error(f"Unexpected response format: {type(market_list)}")
                return []

            logger.info(f"Polymarket Gamma API returned {len(market_list)} markets")

            # Log filtering criteria for ground truth
            if self.require_ground_truth:
                from datetime import timedelta
                lookback_days = self._get_lookback_days(quality_requirements)
                min_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
                logger.info(f"Client-side filter: {min_date.strftime('%Y-%m-%d')} <= closedTime <= now ({lookback_days} days)")

            # Debug: Check sample market
            if market_list:
                sample = market_list[0]
                logger.info(f"Sample: closed={sample.get('closed')}, endDate={sample.get('endDate')}, umaEndDate={sample.get('umaEndDate')}, closedTime={sample.get('closedTime')}, question={sample.get('question', 'N/A')[:60]}")

            return market_list

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

            # Apply cached categorizations from previous calls to avoid re-categorizing
            cached_count = 0
            for q in questions:
                if q.id in self._categorization_cache:
                    domain, category = self._categorization_cache[q.id]
                    q.domain = domain
                    if not hasattr(q, 'metadata') or q.metadata is None:
                        q.metadata = {}
                    q.metadata["category"] = category
                    cached_count += 1

            if cached_count > 0:
                logger.info(f"Applied {cached_count} cached categorizations (skipping re-categorization)")

            # Separate questions into: need categorization vs already categorized
            need_categorization = [q for q in questions if q.id not in self._categorization_cache]
            already_categorized = [q for q in questions if q.id in self._categorization_cache]

            # Combine back together
            questions = need_categorization + already_categorized

            # Iterative enhancement: enhance in small batches, only as needed
            # Only categorize questions that need it (not already cached)
            enhanced_questions = []
            remaining_questions = need_categorization[:]  # Only enhance uncategorized questions
            already_enhanced = already_categorized[:]  # Keep already categorized ones

            if self.use_agent_enhancement and remaining_questions:
                try:
                    # Use efficient batch size for categorization
                    # For gap-filling (small count), use smaller batches to avoid waste
                    # For bulk collection (large count), use larger batches for efficiency
                    batch_size = min(50, max(count * 2, 10))

                    while remaining_questions and len(enhanced_questions) < count * 3:
                        # Take next batch
                        batch = remaining_questions[:batch_size]
                        remaining_questions = remaining_questions[batch_size:]

                        logger.info(f"Enhancing batch of {len(batch)} questions ({len(enhanced_questions)} enhanced so far)...")
                        batch_enhanced = await self._enhance_with_agent(batch)

                        # Cache the categorizations
                        for q in batch_enhanced:
                            if q.domain and q.metadata and q.metadata.get("category"):
                                self._categorization_cache[q.id] = (q.domain, q.metadata["category"])

                        enhanced_questions.extend(batch_enhanced)

                        # Try filtering with what we have so far (including already enhanced from cache)
                        all_enhanced_so_far = enhanced_questions + already_enhanced
                        filtered = self._filter_questions(
                            all_enhanced_so_far,
                            type_filter=type_filter,
                            category_filter=category_filter,
                            quality_requirements=quality_requirements,
                        )

                        # If we have enough after filtering, stop enhancing
                        if len(filtered) >= count:
                            logger.info(f"Found {len(filtered)} matching questions after enhancing {len(enhanced_questions)} (+ {len(already_enhanced)} cached), stopping enhancement")
                            break

                    # Add any remaining unenhanced questions as fallback + already enhanced from cache
                    questions = enhanced_questions + already_enhanced + remaining_questions

                except Exception as e:
                    logger.warning(f"Agent enhancement failed: {e}, using questions as-is")
                    questions = enhanced_questions + already_enhanced + remaining_questions if enhanced_questions else (already_enhanced + need_categorization)
            else:
                # No enhancement, use all questions (already cached + new uncategorized)
                questions = already_enhanced + need_categorization

            # Final filtering
            filtered = self._filter_questions(
                questions,
                type_filter=type_filter,
                category_filter=category_filter,
                quality_requirements=quality_requirements,
            )

            # Smart sampling by type if type_filter specified
            if type_filter and len(filtered) > count:
                # Try to get diverse types
                final = []
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
                # Return up to count
                final = filtered[:count]

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
            async with aiohttp.ClientSession() as session:
                # Fetch market list from API
                market_list = await self._fetch_market_list_from_api(session, limit, quality_requirements)

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
                    closed_time = self._parse_market_close_time(market)

                    # Filter based on mode (ground truth vs prediction)
                    should_skip, skip_reason = self._should_skip_market(market, end_date, closed_time, quality_requirements)
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

        Args:
            mq: Market question to map

        Returns:
            Question instance
        """
        # Use configured mappings
        domain = self.category_map.get(mq.category, Domain.GENERAL) if mq.category else Domain.GENERAL

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
            "category": mq.category or "general",
            "options": mq.options,
            **extra_metadata,  # Includes clob_token_ids and other market data
        }

        return Question(
            id=f"polymarket_{mq.market_id}",
            question_text=mq.question_text,
            question_type=self.type_map.get(mq.question_type, QuestionType.BOOLEAN),
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
        # Polymarket primarily has boolean and multiple choice
        if question_type:
            return question_type in ["boolean", "multiple_choice"]
        return True