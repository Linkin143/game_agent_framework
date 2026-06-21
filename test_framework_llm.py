from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(".env"))

from core.llm.llm_service import LiteLLMService

llm = LiteLLMService(
    model="azure/gpt-5.4"
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
        {"content": "Reply only with FRAMEWORK_OK"}
    )(),
])

print(response.content)