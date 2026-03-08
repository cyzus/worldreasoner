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
