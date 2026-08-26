"""Usage extraction tests for the construction runtime adapter."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from src.pipelines.construction.sdk_runtime import AgentsSDKRuntime


class RetryingRuntime(AgentsSDKRuntime):
    """Fail once with malformed output, then return a valid SDK-like result."""

    def __init__(self) -> None:
        self.model_id = "fake/model"
        self.max_output_retries = 1
        self.provider_call_timeout_seconds = 1.0
        self.calls = 0

    async def _run_once(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise json.JSONDecodeError("Invalid JSON", "{", 1)
        return SimpleNamespace(
            final_output='{"value": 3}\u0000\u0000',
            context_wrapper=SimpleNamespace(usage=None),
        )


def test_extract_usage_estimates_model_cost(monkeypatch) -> None:
    monkeypatch.setattr(
        "litellm.cost_per_token",
        lambda **_: (0.25, 0.15),
    )
    runtime = object.__new__(AgentsSDKRuntime)
    runtime.model_id = "gemini/gemini-3.1-pro-preview"
    usage = SimpleNamespace(
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
        requests=1,
        request_usage_entries=[],
    )
    result = SimpleNamespace(
        context_wrapper=SimpleNamespace(usage=usage),
    )

    extracted = runtime._extract_usage(result)

    assert extracted.total_tokens == 120
    assert extracted.requests == 1
    assert extracted.cost_usd == pytest.approx(0.40)


@pytest.mark.asyncio
async def test_retries_malformed_output_and_strips_nul_padding() -> None:
    class Output(BaseModel):
        value: int

    runtime = RetryingRuntime()

    output, usage = await runtime.run_structured(
        "test",
        "instructions",
        "input",
        Output,
    )

    assert output.value == 3
    assert usage.total_tokens == 0
    assert runtime.calls == 2


@pytest.mark.asyncio
async def test_does_not_retry_non_output_errors() -> None:
    runtime = RetryingRuntime()

    async def fail(*args, **kwargs):
        raise ConnectionError("provider unavailable")

    runtime._run_once = fail

    with pytest.raises(ConnectionError, match="provider unavailable"):
        await runtime.run_structured("test", "instructions", "input", BaseModel)


@pytest.mark.asyncio
async def test_provider_call_has_wall_clock_timeout() -> None:
    runtime = RetryingRuntime()
    runtime.provider_call_timeout_seconds = 0.01

    async def hang(*args, **kwargs):
        await asyncio.sleep(1)

    runtime._run_once = hang

    with pytest.raises(asyncio.TimeoutError):
        await runtime.run_structured("test", "instructions", "input", BaseModel)


@pytest.mark.asyncio
async def test_provider_timeout_is_forwarded_to_litellm(monkeypatch) -> None:
    import agents

    captured = {}

    class FakeSettings:
        def __init__(self, **kwargs):
            captured["settings"] = kwargs

    class FakeAgent:
        def __init__(self, **kwargs):
            captured["agent"] = kwargs

    class FakeRunner:
        @staticmethod
        async def run(agent, user_input, max_turns):
            captured["run"] = (agent, user_input, max_turns)
            return "result"

    monkeypatch.setattr(agents, "ModelSettings", FakeSettings)
    monkeypatch.setattr(agents, "Agent", FakeAgent)
    monkeypatch.setattr(agents, "Runner", FakeRunner)
    runtime = object.__new__(AgentsSDKRuntime)
    runtime.model = object()
    runtime.temperature = 0.2
    runtime.provider_call_timeout_seconds = 42.0

    result = await runtime._run_once(
        "test",
        "instructions",
        "input",
        BaseModel,
        4,
    )

    assert result == "result"
    assert captured["settings"]["extra_args"] == {"timeout": 42.0}
