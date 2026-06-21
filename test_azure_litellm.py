import os
from dotenv import load_dotenv

from litellm import completion

load_dotenv()

response = completion(
    model="azure/gpt-5.4",
    api_base=os.getenv("AZURE_API_BASE"),
    api_key=os.getenv("AZURE_API_KEY"),
    api_version=os.getenv("AZURE_API_VERSION"),
    messages=[
        {
            "role": "user",
            "content": "Reply only with AZURE_OK"
        }
    ],
    max_tokens=20,
)

print(response.choices[0].message.content)