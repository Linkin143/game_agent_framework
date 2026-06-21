from pathlib import Path
from dotenv import load_dotenv
import base64

load_dotenv()

from core.llm.llm_service import LiteLLMService
from agents.base_agent import BaseAgent


class TestAgent(BaseAgent):
    SKILL_FILE = ""


img_b64 = base64.b64encode(
    Path("companylogo.png").read_bytes()
).decode()


llm = LiteLLMService(
    model="azure/gpt-5.4"
)

agent = TestAgent(llm)

content = agent.build_image_message(
    img_b64,
    """
Look at the image.

Return ONLY valid JSON:

{
  "status":"ok",
  "description":"short description"
}
"""
)

result = agent.call_llm(content)

print(type(result))
print(result)