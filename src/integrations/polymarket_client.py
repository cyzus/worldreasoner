"""Polymarket API client.

HTTP client wrapper for the Polymarket Gamma API.
Follows flat hierarchy pattern (no subdirectories).
"""

from typing import List, Dict, Any, Optional
import aiohttp
from datetime import datetime, timedelta, timezone

from src.utils.logging import logger
from src.config.collection_goal import QualityRequirements


class PolymarketClient:
    """HTTP client for Polymarket Gamma API.

    Provides a clean interface for fetching market data from Polymarket's
    Gamma API. Handles pagination, filtering, and error handling.
    """

    API_BASE = "https://gamma-api.polymarket.com"

    # Cache for tag slug -> tag ID mapping
    _tag_id_cache: Dict[str, Optional[str]] = {}

    async def get_tag_id(self, slug: str) -> Optional[str]:
        """Get numeric tag ID from slug.

        Args:
            slug: Tag slug (e.g., 'politics', 'crypto')

        Returns:
            Tag ID string or None if not found
        """
        # Check cache
        if slug in self._tag_id_cache:
            return self._tag_id_cache[slug]

        url = f"{self.API_BASE}/tags/slug/{slug}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        tag_id = data.get("id")
                        self._tag_id_cache[slug] = tag_id
                        logger.debug(f"Tag '{slug}' -> ID '{tag_id}'")
                        return tag_id
                    else:
                        logger.warning(
                            f"Tag slug '{slug}' not found (status {response.status})"
                        )
                        self._tag_id_cache[slug] = None
                        return None
        except Exception as e:
            logger.warning(f"Failed to fetch tag ID for '{slug}': {e}")
            self._tag_id_cache[slug] = None
            return None

    async def search_markets(
        self,
        query: str,
        limit_per_type: int = 20,
        events_tag: Optional[List[str]] = None,
        page: Optional[int] = None,
        result_type: Optional[str] = None,
        events_status: Optional[str] = None,
        sort: Optional[str] = None,
        presets: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Search Polymarket markets, events, and profiles.

        Args:
            query: Search query term
            limit_per_type: Results limit per content type (default: 20)
            events_tag: Optional event tags to filter by
            page: Page number for pagination
            result_type: Filter by type (e.g., 'events')
            events_status: Event status filter ('active' or 'resolved')
            sort: Sort key (e.g., 'closed_time')
            presets: Response presets

        Returns:
            Dict with 'events', 'tags', 'profiles' keys containing search results
        """
        # Let aiohttp handle URL encoding automatically - don't manually replace spaces
        normalized_query = query.strip()

        url = f"{self.API_BASE}/public-search"
        params = {
            "q": normalized_query,
            "limit_per_type": limit_per_type,
        }
        # Only include page if explicitly provided
        if page is not None:
            params["page"] = page

        # Optional filters per example query
        if events_tag:
            params["events_tag"] = events_tag
        if result_type:
            params["type"] = result_type
        if events_status:
            params["events_status"] = events_status
        if sort:
            params["sort"] = sort
        if presets:
            # aiohttp will serialize list values as repeated query params
            params["presets"] = presets

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        logger.error(
                            f"Polymarket search API returned {response.status}"
                        )
                        return {"events": [], "tags": [], "profiles": []}

                    data = await response.json()

                    # Extract events (which contain markets)
                    events = data.get("events", [])
                    tags = data.get("tags", [])
                    profiles = data.get("profiles", [])

                    logger.info(
                        f"Polymarket search for '{normalized_query}' page={page} returned: "
                        f"{len(events)} events, {len(tags)} tags, {len(profiles)} profiles"
                    )

                    return data

        except Exception as e:
            logger.error(f"Failed to search Polymarket: {e}")
            return {"events": [], "tags": [], "profiles": []}

    async def fetch_markets(
        self,
        limit: int = 1000,
        require_ground_truth: bool = True,
        quality_requirements: Optional[QualityRequirements] = None,
        tag_slugs: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch markets from Polymarket API.

        Args:
            limit: Maximum markets to fetch
            require_ground_truth: If True, fetch resolved markets. If False, fetch active markets.
            quality_requirements: Quality constraints (used for lookback calculation)
            tag_slugs: Optional tag slugs to filter markets by (e.g., ['politics', 'crypto'])

        Returns:
            List of market dictionaries from API
        """
        url = f"{self.API_BASE}/markets"
        params = {
            "limit": limit,
            "offset": 0,
        }

        # Add tag filter if specified (for domain-specific fetching)
        # Convert slug to numeric ID first
        if tag_slugs:
            tag_ids = []
            for slug in tag_slugs:
                tag_id = await self.get_tag_id(slug)
                if tag_id:
                    tag_ids.append(tag_id)
                else:
                    logger.warning(
                        f"Could not resolve tag slug '{slug}', fetching without tag filter"
                    )

        # For ground truth, query closed markets sorted by resolution time
        if require_ground_truth:
            lookback_days = self._get_lookback_days(quality_requirements)

            # Query only closed markets, sorted by closedTime (most recent first)
            params["closed"] = "true"
            params["order"] = "volume,closedTime"
            params["ascending"] = "false"
            logger.info(
                "API filtering for closed markets sorted by closedTime (most recent first)"
            )
        market_list = []
        if tag_slugs and tag_ids:
            params_list = [params.copy() for _ in tag_ids]
            for i, tag_id in enumerate(tag_ids):
                params_list[i]["tag_id"] = tag_id
                markets = await self.call_api(
                    url=url,
                    params=params_list[i],
                )
                market_list.extend(markets)
        else:
            markets = await self.call_api(
                url=url,
                params=params,
            )
            market_list.extend(markets)

        # Log filtering criteria for ground truth
        if require_ground_truth:
            lookback_days = self._get_lookback_days(quality_requirements)
            min_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
            logger.info(
                f"Client-side filter: {min_date.strftime('%Y-%m-%d')} <= closedTime <= now ({lookback_days} days)"
            )

        # Debug: Check sample market
        if market_list:
            sample = market_list[0]
            logger.info(
                f"Sample: closed={sample.get('closed')}, endDate={sample.get('endDate')}, umaEndDate={sample.get('umaEndDate')}, closedTime={sample.get('closedTime')}, question={sample.get('question', 'N/A')[:60]}"
            )

        return market_list

    async def fetch_events(
        self,
        limit: int = 100,
        closed: bool = False,
        active: bool = True,
        tag_slugs: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch events (grouped markets) from Polymarket API.

        This endpoint (/events) returns markets grouped by event, allowing
        detection of multi-market questions (e.g. categorical).
        """
        url = f"{self.API_BASE}/events"
        
        # We manually construct a list of params to handle duplicate keys like multiple tag_slugs properly if needed,
        # but aiohttp supports list values natively.
        params = {
            "limit": limit,
            "closed": str(closed).lower(),
            "active": str(active).lower(),
            "order": "volume24hr",
            "ascending": "false",
        }
        
        if tag_slugs:
            params["tag_slug"] = tag_slugs

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        logger.error(
                            f"Polymarket Events API returned {response.status}"
                        )
                        return []

                    payload = await response.json()
                    events_list = []
                    if isinstance(payload, list):
                        events_list = payload
                    elif isinstance(payload, dict):
                        events_list = payload.get("events", []) or payload.get("data", []) or []
                    
                    # Robust local sorting fallback
                    if events_list:
                        events_list.sort(key=lambda e: float(e.get("volume24hr", e.get("volume", 0))), reverse=True)
                        
                    return events_list
        except Exception as e:
            logger.error(f"Failed to fetch events: {e}")
            return []

    async def call_api(
        self, url: str, params: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    logger.error(f"Polymarket Gamma API returned {response.status}")
                    return []

                # Gamma API returns array directly
                market_list = await response.json()

                if not isinstance(market_list, list):
                    logger.error(f"Unexpected response format: {type(market_list)}")
                    return []

                logger.info(f"Polymarket Gamma API returned {len(market_list)} markets")

                return market_list

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
