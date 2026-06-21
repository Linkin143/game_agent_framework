from dotenv import load_dotenv
load_dotenv()

from core.llm.llm_service import LiteLLMService

llm = LiteLLMService(
    model="azure/gpt-5.4"
)

fake_image = "AAAA"

content = [
    {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": fake_image,
        },
    },
    {
        "type": "text",
        "text": "Reply only with JSON: {\"status\":\"vision_ok\"}"
    },
]

response = llm.invoke([
    type(
        "HumanMessage",
        (),
        {"content": content}
    )(),
])

print(response.content)