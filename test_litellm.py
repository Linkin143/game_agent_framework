import os
from dotenv import load_dotenv

from core.llm.llm_service import LiteLLMService

load_dotenv()

llm = LiteLLMService(
    model="anthropic/claude-sonnet-4-5",
    temperature=0.1,
    max_tokens=100,
)

response = llm.invoke([
    type(
        "SystemMessage",
        (),
        {"content": "You are a helpful assistant"}
    )(),
    type(
        "HumanMessage",
        (),
        {"content": "Reply only with: LITELLM_OK"}
    )(),
])

print(response.content)