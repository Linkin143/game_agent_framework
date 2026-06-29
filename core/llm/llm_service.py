from __future__ import annotations

import os
from litellm import completion


class LiteLLMService:
    """
    Compatibility wrapper around LiteLLM.

    Goal:
        Behave like ChatAnthropic.invoke()

    So existing agents remain unchanged.
    """

    def __init__(
        self,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    # ------------------------------------------------------------------
    # Anthropic → OpenAI/LiteLLM image format conversion
    # ------------------------------------------------------------------

    def _convert_content(self, content):
        """
        Converts existing BaseAgent multimodal format into
        LiteLLM/OpenAI compatible format.

        Existing framework sends:

        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "..."
            }
        }

        We convert to:

        {
            "type": "image_url",
            "image_url": {
                "url": "data:image/png;base64,..."
            }
        }
        """

        if isinstance(content, str):
            return content

        if not isinstance(content, list):
            return str(content)

        converted = []

        for item in content:

            if not isinstance(item, dict):
                continue

            # Text block
            if item.get("type") == "text":
                converted.append(
                    {
                        "type": "text",
                        "text": item.get("text", "")
                    }
                )

            # Anthropic image block
            elif item.get("type") == "image":

                source = item.get("source", {})

                media_type = source.get(
                    "media_type",
                    "image/png"
                )

                image_b64 = source.get("data", "")

                converted.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_b64}"
                        }
                    }
                )

        return converted

    # ------------------------------------------------------------------
    # Main invoke()
    # ------------------------------------------------------------------

    def invoke(self, messages):

        converted_messages = []

        for msg in messages:

            role = "user"

            if msg.__class__.__name__ == "SystemMessage":
                role = "system"

            converted_messages.append(
                {
                    "role": role,
                    "content": self._convert_content(msg.content),
                }
            )

        kwargs = {
            "model": self.model,
            "messages": converted_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        provider = os.getenv("ACTIVE_PROVIDER", "").lower()

        if self.model.startswith("azure/") or provider == "azure":
            kwargs["api_base"] = os.getenv("AZURE_API_BASE")
            kwargs["api_key"] = os.getenv("AZURE_API_KEY")
            kwargs["api_version"] = os.getenv("AZURE_API_VERSION", "2024-12-01-preview")

        elif provider == "huggingface":
            kwargs["api_key"] = os.getenv("HUGGINGFACE_API_KEY")
            # only if using dedicated endpoint:
            # kwargs["api_base"] = os.getenv("HF_API_BASE")
        print("MODEL:", self.model)

        response = completion(**kwargs)

        class Response:
            pass

        result = Response()
        result.content = response.choices[0].message.content

        return result