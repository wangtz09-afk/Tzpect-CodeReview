"""Configuration validation and runtime checks."""
import json
import os
import urllib.request
from typing import Optional

from utils.common import find_api_key


class ConfigError(Exception):
    """Raised when configuration validation fails."""
    pass


class ConfigValidator:
    """Validates configuration before starting reviews."""

    # Expected config keys and their types
    EXPECTED_KEYS = {
        "api_url": str,
        "timeout": int,
        "max_retries": int,
        "model": str,
        "temperature": float,
        "max_tokens": int,
    }

    def __init__(self, settings: dict):
        self.settings = settings
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def validate(self) -> bool:
        """Run all validation checks. Returns True if all pass."""
        self.errors.clear()
        self.warnings.clear()

        self._check_api_key()
        self._check_model()
        self._check_parameters()
        self._check_paths()

        if self.errors:
            return False
        return True

    def _check_api_key(self) -> None:
        """Verify API key is set."""
        api_key = find_api_key()
        if not api_key:
            self.errors.append(
                "No API key found. Set one of: DASHSCOPE_API_KEY, DEEPSEEK_API_KEY, OPENAI_API_KEY"
            )
        elif len(api_key) < 10:
            self.warnings.append(
                f"API key looks too short ({len(api_key)} chars). Check if correct."
            )

    def _check_model(self) -> None:
        """Verify model name is configured."""
        model = self.settings.get("model", "")
        if not model:
            self.warnings.append("No model specified, using default")
        elif not any(k in model.lower() for k in ("gpt", "claude", "deepseek", "qwen", "llama", "mistral")):
            self.warnings.append(
                f"Model '{model}' may not be supported. "
                f"Expected: GPT, Claude, DeepSeek, Qwen, LLaMA, or Mistral variant"
            )

    def _check_parameters(self) -> None:
        """Validate parameter ranges."""
        timeout = self.settings.get("timeout", 180)
        if isinstance(timeout, (int, float)):
            if timeout < 10:
                self.errors.append(f"API timeout too low: {timeout}s (minimum: 10s)")
            elif timeout > 600:
                self.warnings.append(f"API timeout very high: {timeout}s")
        else:
            self.errors.append(f"Invalid timeout type: {type(timeout).__name__}")

        max_retries = self.settings.get("max_retries", 3)
        if isinstance(max_retries, int):
            if max_retries < 0:
                self.errors.append(f"max_retries must be >= 0, got {max_retries}")
            elif max_retries > 10:
                self.warnings.append(f"max_retries very high: {max_retries}")
        else:
            self.errors.append(f"Invalid max_retries type: {type(max_retries).__name__}")

        temperature = self.settings.get("temperature", 0.3)
        if isinstance(temperature, (int, float)):
            if temperature < 0:
                self.errors.append(f"temperature must be >= 0, got {temperature}")
            elif temperature > 2.0:
                self.errors.append(f"temperature must be <= 2.0, got {temperature}")
        else:
            self.errors.append(f"Invalid temperature type: {type(temperature).__name__}")

        max_tokens = self.settings.get("max_tokens", 4096)
        if isinstance(max_tokens, int):
            if max_tokens < 64:
                self.errors.append(f"max_tokens too low: {max_tokens} (minimum: 64)")
            elif max_tokens > 128000:
                self.warnings.append(f"max_tokens very high: {max_tokens}")
        else:
            self.errors.append(f"Invalid max_tokens type: {type(max_tokens).__name__}")

    def _check_paths(self) -> None:
        """Verify file paths are valid."""
        checkpoint_dir = self.settings.get("checkpoint_dir")
        if checkpoint_dir and not os.path.isdir(os.path.dirname(checkpoint_dir)):
            self.errors.append(f"Checkpoint directory parent not found: {checkpoint_dir}")

        output_dir = self.settings.get("output_dir")
        if output_dir and not os.path.isdir(os.path.dirname(output_dir)):
            self.warnings.append(f"Output directory parent not found: {output_dir}")

    def test_connection(self, api_url: str = "", api_key: str = "") -> dict:
        """Test API connectivity and return result."""
        if not api_url:
            api_url = self.settings.get("api_url", "https://api.deepseek.com/v1/chat/completions")
        if not api_key:
            api_key = find_api_key()

        if not api_key:
            return {"success": False, "error": "No API key"}

        payload = json.dumps({
            "model": self.settings.get("model", "deepseek-v4-flash"),
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 10,
        }).encode("utf-8")

        req = urllib.request.Request(
            api_url,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return {
                    "success": True,
                    "model": data.get("model", self.settings.get("model", "unknown")),
                    "tokens_used": data.get("usage", {}).get("total_tokens", 0),
                }
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            return {"success": False, "error": f"HTTP {e.code}: {body[:200]}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_summary(self) -> str:
        """Get validation summary."""
        lines = []
        if self.errors:
            lines.append(f"❌ {len(self.errors)} error(s):")
            for err in self.errors:
                lines.append(f"  - {err}")
        if self.warnings:
            lines.append(f"⚠ {len(self.warnings)} warning(s):")
            for warn in self.warnings:
                lines.append(f"  - {warn}")
        if not self.errors and not self.warnings:
            lines.append("✅ Configuration is valid")
        return "\n".join(lines)
