# test_real_vision.py

from pathlib import Path
import base64

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from core.llm.llm_service import LiteLLMService

img_b64 = base64.b64encode(
    Path("companylogo.png").read_bytes()
).decode()

llm = LiteLLMService(
    model="azure/gpt-5.4"
)

response = llm.invoke([
    type(
        "HumanMessage",
        (),
        {
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": img_b64,
                    },
                },
                {
                    "type": "text",
                    "text": "Describe this image in one sentence."
                },
            ]
        },
    )()
])

print(response.content)