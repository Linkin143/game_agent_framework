from dotenv import load_dotenv
load_dotenv()

from core.llm.llm_service import LiteLLMService
from langchain_core.messages import SystemMessage, HumanMessage

llm = LiteLLMService(
    model="azure/gpt-5.4"
)

response = llm.invoke([
    SystemMessage(
        content="Reply only with JSON"
    ),
    HumanMessage(
        content='{"status":"ok"}'
    )
])

print(type(response.content))
print(response.content)