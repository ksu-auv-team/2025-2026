import os
from pathlib import Path

from dotenv import load_dotenv


def load_env() -> None:
    """Load .env from the project root (two levels up from this file)."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=env_path, override=False)


def get_env(key: str, default: str | None = None, required: bool = False) -> str | None:
    """
    Retrieve an environment variable by key.

    Args:
        key:      The environment variable name.
        default:  Fallback value if the key is not set.
        required: If True, raises RuntimeError when the key is missing.
    """
    load_env()
    value = os.getenv(key, default)
    if required and value is None:
        raise RuntimeError(f"Missing required environment variable: '{key}'")
    return value