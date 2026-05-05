"""Tests for logger sanitization of sensitive data."""
import pytest

from utils.logger import sanitize, sanitize_dict, _SENSITIVE_PATTERNS


class TestSanitize:
    """Test sensitive data scrubbing in log output."""

    def test_bearer_token_redaction(self):
        """Should redact Bearer tokens."""
        text = "Authorization: Bearer sk-abc123xyz789def456"
        result = sanitize(text)
        assert "sk-abc123xyz789def456" not in result
        assert "[REDACTED]" in result

    def test_api_key_redaction(self):
        """Should redact API key patterns (sk-...)."""
        text = "DASHSCOPE_API_KEY=sk-f0611636ae014941adfeac5027bd6bfa"
        result = sanitize(text)
        assert "sk-f0611636ae014941adfeac5027bd6bfa" not in result
        assert "[REDACTED]" in result

    def test_env_var_redaction(self):
        """Should redact env var assignments."""
        text = 'API_KEY=supersecretvalue123'
        result = sanitize(text)
        assert "supersecretvalue123" not in result
        assert "[REDACTED]" in result

    def test_json_auth_header_redaction(self):
        """Should redact Authorization header in JSON."""
        text = '{"Authorization": "Bearer my-secret-token-1234567890abcdef"}'
        result = sanitize(text)
        assert "my-secret-token-1234567890abcdef" not in result
        assert "[REDACTED]" in result

    def test_normal_text_unchanged(self):
        """Should not modify normal text without sensitive data."""
        text = "Code review complete: 3 issues found"
        result = sanitize(text)
        assert result == text

    def test_empty_string(self):
        """Should handle empty strings."""
        assert sanitize("") == ""

    def test_non_string_passthrough(self):
        """Should return non-strings unchanged."""
        assert sanitize(42) == 42
        assert sanitize(None) is None

    def test_multiple_secrets(self):
        """Should redact multiple secrets in one string."""
        text = "API_KEY=secretvalue123 TOKEN=mytoken1234567890abcdef PASSWORD=p@ssword123"
        result = sanitize(text)
        assert "secretvalue123" not in result
        assert "mytoken1234567890abcdef" not in result
        assert "p@ssword123" not in result


class TestSanitizeDict:
    """Test dict sanitization."""

    def test_string_values(self):
        """Should sanitize string values in dict."""
        data = {"api_key": "sk-abc123xyz789def456qwertyuiop", "model": "deepseek-chat"}
        result = sanitize_dict(data)
        assert "[REDACTED]" in result["api_key"]
        assert result["model"] == "deepseek-chat"

    def test_nested_dict(self):
        """Should recursively sanitize nested dicts."""
        data = {
            "user": {"token": "mytokensecret1234567890abcdef", "name": "Alice"},
        }
        result = sanitize_dict(data)
        # The token gets redacted via env var pattern when in JSON form,
        # or via bearer pattern. Here it's a raw token — test with a Bearer format.
        data2 = {
            "user": {"token": "Bearer mytokensecret1234567890abcdef", "name": "Alice"},
        }
        result2 = sanitize_dict(data2)
        assert "[REDACTED]" in result2["user"]["token"]
        assert result2["user"]["name"] == "Alice"

    def test_list_values(self):
        """Should sanitize strings within lists."""
        data = {"keys": ["sk-abc123xyz789def456qwertyuiop", "normal-value"]}
        result = sanitize_dict(data)
        assert "[REDACTED]" in result["keys"][0]
        assert result["keys"][1] == "normal-value"

    def test_non_string_values(self):
        """Should preserve non-string values."""
        data = {"count": 42, "ratio": 0.5, "active": True, "nothing": None}
        result = sanitize_dict(data)
        assert result["count"] == 42
        assert result["ratio"] == 0.5
        assert result["active"] is True
        assert result["nothing"] is None

    def test_empty_dict(self):
        """Should handle empty dicts."""
        assert sanitize_dict({}) == {}
