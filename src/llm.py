from pydantic import BaseModel
import litellm
from dotenv import load_dotenv
from typing import Union

load_dotenv()


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

        response = await litellm.acompletion(**kwargs, messages=messages)
        return response["choices"][0]["message"]["content"]

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
