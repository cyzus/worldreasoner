"""Unit tests for LiteLLM client."""

import pytest
from src.core.llm import LiteLLMClient
from src.config import get_config


class TestLiteLLMClientIntegration:
    """Integration tests for LiteLLMClient with real API calls."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_acomplete_real_api_call(self):
        """Test real API call to LiteLLM (requires API key in environment).

        This test makes an actual API call. Run with: pytest -m integration
        Skip with: pytest -m "not integration"
        """
        config = get_config()
        llm_config = config.llm
        client = LiteLLMClient(llm_config)

        messages = [
            {"role": "user", "content": "Say 'Hello, World!' and nothing else."}
        ]

        # Make real API call
        result = await client.acomplete(messages)

        # Print the actual response for inspection
        print(f"\n{'=' * 60}")
        print(f"API Response: {result}")
        print(f"Response type: {type(result)}")
        print(f"Response length: {len(result)}")
        print(f"{'=' * 60}\n")

        # Verify we got a non-empty response
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0

        # The response should contain the requested phrase
        assert "Hello" in result or "hello" in result

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_acomplete_with_config_file(self):
        """Test real API call using LLM config loaded from config files.

        This test loads configuration from config.example.yaml + config.yaml and makes an actual API call.
        """
        # Load configuration from config files
        config = get_config()

        # Create client with config from file
        client = LiteLLMClient(config.llm)

        messages = [
            {"role": "user", "content": "What is 2+2? Answer with just the number."}
        ]

        # Make real API call
        result = await client.acomplete(messages)

        # Print the actual response and config for inspection
        print(f"\n{'=' * 60}")
        print("Loaded LLM Config:")
        print(f"  Model: {config.llm.model}")
        print(f"  Temperature: {config.llm.temperature}")
        print(f"  Max Tokens: {config.llm.max_tokens}")
        print(f"\nAPI Response: {result}")
        print(f"Response type: {type(result)}")
        print(f"Response length: {len(result)}")
        print(f"{'=' * 60}\n")

        # Verify we got a non-empty response
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0

        # The response should contain the answer
        assert "4" in result
