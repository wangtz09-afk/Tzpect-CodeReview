"""LLM client wrapper for OpenAI-compatible APIs (DeepSeek, DashScope, etc.)."""
import hashlib
import json
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

import httpx

from utils.common import find_api_key
from config import get_settings


@dataclass
class LLMResponse:
    """Unified LLM response."""
    content: str
    model: str
    tokens_used: int = 0
    success: bool = True
    error: str = ""
    cached: bool = False


@dataclass
class CacheStats:
    """Cache usage statistics."""
    hits: int = 0
    misses: int = 0
    saves: int = 0

    @property
    def hit_rate(self) -> float:
        count = self.hits + self.misses
        return self.hits / count if count > 0 else 0.0


class PromptCache:
    """Disk-based cache for LLM responses to avoid redundant API calls."""

    def __init__(self, cache_dir: Optional[str] = None, ttl_seconds: int = 86400):
        if cache_dir is None:
            cache_dir = str(Path(__file__).parent.parent / ".llm_cache")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self.stats = CacheStats()

    def _key(self, system_prompt: str, user_prompt: str, model: str, temperature: float, max_tokens: int) -> str:
        """Generate a cache key from request parameters."""
        raw = f"{model}:{temperature}:{max_tokens}:{system_prompt}:{user_prompt}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, system_prompt: str, user_prompt: str, model: str, temperature: float, max_tokens: int) -> Optional[LLMResponse]:
        """Look up a cached response. Returns None if not found or expired."""
        key = self._key(system_prompt, user_prompt, model, temperature, max_tokens)
        cache_file = self.cache_dir / f"{key}.json"
        if not cache_file.exists():
            self.stats.misses += 1
            return None
        try:
            mtime = cache_file.stat().st_mtime
            if time.time() - mtime > self.ttl_seconds:
                cache_file.unlink()
                self.stats.misses += 1
                return None
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.stats.hits += 1
            return LLMResponse(
                content=data["content"],
                model=data["model"],
                tokens_used=data.get("tokens_used", 0),
                success=True,
                cached=True,
            )
        except (json.JSONDecodeError, KeyError, OSError):
            self.stats.misses += 1
            return None

    def save(self, system_prompt: str, user_prompt: str, model: str, temperature: float, max_tokens: int, response: LLMResponse) -> None:
        """Save a response to the cache."""
        if not response.success:
            return  # Don't cache errors
        key = self._key(system_prompt, user_prompt, model, temperature, max_tokens)
        cache_file = self.cache_dir / f"{key}.json"
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({
                    "content": response.content,
                    "model": response.model,
                    "tokens_used": response.tokens_used,
                    "saved_at": time.time(),
                }, f, ensure_ascii=False)
            self.stats.saves += 1
        except OSError:
            pass

    def clear(self) -> int:
        """Remove all cached entries. Returns count of removed files."""
        count = 0
        for f in self.cache_dir.glob("*.json"):
            try:
                f.unlink()
                count += 1
            except OSError:
                pass
        return count

    def get_summary(self) -> str:
        total = self.stats.hits + self.stats.misses
        return (
            f"Cache: {self.stats.hits} hits, {self.stats.misses} misses, "
            f"{self.stats.saves} saves "
            f"(hit rate: {self.stats.hit_rate:.1%})"
        )


class LLMClient:
    """
    Universal LLM client that wraps any OpenAI-compatible API via httpx.

    Supported providers (auto-detected by model name):
    - DeepSeek, DashScope (Qwen/通义千问), OpenAI, Groq, Together, vLLM, Ollama, LM Studio
    - Any custom endpoint via API_URL environment variable

    Simply set the model name and API endpoint, and it works.
    """

    DEFAULT_ENDPOINTS = {
        "deepseek": "https://api.deepseek.com/v1/chat/completions",
        "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "openai": "https://api.openai.com/v1/chat/completions",
        "groq": "https://api.groq.com/openai/v1/chat/completions",
        "together": "https://api.together.xyz/v1/chat/completions",
        "ollama": "http://localhost:11434/v1/chat/completions",
    }

    def __init__(self, model: str, temperature: float = 0.3, max_tokens: int = 4096, use_cache: bool = True):
        self.settings = get_settings()
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.endpoint = self._resolve_endpoint()
        self.timeout = float(self.settings.get("timeout", 300))
        self.max_retries = int(self.settings.get("max_retries", 3))
        self.cache = PromptCache() if use_cache else None

    def _resolve_endpoint(self) -> str:
        """Resolve the API endpoint based on model name or settings.

        Auto-detection rules:
        1. If API_URL is set, use it (overrides everything)
        2. Match model name against known providers (deepseek, qwen, groq, etc.)
        3. Default to empty string - user must configure endpoint
        """
        custom_url = self.settings.get("api_url", "")
        if custom_url:
            return custom_url

        model_lower = self.model.lower()

        # Check model name for provider keywords
        for key, url in self.DEFAULT_ENDPOINTS.items():
            if key in model_lower:
                return url

        # Specific model patterns
        if model_lower.startswith("qwen"):
            return self.DEFAULT_ENDPOINTS["dashscope"]
        if model_lower.startswith("gpt"):
            return self.DEFAULT_ENDPOINTS["openai"]
        if model_lower.startswith("llama"):
            # Could be Groq, Together, or local - default to empty
            pass
        if model_lower.startswith("mistral"):
            return self.DEFAULT_ENDPOINTS["together"]

        # Unknown model - return empty, user must set API_URL
        return ""

    def _get_api_key(self) -> str:
        """Get API key from environment variables.

        Checks multiple environment variable names for compatibility:
        API_KEY, DASHSCOPE_API_KEY, DEEPSEEK_API_KEY, OPENAI_API_KEY,
        GROQ_API_KEY, TOGETHER_API_KEY, etc.

        Returns:
            API key string, or empty string if none found.
        """
        # Try generic name first
        api_key = os.getenv("API_KEY", "")
        if api_key:
            return api_key

        # Try provider-specific names
        for key_name in ["DASHSCOPE_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY",
                         "GROQ_API_KEY", "TOGETHER_API_KEY", "ANTHROPIC_API_KEY"]:
            api_key = os.getenv(key_name, "")
            if api_key:
                return api_key

        return ""

    def _build_headers(self, api_key: str) -> dict:
        """Build request headers with API key."""
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def chat(self, system_prompt: str, user_prompt: str, context: str = "") -> LLMResponse:
        """
        Send a chat request to the LLM with automatic retry and caching.

        Args:
            system_prompt: System-level instructions.
            user_prompt: User message / code to review.
            context: Optional additional context.

        Returns:
            LLMResponse with the model's output.
        """
        full_prompt = user_prompt
        if context:
            full_prompt = f"=== Additional Context ===\n{context}\n\n=== Task ===\n{user_prompt}"

        # Check cache first
        if self.cache:
            cached = self.cache.get(system_prompt, full_prompt, self.model, self.temperature, self.max_tokens)
            if cached:
                return cached

        # Retry with exponential backoff
        for attempt in range(self.max_retries):
            try:
                response = self._call_api(system_prompt, full_prompt)
                # Cache successful responses
                if response.success and self.cache:
                    self.cache.save(system_prompt, full_prompt, self.model, self.temperature, self.max_tokens, response)
                return response
            except _RetryableError as e:
                if attempt < self.max_retries - 1:
                    wait = min(2 ** attempt, 16)
                    print(f"    [WARN] Retry {attempt+1}/{self.max_retries} after {wait}s ({e})")
                    time.sleep(wait)
                else:
                    return LLMResponse(
                        content="", success=False, model=self.model,
                        error=f"API failed after {self.max_retries} attempts: {e}"
                    )
            except httpx.ReadError as e:
                # Connection lost mid-response
                if attempt < self.max_retries - 1:
                    wait = min(2 ** attempt, 16)
                    print(f"    [WARN] Retry {attempt+1}/{self.max_retries} after {wait}s (ReadError: {e})")
                    time.sleep(wait)
                else:
                    return LLMResponse(
                        content="", success=False, model=self.model,
                        error=f"API failed after {self.max_retries} attempts: ReadError({e})"
                    )
            except httpx.ConnectError as e:
                if attempt < self.max_retries - 1:
                    wait = min(2 ** attempt, 16)
                    print(f"    [WARN] Retry {attempt+1}/{self.max_retries} after {wait}s (ConnectError: {e})")
                    time.sleep(wait)
                else:
                    return LLMResponse(
                        content="", success=False, model=self.model,
                        error=f"API failed after {self.max_retries} attempts: ConnectError({e})"
                    )
            except Exception as e:
                return LLMResponse(
                    content="", success=False, model=self.model,
                    error=f"Non-retryable error: {str(e)}"
                )

        return LLMResponse(
            content="", success=False, model=self.model,
            error="Unexpected: exhausted retries"
        )

    def _call_api(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        """Call OpenAI-compatible API via httpx."""
        api_key = self._get_api_key()
        if not api_key:
            return LLMResponse(
                content="", success=False, model=self.model,
                error="No API key found. Set one of: API_KEY, DASHSCOPE_API_KEY, DEEPSEEK_API_KEY, OPENAI_API_KEY, GROQ_API_KEY, etc."
            )

        # Check if endpoint is configured
        if not self.endpoint:
            return LLMResponse(
                content="", success=False, model=self.model,
                error="No API endpoint configured. Set API_URL environment variable or use a known model name (deepseek-*, qwen-*, gpt-*, etc.)"
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(self.endpoint, json=payload, headers=self._build_headers(api_key))
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500] if e.response else ""
            status_code = e.response.status_code if e.response else 0
            if status_code in (429, 503, 500, 502, 504):
                raise _RetryableError(f"HTTP {status_code}: {body}")
            # Non-retryable (400, 401, 403)
            if status_code == 401:
                return LLMResponse(
                    content="", success=False, model=self.model,
                    error="Authentication failed (401). Check your API key."
                )
            elif status_code == 400:
                return LLMResponse(
                    content="", success=False, model=self.model,
                    error=f"Bad request (400): {body}"
                )
            elif status_code == 403:
                return LLMResponse(
                    content="", success=False, model=self.model,
                    error=f"Forbidden (403): {body}"
                )
            return LLMResponse(
                content="", success=False, model=self.model,
                error=f"HTTP {status_code}: {body}"
            )
        except httpx.TimeoutException:
            raise _RetryableError("Request timed out")
        except httpx.NetworkError as e:
            raise _RetryableError(f"Network error: {e}")

        # Parse response
        try:
            content = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens", 0)
            return LLMResponse(content=content, model=self.model, tokens_used=tokens)
        except (KeyError, IndexError) as e:
            return LLMResponse(
                content="", success=False, model=self.model,
                error=f"Unexpected response format: {str(e)}"
            )


class _RetryableError(Exception):
    """Raised for errors that warrant a retry."""
    pass
