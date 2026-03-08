from pydantic import BaseModel
import asyncio
import litellm
from dotenv import load_dotenv
from typing import Union

load_dotenv()

_EMPTY_CHOICES_MAX_RETRIES = 3
_EMPTY_CHOICES_BACKOFF_BASE = 2.0  # seconds


class LiteLLMClient:
    def __init__(self, llm_config: Union[dict, BaseModel]):
        # Convert BaseModel to dict if needed
        if isinstance(llm_config, BaseModel):
            self.llm_config = llm_config.model_dump(exclude_none=True)
        else:
            self.llm_config = llm_config

    async def acomplete(self, messages: list[dict], response_format: dict = None):
        """Complete an LLM request.

        Args:
            messages: List of message dicts with role and content
            response_format: Optional response format specification (e.g., {"type": "json_object"})
        """
        kwargs = {**self.llm_config}
        if response_format:
            kwargs["response_format"] = response_format

        # Use implicit retries from litellm (default 0, we set to 3)
        # See https://docs.litellm.ai/docs/completion/reliable_completions
        if "num_retries" not in kwargs:
            kwargs["num_retries"] = 3

        # litellm's num_retries handles HTTP-level errors but NOT the case where
        # the API returns HTTP 200 with an empty choices list (a transient Gemini/
        # Vertex issue). We handle that here with our own retry loop.
        for attempt in range(_EMPTY_CHOICES_MAX_RETRIES + 1):
            response = await litellm.acompletion(**kwargs, messages=messages)
            if response["choices"]:
                return response["choices"][0]["message"]["content"]
            # Empty choices — transient API hiccup
            if attempt < _EMPTY_CHOICES_MAX_RETRIES:
                wait = _EMPTY_CHOICES_BACKOFF_BASE ** attempt
                from src.utils.logging import logger
                logger.warning(
                    f"LLM returned empty choices (attempt {attempt + 1}/{_EMPTY_CHOICES_MAX_RETRIES}), "
                    f"retrying in {wait:.1f}s..."
                )
                await asyncio.sleep(wait)

        raise RuntimeError(
            f"LLM returned empty choices after {_EMPTY_CHOICES_MAX_RETRIES} retries. "
            "This is likely a transient API issue."
        )

    async def aembedding(self, inputs: list[str], model: str = None):
        """Generate embeddings for a list of texts.

        Args:
            inputs: List of texts to embed
            model: Optional embedding model override (uses llm_config['model'] if not provided)

        Returns:
            List of embedding vectors (as lists of floats)
        """
        # Use provided model or default to config model
        embedding_model = model or self.llm_config.get("embedding_model")
        
        # Add num_retries=3 for robustness
        response = await litellm.aembedding(
            model=embedding_model, 
            input=inputs,
            num_retries=3
        )
        return [item["embedding"] for item in response["data"]]


def parse_json_response(response_str: str) -> dict:
    """Parse JSON from LLM response, handling markdown code blocks.

    Args:
        response_str: Raw response string from LLM

    Returns:
        Parsed JSON object

    Raises:
        json.JSONDecodeError: If JSON cannot be parsed
    """
    import json
    import re
    from src.utils.logging import logger

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
    """Get the knowledge cutoff date for a given LLM model.

    Args:
        model_id: Model identifier (e.g., "gpt-4", "gemini/gemini-2.5-flash")

    Returns:
        Cutoff date string or "Unknown" if not found
    """
    import json
    from src.utils.logging import logger
    from src.config.constants import PROJECT_ROOT

    cutoff_file = PROJECT_ROOT / "config" / "llm_cutoff_dates.json"
    model_id = model_id.split("/")[-1]  # Get the last part of the model ID

    try:
        with open(cutoff_file, "r", encoding="utf-8") as f:
            cutoff_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Could not load LLM cutoff dates from {cutoff_file}: {e}")
        return "Unknown"

    models = cutoff_data.get("models", {})
    for key, model_info in models.items():
        if model_id.lower() in key.lower():
            return model_info.get("cutoff_date", "Unknown")
    return "Unknown"
