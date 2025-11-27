"""Prediction market question source runners.

Imports questions directly from prediction markets like Polymarket and Metaculus.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import json
import aiohttp
from pydantic import BaseModel

from .base import QuestionSourceRunner, CollectionResult
from src.domain.models import Question
from src.config.collection_goal import QualityRequirements
from src.utils.logging import logger


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

    def __init__(
        self,
        min_volume_usd: float = 0.0,  # Relaxed - many markets lack volume data
        use_agent_enhancement: bool = True,
        require_ground_truth: bool = True,
    ):
        """Initialize Polymarket runner.

        Args:
            min_volume_usd: Minimum trading volume filter (0 = no filter)
            use_agent_enhancement: Use LLM agent to categorize and enhance questions
            require_ground_truth: If True, fetch resolved markets with outcomes. If False, fetch active future markets.
        """
        super().__init__(source_name="polymarket")
        self.min_volume_usd = min_volume_usd
        self.use_agent_enhancement = use_agent_enhancement
        self.require_ground_truth = require_ground_truth

    async def collect(
        self,
        count: int,
        type_filter: Optional[List[str]] = None,
        category_filter: Optional[List[str]] = None,
        quality_requirements: Optional[QualityRequirements] = None,
        existing_question_ids: Optional[set] = None,
    ) -> CollectionResult:
        """Collect questions from Polymarket.

        Args:
            count: Target number of questions
            type_filter: Only collect these question types
            category_filter: Only collect these categories
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

            # Early deduplication (before expensive categorization!)
            if existing_question_ids is not None:
                before_dedup = len(questions)
                questions = [q for q in questions if q.id not in existing_question_ids]

                if before_dedup != len(questions):
                    logger.info(f"Filtered out {before_dedup - len(questions)} duplicates before categorization")
                    logger.debug(f"Remaining: {len(questions)} unique questions")

                # Note: Don't add to existing_question_ids here - let orchestrator do it
                # after confirming questions are actually being collected

            if not questions:
                logger.warning("No questions remaining after deduplication")
                return CollectionResult(
                    source_name=self.source_name,
                    questions=[],
                    requested_count=count,
                    actual_count=0,
                    success=True,
                    metadata={"all_duplicates": True},
                )

            # Iterative enhancement: enhance in small batches, only as needed
            enhanced_questions = []
            remaining_questions = questions[:]

            if self.use_agent_enhancement and questions:
                try:
                    batch_size = count * 2  # Enhance 2x what we need per batch

                    while remaining_questions and len(enhanced_questions) < count * 3:
                        # Take next batch
                        batch = remaining_questions[:batch_size]
                        remaining_questions = remaining_questions[batch_size:]

                        logger.info(f"Enhancing batch of {len(batch)} questions ({len(enhanced_questions)} enhanced so far)...")
                        batch_enhanced = await self._enhance_with_agent(batch)
                        enhanced_questions.extend(batch_enhanced)

                        # Try filtering with what we have so far
                        filtered = self._filter_questions(
                            enhanced_questions,
                            type_filter=type_filter,
                            category_filter=category_filter,
                            quality_requirements=quality_requirements,
                        )

                        # If we have enough after filtering, stop enhancing
                        if len(filtered) >= count:
                            logger.info(f"Found {len(filtered)} matching questions after enhancing {len(enhanced_questions)}, stopping enhancement")
                            break

                    # Add any remaining unenhanced questions as fallback
                    questions = enhanced_questions + remaining_questions

                except Exception as e:
                    logger.warning(f"Agent enhancement failed: {e}, using questions as-is")
                    questions = enhanced_questions + remaining_questions if enhanced_questions else questions

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
                url = f"{self.API_BASE}/markets"
                params = {
                    "limit": limit,
                    "offset": 0,  # Start from beginning
                }

                # Note: The 'closed' API parameter doesn't reliably filter markets
                # We filter by the 'closed' field in the response data instead

                # For ground truth, filter by API to get markets with recent endDate
                if self.require_ground_truth:
                    from datetime import timedelta
                    lookback_days = 180
                    if quality_requirements and quality_requirements.min_resolution_days < 0:
                        lookback_days = abs(quality_requirements.min_resolution_days)
                    min_date = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
                    params["end_date_min"] = min_date
                    logger.info(f"API filtering for markets with endDate >= {min_date}")

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
                        lookback_days = 180
                        if quality_requirements and quality_requirements.min_resolution_days < 0:
                            lookback_days = abs(quality_requirements.min_resolution_days)
                        min_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
                        logger.info(f"Filtering for resolved markets with endDate >= {min_date.strftime('%Y-%m-%d')} (no upper limit)")

                    # Debug: Check sample market
                    if market_list:
                        sample = market_list[0]
                        logger.info(f"Sample: closed={sample.get('closed')}, endDate={sample.get('endDate')}, question={sample.get('question', 'N/A')[:60]}")

                    parsed_count = 0
                    skipped_not_closed = 0  # For ground truth mode: markets not yet closed/resolved
                    skipped_closed = 0  # For prediction mode: markets already closed
                    skipped_past = 0  # Markets with dates outside target range
                    skipped_volume = 0
                    failed_parse = 0

                    for market in market_list:
                        # Parse end date (needed for all markets)
                        try:
                            end_date_str = market.get("endDate")
                            if not end_date_str:
                                failed_parse += 1
                                continue

                            end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                        except Exception as e:
                            failed_parse += 1
                            logger.debug(f"Failed to parse endDate: {e}")
                            continue

                        # Filter based on mode (ground truth vs prediction)
                        if self.require_ground_truth:
                            # For ground truth: need closed markets with resolved outcomes
                            # Check 1: Must be closed (resolved)
                            if not market.get("closed"):
                                skipped_not_closed += 1
                                continue

                            # Check 2: Must have outcome prices (indicates actual resolution)
                            outcome_prices_str = market.get("outcomePrices", "")
                            if not outcome_prices_str or outcome_prices_str == "[]":
                                skipped_not_closed += 1
                                continue

                            # Check 3: endDate should not be too old
                            # Note: We accept future endDates for early-resolved markets
                            from datetime import timedelta
                            now = datetime.now(timezone.utc)

                            lookback_days = 180  # Default to last 6 months
                            if quality_requirements and quality_requirements.min_resolution_days < 0:
                                lookback_days = abs(quality_requirements.min_resolution_days)

                            min_date = now - timedelta(days=lookback_days)

                            # Only skip if endDate is TOO old (before min_date)
                            if end_date < min_date:
                                skipped_past += 1
                                continue
                        else:
                            # For predictions: need open markets with future resolution
                            # Skip closed markets
                            if market.get("closed"):
                                skipped_closed += 1
                                continue

                            # Skip markets that already ended
                            if end_date < datetime.now(timezone.utc):
                                skipped_past += 1
                                continue

                        # Get volume (Gamma API provides volumeNum)
                        volume = market.get("volumeNum", 0.0) or 0.0

                        # Apply volume filter (relaxed - many markets don't have volume data)
                        # Only filter if we have volume data AND it's below threshold
                        if volume > 0 and volume < self.min_volume_usd:
                            skipped_volume += 1
                            continue

                        # Parse market
                        try:
                            question_text = market.get("question")
                            if not question_text:
                                failed_parse += 1
                                continue

                            # Get description (resolution criteria)
                            description = market.get("description", "")
                            if not description:
                                # Fallback: try to get from events
                                events = market.get("events", [])
                                if events and isinstance(events, list) and len(events) > 0:
                                    description = events[0].get("description", "")

                            # Use description as resolution criteria, with fallback
                            resolution_criteria = description if description else f"See https://polymarket.com/event/{market.get('slug', '')}"

                            # Gamma API doesn't provide outcomes directly - assume binary for now
                            # More complex markets would need additional API calls
                            question_type = "boolean"

                            # Extract ground truth for resolved markets
                            ground_truth = None
                            resolution_reasoning = None
                            if market.get("closed") and self.require_ground_truth:
                                # Parse outcomePrices to determine winning outcome
                                try:
                                    import json as json_module
                                    outcome_prices_str = market.get("outcomePrices", "")
                                    if outcome_prices_str:
                                        outcome_prices = json_module.loads(outcome_prices_str)
                                        outcomes = json_module.loads(market.get("outcomes", '["Yes", "No"]'))

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

                            mq = MarketQuestion(
                                market_id=market.get("conditionId", market.get("id")),  # camelCase
                                market_source="polymarket",
                                question_text=question_text,
                                question_type=question_type,
                                resolution_criteria=resolution_criteria,
                                close_time=end_date,
                                current_probability=market.get("lastTradePrice"),  # Use last trade price as proxy
                                volume_usd=volume if volume > 0 else None,
                                liquidity_usd=market.get("liquidityNum"),
                                category=market.get("category"),  # Gamma provides category directly
                                options=["Yes", "No"],  # Default for binary markets
                                metadata={
                                    "market_slug": market.get("slug"),
                                    "tags": market.get("tags", []),
                                    "active": market.get("active"),
                                    "events": market.get("events", []),
                                    "categories": market.get("categories", []),
                                    "ground_truth": ground_truth,  # Store ground truth in metadata
                                    "resolution_reasoning": resolution_reasoning,
                                    "closed": market.get("closed", False),
                                },
                            )
                            markets.append(mq)
                            parsed_count += 1
                        except Exception as e:
                            failed_parse += 1
                            logger.debug(f"Failed to parse market {market.get('question', 'unknown')}: {e}")

                    if self.require_ground_truth:
                        logger.info(
                            f"Polymarket parsing: {parsed_count} markets parsed, "
                            f"{skipped_not_closed} not closed/resolved, {skipped_past} wrong date, "
                            f"{skipped_volume} low volume, {failed_parse} failed"
                        )
                    else:
                        logger.info(
                            f"Polymarket parsing: {parsed_count} markets parsed, "
                            f"{skipped_closed} already closed, {skipped_past} wrong date, "
                            f"{skipped_volume} low volume, {failed_parse} failed"
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
        from src.domain.models.domain import Domain

        # Map question types
        type_map = {
            "boolean": "boolean",
            "binary": "boolean",
            "multiple_choice": "multiple_choice",
        }

        # Map category to Domain enum (will be enhanced by agent later)
        category_to_domain = {
            "finance": Domain.FINANCE,
            "technology": Domain.TECH,
            "tech": Domain.TECH,
            "politics": Domain.POLITICS,
            "science": Domain.HEALTH,  # Map science to health for now
            "sports": Domain.SPORTS,
            "other": Domain.GENERAL,
        }

        domain = category_to_domain.get(mq.category, Domain.GENERAL) if mq.category else Domain.GENERAL

        # Extract ground truth from metadata if available
        ground_truth = mq.metadata.get("ground_truth") if mq.metadata else None
        resolution_reasoning = mq.metadata.get("resolution_reasoning") if mq.metadata else None

        return Question(
            id=f"polymarket_{mq.market_id}",
            question_text=mq.question_text,
            question_type=type_map.get(mq.question_type, "boolean"),
            domain=domain,
            difficulty=self._estimate_difficulty(mq),
            resolution_date=mq.resolution_time or mq.close_time,
            cutoff_date=mq.close_time,
            created_at=datetime.now(timezone.utc),
            ground_truth=ground_truth,  # Use ground truth from metadata
            resolution_reasoning=resolution_reasoning,  # Add resolution reasoning
            resolution_criteria=mq.resolution_criteria,
            target_event_id=None,
            related_event_ids=[],
            metadata={
                "source": "polymarket",
                "market_id": mq.market_id,
                "current_probability": mq.current_probability,
                "volume_usd": mq.volume_usd,
                "liquidity_usd": mq.liquidity_usd,
                "category": mq.category,
                "options": mq.options,
                **mq.metadata,
            },
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


class MetaculusRunner(QuestionSourceRunner):
    """Question source from Metaculus prediction platform."""

    API_BASE = "https://www.metaculus.com/api2"

    def __init__(
        self,
        min_predictions: int = 10,
        use_agent_enhancement: bool = True,
    ):
        """Initialize Metaculus runner.

        Args:
            min_predictions: Minimum number of predictions (quality filter)
            use_agent_enhancement: Use LLM agent to categorize questions
        """
        super().__init__(source_name="metaculus")
        self.min_predictions = min_predictions
        self.use_agent_enhancement = use_agent_enhancement

    async def collect(
        self,
        count: int,
        type_filter: Optional[List[str]] = None,
        category_filter: Optional[List[str]] = None,
        quality_requirements: Optional[QualityRequirements] = None,
        existing_question_ids: Optional[set] = None,
    ) -> CollectionResult:
        """Collect questions from Metaculus.

        Args:
            count: Target number of questions
            type_filter: Only collect these question types
            category_filter: Only collect these categories
            quality_requirements: Quality constraints
            existing_question_ids: Set of existing IDs to skip

        Returns:
            CollectionResult with Metaculus questions
        """
        try:
            logger.info(f"MetaculusRunner: Fetching up to {count} questions")

            # Fetch questions
            market_questions = await self._fetch_questions(limit=count * 2)

            # Map to Question model
            questions = []
            for mq in market_questions:
                try:
                    question = self._map_to_question(mq)
                    questions.append(question)
                except Exception as e:
                    logger.warning(f"Failed to map question {mq.market_id}: {e}")

            # Tag with source
            self._tag_questions_with_source(questions)

            # Agent enhancement (categorization, quality improvement)
            if self.use_agent_enhancement and questions:
                try:
                    questions = await self._enhance_with_agent(questions)
                except Exception as e:
                    logger.warning(f"Agent enhancement failed: {e}, using questions as-is")

            # Apply filters
            filtered = self._filter_questions(
                questions,
                type_filter=type_filter,
                category_filter=category_filter,
                quality_requirements=quality_requirements,
            )

            # Return up to count
            final = filtered[:count]

            logger.info(
                f"Metaculus: {len(final)}/{count} questions collected "
                f"({len(questions)} fetched, {len(filtered)} after filter)"
            )

            return CollectionResult(
                source_name=self.source_name,
                questions=final,
                requested_count=count,
                actual_count=len(final),
                success=True,
                metadata={
                    "questions_fetched": len(market_questions),
                    "questions_mapped": len(questions),
                    "questions_filtered": len(filtered),
                },
            )

        except Exception as e:
            logger.error(f"MetaculusRunner error: {e}")
            return CollectionResult(
                source_name=self.source_name,
                questions=[],
                requested_count=count,
                actual_count=0,
                success=False,
                error_message=str(e),
            )

    async def _fetch_questions(self, limit: int = 100) -> List[MarketQuestion]:
        """Fetch questions from Metaculus API.

        Args:
            limit: Maximum questions to fetch

        Returns:
            List of MarketQuestion objects
        """
        questions = []

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.API_BASE}/questions/"
                params = {
                    "status": "open",
                    "order_by": "-activity",
                    "limit": limit,
                }

                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status != 200:
                        logger.error(f"Metaculus API returned {response.status}")
                        return []

                    data = await response.json()
                    metaculus_questions = data.get("results", [])

                    for q in metaculus_questions:
                        # Filter by prediction count
                        num_predictions = q.get("number_of_predictions", 0)
                        if num_predictions < self.min_predictions:
                            continue

                        # Determine type
                        q_type = q.get("possibilities", {}).get("type", "binary")
                        type_map = {
                            "binary": "boolean",
                            "continuous": "quantity",
                            "date": "timeframe",
                            "multiple_choice": "multiple_choice",
                        }

                        try:
                            close_time = datetime.fromisoformat(
                                q["close_time"].replace("Z", "+00:00")
                            )
                            resolve_time = None
                            if q.get("resolve_time"):
                                resolve_time = datetime.fromisoformat(
                                    q["resolve_time"].replace("Z", "+00:00")
                                )

                            mq = MarketQuestion(
                                market_id=str(q["id"]),
                                market_source="metaculus",
                                question_text=q["title"],
                                question_type=type_map.get(q_type, "boolean"),
                                resolution_criteria=q.get("resolution_criteria", ""),
                                close_time=close_time,
                                resolution_time=resolve_time,
                                current_probability=q.get("community_prediction", {}).get("q2"),
                                category=q.get("category", "other"),
                                options=q.get("possibilities", {}).get("choices"),
                                metadata={
                                    "question_url": f"https://www.metaculus.com/questions/{q['id']}",
                                    "num_predictions": num_predictions,
                                    "publish_time": q.get("publish_time"),
                                },
                            )
                            questions.append(mq)
                        except Exception as e:
                            logger.debug(f"Failed to parse question: {e}")

        except Exception as e:
            logger.error(f"Error fetching Metaculus questions: {e}")

        return questions

    def _map_to_question(self, mq: MarketQuestion) -> Question:
        """Map MarketQuestion to Question model.

        Args:
            mq: Market question

        Returns:
            Question instance
        """
        from src.domain.models.domain import Domain

        type_map = {
            "boolean": "boolean",
            "quantity": "quantity",
            "timeframe": "timeframe",
            "multiple_choice": "multiple_choice",
        }

        # Map category to Domain enum (will be enhanced by agent later)
        category_to_domain = {
            "finance": Domain.FINANCE,
            "technology": Domain.TECH,
            "tech": Domain.TECH,
            "politics": Domain.POLITICS,
            "science": Domain.HEALTH,
            "health": Domain.HEALTH,
            "sports": Domain.SPORTS,
            "culture": Domain.CULTURE,
            "business": Domain.BUSINESS,
            "other": Domain.GENERAL,
        }

        domain = category_to_domain.get(mq.category, Domain.GENERAL) if mq.category else Domain.GENERAL

        return Question(
            id=f"metaculus_{mq.market_id}",
            question_text=mq.question_text,
            question_type=type_map.get(mq.question_type, "boolean"),
            domain=domain,
            difficulty=3,  # Default medium difficulty
            resolution_date=mq.resolution_time or mq.close_time,
            cutoff_date=mq.close_time,
            created_at=datetime.now(timezone.utc),
            ground_truth=None,
            resolution_criteria=mq.resolution_criteria,
            target_event_id=None,
            related_event_ids=[],
            metadata={
                "source": "metaculus",
                "market_id": mq.market_id,
                "current_probability": mq.current_probability,
                "category": mq.category,
                "options": mq.options,
                **mq.metadata,
            },
        )

    async def can_provide(
        self,
        question_type: Optional[str] = None,
        category: Optional[str] = None,
    ) -> bool:
        """Check if Metaculus can provide questions of given type/category.

        Args:
            question_type: Question type to check
            category: Category to check

        Returns:
            True if type/category is supported
        """
        # Metaculus supports all question types
        return True
