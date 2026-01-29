"""Parser for Polymarket market data.

Extracts and normalizes data from Polymarket API responses.
Follows flat hierarchy pattern (no subdirectories).
"""

from typing import Dict, Any, List, Optional, Tuple, Union
from datetime import datetime, timezone, timedelta
import json

from src.utils.logging import logger
from src.utils.date_utils import parse_iso_datetime
from src.config.collection_goal import QualityRequirements


class MarketParser:
    """Parses Polymarket market data into standardized format.

    Handles date parsing, outcome extraction, ground truth resolution,
    and market filtering based on quality requirements.
    """

    def __init__(self, require_ground_truth: bool = True):
        """Initialize market parser.

        Args:
            require_ground_truth: If True, parse resolved markets. If False, parse active markets.
        """
        self.require_ground_truth = require_ground_truth

    def parse_close_time(self, market: Dict[str, Any]) -> Optional[datetime]:
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
                    closed_time_str = closed_time_str.replace(" ", "T").replace(
                        "+00", "+00:00"
                    )
                closed_time = datetime.fromisoformat(closed_time_str)
            except Exception as e:
                logger.debug(f"Failed to parse closedTime: {e}")

        return closed_time

    def parse_outcomes(self, market: Dict[str, Any]) -> List[str]:
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
            logger.debug(
                f"Failed to parse outcomes for market {market.get('question', 'unknown')}: {e}"
            )
            return ["Yes", "No"]  # Fallback

    def extract_ground_truth(
        self, market: Dict[str, Any], outcomes: List[str]
    ) -> Tuple[Optional[Union[str, List[str]]], Optional[str]]:
        """Extract ground truth and resolution reasoning from resolved market.

        Args:
            market: Market data from API
            outcomes: List of possible outcomes

        Returns:
            Tuple of (ground_truth, resolution_reasoning).
            ground_truth can be a string (single winner) or list of strings (multiple winners).
        """
        ground_truth = None
        resolution_reasoning = None

        if not market.get("closed") or not self.require_ground_truth:
            return ground_truth, resolution_reasoning

        try:
            outcome_prices_str = market.get("outcomePrices", "")
            if outcome_prices_str:
                outcome_prices = json.loads(outcome_prices_str)

                # Find winning outcomes (price = "1")
                winners = []
                for idx, price in enumerate(outcome_prices):
                    if price == "1" and idx < len(outcomes):
                        winners.append(outcomes[idx])

                if len(winners) == 1:
                    ground_truth = winners[0]
                elif len(winners) > 1:
                    ground_truth = winners

                # Add resolution reasoning
                if ground_truth:
                    resolved_by = market.get("resolvedBy", "")
                    auto_resolved = market.get("automaticallyResolved", False)
                    resolution_method = "automatically" if auto_resolved else "manually"
                    gt_display = (
                        f"'{ground_truth}'"
                        if isinstance(ground_truth, str)
                        else f"{ground_truth}"
                    )
                    resolution_reasoning = (
                        f"Market resolved {resolution_method} to {gt_display}"
                    )
        except Exception as e:
            logger.debug(
                f"Failed to parse ground truth for market {market.get('question', 'unknown')}: {e}"
            )

        return ground_truth, resolution_reasoning

    def should_skip_market(
        self,
        market: Dict[str, Any],
        end_date: datetime,
        closed_time: Optional[datetime],
        quality_requirements: Optional[QualityRequirements],
    ) -> Tuple[bool, str]:
        """Check if market should be skipped based on filters.

        Args:
            market: Market data from API
            end_date: Market end date
            closed_time: Market closed time (if available)
            quality_requirements: Quality constraints

        Returns:
            Tuple of (should_skip, reason)
        """
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

    def _get_lookback_days(
        self, quality_requirements: Optional[QualityRequirements]
    ) -> int:
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
