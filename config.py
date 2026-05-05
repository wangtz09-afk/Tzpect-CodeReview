"""Project configuration."""
import os
from pathlib import Path
from typing import Optional


def _load_dotenv():
    """Load .env file into environment variables."""
    # Find .env relative to project root (main.py location)
    root = Path(__file__).parent
    env_path = root / ".env"
    if not env_path.exists():
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value:
                    os.environ.setdefault(key, value)


_load_dotenv()


def get_settings():
    """Return settings dict from environment variables.

    Supports any OpenAI-compatible API:
    - DeepSeek, DashScope (Qwen/通义千问), OpenAI
    - Custom endpoints via API_URL
    - Any model name via *_MODEL environment variables
    """
    return {
        "api_key": os.getenv("API_KEY", "") or os.getenv("DASHSCOPE_API_KEY", "") or os.getenv("DEEPSEEK_API_KEY", "") or os.getenv("OPENAI_API_KEY", ""),
        "api_url": os.getenv("API_URL", ""),
        "reviewer_model": os.getenv("REVIEWER_MODEL", ""),
        "fixer_model": os.getenv("FIXER_MODEL", ""),
        "tester_model": os.getenv("TESTER_MODEL", ""),
        "verifier_model": os.getenv("VERIFIER_MODEL", ""),
        "max_tokens": int(os.getenv("MAX_TOKENS", "4096")),
        "temperature": float(os.getenv("TEMPERATURE", "0.3")),
        "max_files_per_run": int(os.getenv("MAX_FILES_PER_RUN", "20")),
        "timeout": int(os.getenv("API_TIMEOUT", "300")),
        "max_retries": int(os.getenv("MAX_RETRIES", "5")),
    }
