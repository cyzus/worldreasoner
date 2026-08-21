"""Usage extraction tests for the construction runtime adapter."""

from types import SimpleNamespace

import pytest

from src.pipelines.construction.sdk_runtime import AgentsSDKRuntime


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
