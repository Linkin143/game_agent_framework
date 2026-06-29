import os


def get_active_provider():
    return os.getenv("ACTIVE_PROVIDER", "huggingface")

def get_active_model():
    return os.getenv(
        "ACTIVE_MODEL",
        "huggingface/novita/Qwen/Qwen3-VL-8B-Instruct"
    )