"""OpenAI Agents SDK adapter for bounded structured construction stages."""

import asyncio
import json
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel

from src.config import get_config
from src.pipelines.construction.models import AgentUsage

T = TypeVar("T", bound=BaseModel)


class AgentsSDKRuntime:
    """Run one structured specialist without giving it dataset write access."""

    def __init__(
        self,
        model_id: Optional[str] = None,
        temperature: float = 0.2,
        tracing_enabled: bool = False,
        max_output_retries: int = 1,
        provider_call_timeout_seconds: float = 480.0,
    ) -> None:
        from agents.extensions.models.litellm_model import LitellmModel

        from agents import set_tracing_disabled

        config = get_config().llm
        self.model_id = model_id or config.model
        self.temperature = temperature
        self.max_output_retries = max_output_retries
        self.provider_call_timeout_seconds = provider_call_timeout_seconds
        self.model = LitellmModel(model=self.model_id)
        set_tracing_disabled(not tracing_enabled)

    async def run_structured(
        self,
        name: str,
        instructions: str,
        user_input: str,
        output_type: Type[T],
        max_turns: int = 4,
    ) -> tuple[T, AgentUsage]:
        """Execute a bounded SDK run and validate its final structured output."""
        last_error: Optional[Exception] = None
        for attempt_number in range(self.max_output_retries + 1):
            try:
                result = await asyncio.wait_for(
                    self._run_once(
                        name,
                        instructions,
                        user_input,
                        output_type,
                        max_turns,
                    ),
                    timeout=self.provider_call_timeout_seconds,
                )
                output = self._coerce_output(result.final_output, output_type)
                return output, self._extract_usage(result)
            except Exception as exc:
                last_error = exc
                if (
                    attempt_number >= self.max_output_retries
                    or not self._is_retryable_output_error(exc)
                ):
                    raise
        assert last_error is not None
        raise last_error

    async def _run_once(
        self,
        name: str,
        instructions: str,
        user_input: str,
        output_type: Type[T],
        max_turns: int,
    ) -> Any:
        """Run one SDK invocation; split out so retry behavior is testable."""
        from agents import Agent, ModelSettings, Runner

        agent = Agent(
            name=name,
            instructions=instructions,
            model=self.model,
            model_settings=ModelSettings(
                temperature=self.temperature,
                extra_args={"timeout": self.provider_call_timeout_seconds},
            ),
            output_type=output_type,
        )
        return await Runner.run(agent, user_input, max_turns=max_turns)

    @staticmethod
    def _coerce_output(output: Any, output_type: Type[T]) -> T:
        """Remove harmless transport padding before Pydantic validation."""
        if isinstance(output, str):
            cleaned = output.replace("\x00", "").strip()
            output = json.loads(cleaned)
        if not isinstance(output, output_type):
            output = output_type.model_validate(output)
        return output

    @staticmethod
    def _is_retryable_output_error(exc: Exception) -> bool:
        """Recognize malformed model output without retrying provider failures."""
        if isinstance(exc, json.JSONDecodeError):
            return True
        error_name = type(exc).__name__.lower()
        message = str(exc).lower()
        return any(
            marker in error_name or marker in message
            for marker in (
                "modelbehaviorerror",
                "invalid json",
                "json decode",
                "unterminated string",
                "control character",
                "validation error",
            )
        )

    def _extract_usage(self, result: Any) -> AgentUsage:
        """Read usage across SDK versions without coupling pipeline behavior to it."""
        context = getattr(result, "context_wrapper", None)
        usage = getattr(context, "usage", None)
        if usage is None:
            return AgentUsage()
        input_tokens = int(
            getattr(usage, "input_tokens", 0)
            or getattr(usage, "prompt_tokens", 0)
            or 0
        )
        output_tokens = int(
            getattr(usage, "output_tokens", 0)
            or getattr(usage, "completion_tokens", 0)
            or 0
        )
        cost_usd = self._estimate_cost(usage, input_tokens, output_tokens)
        return AgentUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=int(
                getattr(usage, "total_tokens", 0)
                or input_tokens + output_tokens
            ),
            requests=int(getattr(usage, "requests", 0) or 0),
            cost_usd=cost_usd,
        )

    def _estimate_cost(
        self,
        usage: Any,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Estimate provider cost using LiteLLM's installed model-price table."""
        import litellm

        entries = list(getattr(usage, "request_usage_entries", None) or [])
        if not entries:
            entries = [usage]
        total = 0.0
        try:
            for entry in entries:
                prompt_cost, completion_cost = litellm.cost_per_token(
                    model=self.model_id,
                    prompt_tokens=int(
                        getattr(entry, "input_tokens", input_tokens) or 0
                    ),
                    completion_tokens=int(
                        getattr(entry, "output_tokens", output_tokens) or 0
                    ),
                )
                total += float(prompt_cost or 0.0) + float(
                    completion_cost or 0.0
                )
        except Exception:
            return 0.0
        return total
