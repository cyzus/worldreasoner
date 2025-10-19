from pydantic import BaseModel, Field
import litellm
from dotenv import load_dotenv

load_dotenv()

class LiteLLMClient():
    def __init__(self, llm_config: dict):
        self.llm_config = llm_config

    async def acomplete(self, messages: list[dict]):
        response = await litellm.acompletion(
            **self.llm_config,
            messages=messages
        )
        return response['choices'][0]['message']['content']


