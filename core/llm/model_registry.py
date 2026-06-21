import os


def get_active_provider():
    return os.getenv("ACTIVE_PROVIDER", "anthropic")


def get_active_model():
    return os.getenv(
        "ACTIVE_MODEL",
        "claude-3-5-sonnet-20241022"
    )