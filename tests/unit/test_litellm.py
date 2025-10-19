"""Unit tests for LiteLLM client."""

import pytest
from src.llm import LiteLLMClient

class TestLiteLLMClientIntegration:
    """Integration tests for LiteLLMClient with real API calls."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_acomplete_real_api_call(self):
        """Test real API call to LiteLLM (requires API key in environment).
        
        This test makes an actual API call. Run with: pytest -m integration
        Skip with: pytest -m "not integration"
        """
        llm_config = {
            "model": "gemini/gemini-2.5-flash",
            "temperature": 0.7,
            "max_tokens": 50
        }
        client = LiteLLMClient(llm_config)
        
        messages = [
            {"role": "user", "content": "Say 'Hello, World!' and nothing else."}
        ]
        
        # Make real API call
        result = await client.acomplete(messages)
        
        # Print the actual response for inspection
        print(f"\n{'='*60}")
        print(f"API Response: {result}")
        print(f"Response type: {type(result)}")
        print(f"Response length: {len(result)}")
        print(f"{'='*60}\n")
        
        # Verify we got a non-empty response
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0
        
        # The response should contain the requested phrase
        assert "Hello" in result or "hello" in result
