"""Prediction market question source runners.

Imports questions directly from prediction markets like Polymarket and Metaculus.
Refactored to use modular client and parser utilities (flat hierarchy pattern).
"""

from typing import List, Optional, Dict, Any, Union
from datetime import datetime, timezone
import json
from pydantic import BaseModel

from .runner_base import QuestionSourceRunner, CollectionResult
from src.integrations.polymarket_client import PolymarketClient
from src.integrations.polymarket_parser import MarketParser
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
        Domain.CULTURE: ["entertainment", "music", "movies"],
        Domain.HEALTH: ["health", "pandemic"],
        Domain.SCIENCE: ["science"],
        Domain.BUSINESS: ["business"],
        Domain.CLIMATE: ["climate", "weather"],
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

    def _infer_domain_from_tags(self, event: Dict[str, Any]) -> Optional[Domain]:
        """Infer domain from event tags by matching against DOMAIN_TO_TAG_SLUGS.

        Returns the first matching Domain, or None if no match found.
        """
        event_tags = {
            tag.get("slug") for tag in event.get("tags", []) if tag.get("slug")
        }
        if not event_tags:
            return None

        for domain, slugs in self.DOMAIN_TO_TAG_SLUGS.items():
            if domain == Domain.GENERAL:
                continue  # Skip "all" catch-all
            if any(slug in event_tags for slug in slugs):
                return domain
        return None

    async def _fetch_markets_by_category(
        self,
        category_filter: Optional[Union[Dict[str, int], List[str]]],
        limit: int,
        quality_requirements: Optional[QualityRequirements] = None,
    ) -> List[MarketQuestion]:
        """Fetch and parse events by category, with client-side filtering and aggregation."""
        if not category_filter:
            return await self._fetch_markets(
                limit=limit, quality_requirements=quality_requirements
            )

        # Determine which domains are being requested.
        if isinstance(category_filter, dict):
            requested_domains = [Domain(cat) for cat in category_filter.keys()]
        else:
            requested_domains = [Domain(cat) for cat in category_filter]

        # Fetch a broad pool of events to filter through. The `/events` endpoint
        # is less granular, so we fetch more and then apply filters.
        # The limit is adjusted to ensure enough data is available after filtering.
        fetch_limit = limit * 5
        all_events = await self.client.fetch_events(
            limit=fetch_limit, closed=self.require_ground_truth
        )

        all_market_questions = []
        domain_tags = {
            domain: self.DOMAIN_TO_TAG_SLUGS.get(domain, [])
            for domain in requested_domains
        }

        # Perform client-side filtering to find events matching the requested domains.
        for event in all_events:
            event_tags = {tag.get("slug") for tag in event.get("tags", [])}
            for domain, tags in domain_tags.items():
                if any(tag in event_tags for tag in tags):
                    # If an event matches, parse it using the aggregation-aware helper.
                    parsed_questions = self._parse_event_structure(
                        event, quality_requirements
                    )
                    for mq in parsed_questions:
                        # Assign the matched domain, as this is known from the filter.
                        mq.metadata["known_domain"] = domain.value
                        all_market_questions.append(mq)
                    break  # Avoid parsing the same event for multiple domains.

        logger.info(
            f"Parsed {len(all_market_questions)} questions after filtering {len(all_events)} events by domain."
        )
        return all_market_questions

    def _parse_single_market(
        self,
        market: Dict[str, Any],
        end_date: datetime,
        closed_time: Optional[datetime],
    ) -> Optional[MarketQuestion]:
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

            # Skip template/placeholder markets with no trading activity
            # These are created by Polymarket but never properly configured
            volume = market.get("volume")
            if volume is None:
                volume = market.get("volumeNum")

            liquidity = market.get("liquidity")
            if liquidity is None:
                liquidity = market.get("liquidityNum")

            # Filter out markets with no volume AND no liquidity (likely templates)
            if (volume is None or volume == 0 or volume == "0") and (
                liquidity is None or liquidity == 0 or liquidity == "0"
            ):
                logger.info(
                    f"Filtering template market (vol={volume}, liq={liquidity}): {question_text[:80]}"
                )
                return None

            # Get description (resolution criteria)
            description = market.get("description", "")
            if not description:
                # Fallback: try to get from events
                events = market.get("events", [])
                if events and isinstance(events, list) and len(events) > 0:
                    description = events[0].get("description", "")

            # Use description as resolution criteria, with fallback
            resolution_criteria = (
                description
                if description
                else f"See https://polymarket.com/event/{market.get('slug', '')}"
            )

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
            ground_truth, resolution_reasoning = self.parser.extract_ground_truth(
                market, outcomes
            )

            # Get volume
            volume = market.get("volumeNum", 0.0) or 0.0

            # Parse CLOB token IDs for price history
            clob_ids_raw = market.get("clobTokenIds", "[]")
            clob_ids = (
                json.loads(clob_ids_raw)
                if isinstance(clob_ids_raw, str)
                else clob_ids_raw
            )

            # Extract estimated start time from startDate
            start_date_str = market.get("startDate")
            estimated_start = None
            if start_date_str:
                try:
                    estimated_start = parse_iso_datetime(start_date_str)
                    logger.debug(
                        f"Market {market.get('id')}: startDate={estimated_start}"
                    )
                except Exception as e:
                    logger.debug(f"Failed to parse startDate: {e}")

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
                    "start_date": estimated_start.isoformat()
                    if estimated_start
                    else None,  # Store for estimated_start_time
                    "closed": market.get("closed", False),
                },
            )
        except Exception as e:
            logger.debug(
                f"Failed to parse market {market.get('question', 'unknown')}: {e}"
            )
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
            # Filter by status to get resolved markets (for ground truth) or active markets (for predictions)
            # Use same parameters as Polymarket's official website for consistent results
            search_results = await self.client.search_markets(
                query=search_query,
                limit_per_type=count * 2,  # Fetch more to account for filtering
                events_status="resolved" if self.require_ground_truth else "active",
                result_type="events",  # Filter to events only
                sort="closed_time",  # Sort by most recently closed
                presets=["EventsTitle", "Events"],  # Get full event data
            )

            # Use quality_requirements lookback window if provided
            # For search queries, user can control how far back to search
            if quality_requirements is None:
                quality_requirements = QualityRequirements()
            search_quality = quality_requirements

            # Extract markets from events in search results
            events = search_results.get("events", [])
            logger.info(f"Search returned {len(events)} events")
            market_questions = []
            for event in events:
                # Use shared event parsing logic (handles aggregation)
                mqs = self._parse_event_structure(event, search_quality)
                market_questions.extend(mqs)

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

    @staticmethod
    def _parse_identifier(identifier: str) -> Dict[str, str]:
        """Normalize a user-supplied Polymarket identifier.

        Accepts:
        - Event URLs: https://polymarket.com/event/<event-slug>[/<market-slug>]
        - Bare slugs: <event-slug> or <market-slug>
        - Numeric ids: 12345 (treated as both event-id and market-id candidates)

        Returns:
            Dict with optional keys 'event_slug', 'market_slug', 'numeric_id', 'raw'.
        """
        raw = identifier.strip()
        result: Dict[str, str] = {"raw": raw}

        if raw.startswith("http://") or raw.startswith("https://"):
            # Strip query/fragment, then split the path
            path = raw.split("?", 1)[0].split("#", 1)[0]
            parts = [p for p in path.split("/") if p]
            if "event" in parts:
                idx = parts.index("event")
                slugs = parts[idx + 1 :]
                if len(slugs) >= 1:
                    result["event_slug"] = slugs[0]
                if len(slugs) >= 2:
                    result["market_slug"] = slugs[1]
            elif "market" in parts:
                idx = parts.index("market")
                if idx + 1 < len(parts):
                    result["market_slug"] = parts[idx + 1]
            return result

        if raw.isdigit():
            result["numeric_id"] = raw
            return result

        # Bare slug — could be an event or market slug; try event first.
        result["event_slug"] = raw
        result["market_slug"] = raw
        return result

    async def _resolve_identifier_to_events(
        self, identifier: str
    ) -> List[Dict[str, Any]]:
        """Resolve a single identifier to one or more event-shaped dicts.

        Markets resolved on their own are wrapped in a synthetic single-market
        event so they can flow through ``_parse_event_structure`` unchanged.
        """
        parsed = self._parse_identifier(identifier)

        # 1. Try event by slug
        if parsed.get("event_slug"):
            events = await self.client.fetch_events_by_slug(parsed["event_slug"])
            if events:
                return events

        # 2. Try event by numeric id
        if parsed.get("numeric_id"):
            event = await self.client.fetch_event_by_id(parsed["numeric_id"])
            if event and event.get("markets"):
                return [event]

        # 3. Try market by slug -> wrap in synthetic event
        if parsed.get("market_slug"):
            markets = await self.client.fetch_markets_by_slug(parsed["market_slug"])
            if markets:
                return [{"title": markets[0].get("question"), "markets": markets}]

        # 4. Try market by numeric id -> wrap in synthetic event
        if parsed.get("numeric_id"):
            market = await self.client.fetch_market_by_id(parsed["numeric_id"])
            if market:
                return [{"title": market.get("question"), "markets": [market]}]

        logger.warning(f"Could not resolve Polymarket identifier: {identifier}")
        return []

    async def collect_by_identifiers(
        self,
        identifiers: List[str],
        existing_question_ids: Optional[set] = None,
    ) -> CollectionResult:
        """Collect specific Polymarket questions by slug, URL, or numeric id.

        Unlike the goal/search collectors, this fetches exactly the markets the
        caller names — no quality filtering or target counts.

        Args:
            identifiers: Event/market slugs, polymarket.com URLs, or numeric ids
            existing_question_ids: Set of existing IDs to skip

        Returns:
            CollectionResult with the resolved questions
        """
        questions: List[Question] = []
        errors: List[str] = []
        seen_ids: set = set()

        # No quality filtering — the user picked these explicitly.
        quality = QualityRequirements()
        quality.min_resolution_days = -36500  # ~100y lookback, effectively unbounded

        for identifier in identifiers:
            try:
                events = await self._resolve_identifier_to_events(identifier)
                if not events:
                    errors.append(f"Not found: {identifier}")
                    continue

                for event in events:
                    mqs = self._parse_event_structure(event, quality)
                    # Infer domain from event tags when available
                    for mq in mqs:
                        if not (mq.metadata and mq.metadata.get("known_domain")):
                            inferred = self._infer_domain_from_tags(event)
                            if inferred:
                                mq.metadata["known_domain"] = inferred.value
                    for mq in mqs:
                        try:
                            question = self._map_to_question(mq)
                        except Exception as e:
                            errors.append(f"{identifier}: map failed ({e})")
                            continue
                        if question.id in seen_ids:
                            continue
                        seen_ids.add(question.id)
                        questions.append(question)

            except Exception as e:
                logger.error(f"Failed to resolve identifier '{identifier}': {e}")
                errors.append(f"{identifier}: {e}")

        if existing_question_ids:
            questions = [q for q in questions if q.id not in existing_question_ids]

        return CollectionResult(
            source_name=self.source_name,
            questions=questions,
            requested_count=len(identifiers),
            actual_count=len(questions),
            success=len(questions) > 0,
            error_message="; ".join(errors) if errors else None,
        )

    async def collect(
        self,
        count: int,
        type_filter: Optional[List[str]] = None,
        category_filter: Optional[Union[Dict[str, int], List[str]]] = None,
        quality_requirements: Optional[QualityRequirements] = None,
        existing_question_ids: Optional[set] = None,
        time_horizon_hints: Optional[List[str]] = None,
    ) -> CollectionResult:
        """Collect questions from Polymarket.

        Args:
            count: Target number of questions
            type_filter: Only collect these question types
            category_filter: Dict mapping categories to number still needed
            quality_requirements: Quality constraints
            existing_question_ids: Set of existing IDs to skip
            time_horizon_hints: Priority time horizons (used for post-filtering)

        Returns:
            CollectionResult with Polymarket questions
        """
        try:
            logger.info(
                f"PolymarketRunner: Fetching up to {count} questions (require_ground_truth={self.require_ground_truth})"
            )

            # Use tag-based fetching if category filter is provided
            # This eliminates the need for LLM categorization!
            if category_filter:
                logger.info(
                    f"Using tag-based fetching for categories: {category_filter}"
                )
                # Use same multiplier as non-category fetch (count * 20 for ground truth mode)
                fetch_limit = count * 20 if self.require_ground_truth else count * 5
                market_questions = await self._fetch_markets_by_category(
                    category_filter=category_filter,
                    limit=fetch_limit,
                    quality_requirements=quality_requirements,
                )
            else:
                # Fetch market questions - fetch many to have options
                fetch_limit = count * 20 if self.require_ground_truth else count * 5
                market_questions = await self._fetch_markets(
                    limit=fetch_limit, quality_requirements=quality_requirements
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
                    logger.info(
                        f"Early duplicate filter: removed {before_dedup - len(questions)} duplicates before processing"
                    )

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
            logger.info(
                f"Filtered from {len(questions)} down to {len(filtered)} questions after applying type/category/quality filters"
            )

            # Apply time horizon post-filtering if hints provided
            if time_horizon_hints and filtered:
                from .progress import classify_question_time_horizon

                before_horizon = len(filtered)
                horizon_filtered = [
                    q
                    for q in filtered
                    if classify_question_time_horizon(q) in time_horizon_hints
                ]
                if horizon_filtered:
                    logger.info(
                        f"Time horizon filter: {before_horizon} -> {len(horizon_filtered)} "
                        f"(keeping {time_horizon_hints})"
                    )
                    filtered = horizon_filtered
                else:
                    logger.warning(
                        f"No questions match time horizons {time_horizon_hints}, "
                        f"keeping all {len(filtered)} questions"
                    )

            # Smart sampling by type and/or category if filters specified
            if (type_filter or category_filter) and len(filtered) > count:
                final = []

                # Priority 1: Sample by category if category_filter is provided
                # This ensures we get diverse categories instead of all from one category
                if category_filter:
                    by_category = {}
                    for q in filtered:
                        cat = (
                            q.domain.value
                            if hasattr(q.domain, "value")
                            else str(q.domain)
                        )
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
        quality_requirements: Optional[QualityRequirements] = None,
    ) -> List[MarketQuestion]:
        """Fetch markets (grouped by event) from Polymarket API.

        Args:
            limit: Maximum events to fetch
            quality_requirements: Quality constraints

        Returns:
            List of MarketQuestion objects
        """
        questions = []

        try:
            # Use fetch_events to get grouped structure
            # Adjust limit because events contain multiple markets
            # Fetching 1000 events might yield 1000+ markets
            events_list = await self.client.fetch_events(
                limit=limit,
                closed=self.require_ground_truth,
                # quality_requirements not passed to fetch_events yet, client handles closed/active
            )

            if not events_list:
                return []

            logger.info(f"Fetched {len(events_list)} events from Polymarket")

            for event in events_list:
                # Parse event structure
                mqs = self._parse_event_structure(event, quality_requirements)
                # Infer domain from event tags for the non-category-filtered path
                for mq in mqs:
                    if not (mq.metadata and mq.metadata.get("known_domain")):
                        inferred = self._infer_domain_from_tags(event)
                        if inferred:
                            mq.metadata["known_domain"] = inferred.value
                questions.extend(mqs)

            logger.info(
                f"Parsed {len(questions)} questions from {len(events_list)} events"
            )

        except Exception as e:
            logger.error(f"Error fetching Polymarket events: {e}")

        return questions

    def _parse_event_structure(
        self, event: Dict[str, Any], quality_requirements: Optional[QualityRequirements]
    ) -> List[MarketQuestion]:
        """Parse an event dictionary into a list of MarketQuestions (aggregating if possible)."""
        markets = event.get("markets", [])
        if not markets:
            return []

        # Aggregation Logic
        if len(markets) > 1:
            # Aggregate into MCQ
            question_text = event.get("title", markets[0].get("question"))
            options = []
            option_map = {}
            valid_markets = []

            for m in markets:
                # Basic validation logic
                end_date_str = m.get("endDate")
                if not end_date_str:
                    continue
                try:
                    end_date = parse_iso_datetime(end_date_str)
                except:
                    continue

                closed_time = self.parser.parse_close_time(m)
                should_skip, _ = self.parser.should_skip_market(
                    m, end_date, closed_time, quality_requirements
                )
                if should_skip:
                    continue

                # Volume/Liquidity Check (filter placeholders)
                volume = m.get("volumeNum", 0.0) or 0.0
                liquidity = m.get("liquidityNum", 0.0) or 0.0

                # Check for "template" markets (no activity)
                if volume <= 0 and liquidity <= 0:
                    continue

                # Apply configured minimum volume filter
                if volume < self.min_volume_usd:
                    continue

                # Use groupItemTitle if available, else question text
                label = m.get("groupItemTitle", m.get("question"))

                # Deduplicate options (sometimes multiple markets map to same label?)
                if label in option_map:
                    continue

                options.append(label)
                option_map[label] = m
                valid_markets.append(m)

            if not valid_markets:
                return []

            # Use primary market for metadata
            primary = valid_markets[0]

            # Ground Truth Logic for MCQ
            ground_truth = None
            resolution_reasoning = None

            for label, m in option_map.items():
                outcomes = self.parser.parse_outcomes(m)
                gt, reason = self.parser.extract_ground_truth(m, outcomes)
                if gt == "Yes":
                    ground_truth = label
                    resolution_reasoning = reason
                    break

            # Total volume
            total_volume = sum(m.get("volumeNum", 0) or 0 for m in valid_markets)
            total_liquidity = sum(m.get("liquidityNum", 0) or 0 for m in valid_markets)

            # Metadata
            
            # Extract clob_token_ids for each option
            clob_token_ids = []
            for label in options:
                m = option_map[label]
                clob_ids_raw = m.get("clobTokenIds", "[]")
                clob_ids = json.loads(clob_ids_raw) if isinstance(clob_ids_raw, str) else clob_ids_raw
                if clob_ids:
                    clob_token_ids.append(clob_ids[0])

            mq = MarketQuestion(
                market_id=f"event_{event.get('id')}",
                market_source="polymarket",
                question_text=question_text,
                question_type="mcq",
                resolution_criteria=primary.get(
                    "description", f"See event {event.get('slug')}"
                ),
                close_time=parse_iso_datetime(primary.get("endDate")),
                resolution_time=self.parser.parse_close_time(primary),
                current_probability=None,
                volume_usd=total_volume,
                liquidity_usd=total_liquidity,
                category=event.get("category"),  # Or primary.get("category")
                options=options,
                metadata={
                    "market_slug": event.get("slug"),
                    "event_id": event.get("id"),
                    "is_aggregated": True,
                    "sub_markets": [m.get("id") for m in valid_markets],
                    "clob_token_ids": clob_token_ids,
                    "ground_truth": ground_truth,
                    "resolution_reasoning": resolution_reasoning,
                    "tags": event.get("tags", []),
                    "active": primary.get("active"),
                    "closed": primary.get("closed"),
                },
            )
            return [mq]

        elif len(markets) == 1:
            # Single market
            m = markets[0]
            end_date_str = m.get("endDate")
            if not end_date_str:
                return []
            try:
                end_date = parse_iso_datetime(end_date_str)
            except:
                return []
            closed_time = self.parser.parse_close_time(m)
            should_skip, _ = self.parser.should_skip_market(
                m, end_date, closed_time, quality_requirements
            )
            if should_skip:
                return []

            mq = self._parse_single_market(m, end_date, closed_time)
            return [mq] if mq else []

        return []

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
        resolution_reasoning = (
            mq.metadata.get("resolution_reasoning") if mq.metadata else None
        )

        # Extract estimated start time from metadata
        estimated_start = None
        if mq.metadata and "start_date" in mq.metadata and mq.metadata["start_date"]:
            try:
                estimated_start = parse_iso_datetime(mq.metadata["start_date"])
            except Exception as e:
                logger.debug(f"Failed to parse start_date from metadata: {e}")

        # Prepare metadata dict with all Polymarket-specific data
        # Remove fields that are already direct Question parameters to avoid conflicts
        extra_metadata = {
            k: v
            for k, v in mq.metadata.items()
            if k not in ("ground_truth", "resolution_reasoning")
        }

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

        # Log options for debugging
        if mq.options:
            logger.debug(
                f"Mapping market {mq.market_id} with {len(mq.options)} options"
            )

        return Question(
            id=f"polymarket_{mq.market_id}",
            question_text=mq.question_text,
            question_type=self.type_map.get(mq.question_type, QuestionType.BINARY),
            domain=domain,
            source="polymarket",
            difficulty=self._estimate_difficulty(mq),
            resolution_date=mq.resolution_time or mq.close_time,
            estimated_start_time=estimated_start,  # When market opened for trading
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
