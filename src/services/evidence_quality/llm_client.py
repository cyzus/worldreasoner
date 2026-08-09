"""Small structured-LLM interface shared by dataset quality passes."""

from typing import Any, Dict, List, Protocol

from src.core.llm import LiteLLMClient, parse_json_response


class StructuredLLM(Protocol):
    """Dependency-injection boundary for testable quality passes."""

    model_name: str

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> Dict[str, Any]:
        """Return one JSON object."""


class LiteLLMStructuredClient:
    """StructuredLLM adapter around the project's LiteLLM client."""

    def __init__(self, llm_client: LiteLLMClient) -> None:
        self.client = llm_client
        self.model_name = str(llm_client.llm_config.get("model", "unknown"))

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> Dict[str, Any]:
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response = await self.client.acomplete(
            messages=messages,
            response_format={"type": "json_object"},
        )
        result = parse_json_response(response)
        if (
            isinstance(result, list)
            and len(result) == 1
            and isinstance(result[0], dict)
        ):
            result = result[0]
        if not isinstance(result, dict):
            raise ValueError(
                "Quality pass must return a JSON object or a single-object list; "
                f"received {type(result).__name__}"
            )
        return result
