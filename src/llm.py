from pydantic import BaseModel, Field
import litellm
from dotenv import load_dotenv
from typing import Union

load_dotenv()

class LiteLLMClient():
    def __init__(self, llm_config: Union[dict, BaseModel]):
        # Convert BaseModel to dict if needed
        if isinstance(llm_config, BaseModel):
            self.llm_config = llm_config.model_dump(exclude_none=True)
        else:
            self.llm_config = llm_config

    async def acomplete(self, messages: list[dict]):
        response = await litellm.acompletion(
            **self.llm_config,
            messages=messages
        )
        return response['choices'][0]['message']['content']


