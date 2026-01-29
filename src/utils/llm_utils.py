"""Utilities for working with LLM responses."""

import json
import re
from typing import Any, Dict
from src.utils.logging import logger


def parse_json_response(response_str: str) -> Dict[str, Any]:
    """Parse JSON from LLM response, handling markdown code blocks.

    Args:
        response_str: Raw response string from LLM

    Returns:
        Parsed JSON object

    Raises:
        json.JSONDecodeError: If JSON cannot be parsed
    """
    response_str = response_str.strip()

    # Try direct parsing first
    try:
        return json.loads(response_str)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from markdown code blocks
    # Pattern matches: ```json\n{...}\n``` or ```\n{...}\n```
    json_match = re.search(
        r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", response_str, re.DOTALL
    )
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find any JSON object or array in the response
    # Look for the first { or [ and try to parse from there
    for start_char in ["{", "["]:
        start_idx = response_str.find(start_char)
        if start_idx != -1:
            try:
                return json.loads(response_str[start_idx:])
            except json.JSONDecodeError:
                pass

    # If all else fails, raise with helpful error
    logger.error("Failed to parse JSON from LLM response")
    logger.debug(f"Raw response (first 500 chars): {response_str[:500]}")
    raise json.JSONDecodeError(
        "Could not extract valid JSON from response", response_str[:100], 0
    )


def get_knowledge_cutoff_date(model_id: str) -> str:
    from src.config.constants import PROJECT_ROOT
    import json

    cutoff_file = PROJECT_ROOT / "config" / "llm_cutoff_dates.json"
    model_id = model_id.split("/")[-1]  # Get the last part of the model ID
    with open(cutoff_file, "r", encoding="utf-8") as f:
        cutoff_data = json.load(f)
    for key, model_info in cutoff_data["models"].items():
        if model_id.lower() in key.lower():
            return model_info["cutoff_date"]
    return "Unknown"
