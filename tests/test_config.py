"""Tests for config module."""
import os
import pytest
from config import get_settings, _load_dotenv


class TestGetSettings:
    def test_returns_dict(self):
        settings = get_settings()
        assert isinstance(settings, dict)

    def test_has_required_keys(self):
        settings = get_settings()
        assert "api_key" in settings
        assert "reviewer_model" in settings
        assert "fixer_model" in settings
        assert "tester_model" in settings
        assert "verifier_model" in settings
        assert "max_tokens" in settings
        assert "temperature" in settings
        assert "max_files_per_run" in settings
        assert "timeout" in settings
        assert "max_retries" in settings

    def test_has_api_url(self):
        settings = get_settings()
        assert "api_url" in settings

    def test_max_tokens_default(self):
        settings = get_settings()
        assert settings["max_tokens"] == 4096

    def test_temperature_default(self):
        settings = get_settings()
        assert settings["temperature"] == 0.3

    def test_max_files_default(self):
        settings = get_settings()
        assert settings["max_files_per_run"] == 20

    def test_timeout_default(self):
        settings = get_settings()
        assert settings["timeout"] == 300

    def test_max_retries_default(self):
        settings = get_settings()
        assert settings["max_retries"] == 5

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("MAX_TOKENS", "8192")
        monkeypatch.setenv("TEMPERATURE", "0.7")
        monkeypatch.setenv("MAX_FILES_PER_RUN", "50")
        monkeypatch.setenv("REVIEWER_MODEL", "custom-model")
        monkeypatch.setenv("API_TIMEOUT", "300")
        monkeypatch.setenv("MAX_RETRIES", "5")

        settings = get_settings()
        assert settings["max_tokens"] == 8192
        assert settings["temperature"] == 0.7
        assert settings["max_files_per_run"] == 50
        assert settings["reviewer_model"] == "custom-model"
        assert settings["timeout"] == 300
        assert settings["max_retries"] == 5

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key-123")
        settings = get_settings()
        assert settings["api_key"] == "test-key-123"
