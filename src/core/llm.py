from pydantic import BaseModel
import asyncio
from dotenv import load_dotenv
from typing import Any, Union

from src.utils.usage_tracking import UsageMetrics, UsageTracker

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
        self.usage_tracker = UsageTracker(
            model_name=str(self.llm_config.get("model", "unknown"))
        )

    async def acomplete(
        self,
        messages: list[dict],
        response_format: Any = None,
    ):
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
            import litellm
            response = await litellm.acompletion(**kwargs, messages=messages)
            if response["choices"]:
                self._record_usage(response, litellm)
                return response["choices"][0]["message"]["content"]
            # Empty choices — transient API hiccup
            if attempt < _EMPTY_CHOICES_MAX_RETRIES:
                wait = _EMPTY_CHOICES_BACKOFF_BASE**attempt
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

    def _record_usage(self, response: Any, litellm_module: Any) -> None:
        """Capture token counts and LiteLLM's best available cost estimate."""
        usage = response.get("usage") or {}
        prompt_tokens = int(
            usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or 0
        )
        completion_tokens = int(
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or 0
        )
        total_tokens = int(
            usage.get("total_tokens") or prompt_tokens + completion_tokens
        )
        hidden = getattr(response, "_hidden_params", {}) or {}
        estimated_cost = hidden.get("response_cost")
        if not isinstance(estimated_cost, (int, float)):
            estimated_cost = 0.0
            if prompt_tokens or completion_tokens:
                try:
                    prompt_cost, completion_cost = litellm_module.cost_per_token(
                        model=str(self.llm_config.get("model", "unknown")),
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                    )
                    estimated_cost = prompt_cost + completion_cost
                except Exception:
                    estimated_cost = 0.0
        self.usage_tracker.add_usage(
            UsageMetrics(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=float(estimated_cost),
                model=str(self.llm_config.get("model", "unknown")),
            )
        )

    def get_usage_report(self) -> dict[str, Any]:
        """Return aggregate and per-call usage for the current client."""
        summary = self.usage_tracker.get_summary()
        return {
            **summary.to_dict(),
            "calls": self.usage_tracker.total_calls,
            "cost_source": "litellm_response_or_model_pricing",
            "per_call": [
                metrics.to_dict() for metrics in self.usage_tracker.usage_records
            ],
        }

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

        import litellm
        # Add num_retries=3 for robustness
        response = await litellm.aembedding(
            model=embedding_model, input=inputs, num_retries=3
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
    model_id_lower = model_id.lower()
    # Exact match first
    if model_id_lower in models:
        return models[model_id_lower].get("cutoff_date") or "Unknown"
    # Prefix match: find the longest key that is a prefix of the model_id
    # e.g. "gemini-3-flash" matches "gemini-3-flash-preview"
    best_key = None
    for key in models:
        if model_id_lower.startswith(key.lower()):
            if best_key is None or len(key) > len(best_key):
                best_key = key
    if best_key:
        return models[best_key].get("cutoff_date") or "Unknown"
    return "Unknown"
