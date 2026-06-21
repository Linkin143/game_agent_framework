from core.llm.llm_service import LiteLLMService

svc = LiteLLMService("azure/gpt-5.4")

sample = [
    {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "AAAA"
        }
    },
    {
        "type": "text",
        "text": "hello"
    }
]

print(svc._convert_content(sample))