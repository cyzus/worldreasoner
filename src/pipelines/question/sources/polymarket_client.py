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
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        data = await response.json()
                        tag_id = data.get('id')
                        self._tag_id_cache[slug] = tag_id
                        logger.debug(f"Tag '{slug}' -> ID '{tag_id}'")
                        return tag_id
                    else:
                        logger.warning(f"Tag slug '{slug}' not found (status {response.status})")
                        self._tag_id_cache[slug] = None
                        return None
        except Exception as e:
            logger.warning(f"Failed to fetch tag ID for '{slug}': {e}")
            self._tag_id_cache[slug] = None
            return None

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
                    logger.warning(f"Could not resolve tag slug '{slug}', fetching without tag filter")
        
        # For ground truth, query closed markets sorted by resolution time
        if require_ground_truth:
            lookback_days = self._get_lookback_days(quality_requirements)
            
            # Query only closed markets, sorted by closedTime (most recent first)
            params["closed"] = "true"
            params["order"] = "volume,closedTime"
            params["ascending"] = "false"
            logger.info(f"API filtering for closed markets sorted by closedTime (most recent first)")
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
            logger.info(f"Client-side filter: {min_date.strftime('%Y-%m-%d')} <= closedTime <= now ({lookback_days} days)")
        
        # Debug: Check sample market
        if market_list:
            sample = market_list[0]
            logger.info(f"Sample: closed={sample.get('closed')}, endDate={sample.get('endDate')}, umaEndDate={sample.get('umaEndDate')}, closedTime={sample.get('closedTime')}, question={sample.get('question', 'N/A')[:60]}")

        return market_list
    


    async def call_api(self, url: str, params: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  
        async with aiohttp.ClientSession() as session:
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
                
                
                return market_list
    
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
