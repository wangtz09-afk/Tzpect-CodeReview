"""Tests for utils.config_validator module."""
import pytest
import os
from unittest.mock import patch
from utils.config_validator import ConfigValidator, ConfigError


class TestConfigValidator:
    def test_valid_config(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "sk-test-key-12345"}):
            settings = {
                "api_url": "",
                "timeout": 180,
                "max_retries": 3,
                "model": "deepseek-v4-flash",
                "temperature": 0.3,
                "max_tokens": 4096,
            }
            validator = ConfigValidator(settings)
            assert validator.validate() is True
            assert len(validator.errors) == 0

    def test_missing_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = {"model": "test"}
            validator = ConfigValidator(settings)
            assert validator.validate() is False
            assert any("No API key" in e for e in validator.errors)

    def test_short_api_key_warning(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "short"}):
            settings = {"model": "test"}
            validator = ConfigValidator(settings)
            validator.validate()
            assert any("too short" in w for w in validator.warnings)

    def test_invalid_timeout(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "sk-test-key"}):
            settings = {"timeout": 5}  # Too low
            validator = ConfigValidator(settings)
            assert validator.validate() is False
            assert any("too low" in e for e in validator.errors)

    def test_invalid_temperature(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "sk-test-key"}):
            settings = {"temperature": 3.0}  # Too high
            validator = ConfigValidator(settings)
            assert validator.validate() is False

    def test_max_retries_negative(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "sk-test-key"}):
            settings = {"max_retries": -1}
            validator = ConfigValidator(settings)
            assert validator.validate() is False

    def test_max_tokens_too_low(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "sk-test-key"}):
            settings = {"max_tokens": 10}
            validator = ConfigValidator(settings)
            assert validator.validate() is False

    def test_unknown_model_warning(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "sk-test-key"}):
            settings = {"model": "unknown-model-xyz"}
            validator = ConfigValidator(settings)
            validator.validate()
            assert any("may not be supported" in w for w in validator.warnings)

    def test_summary_output(self):
        settings = {}
        validator = ConfigValidator(settings)
        validator.validate()
        summary = validator.get_summary()
        assert len(summary) > 0

    def test_valid_config_high_timeout_warning(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "sk-test-key"}):
            settings = {"timeout": 999}  # Very high
            validator = ConfigValidator(settings)
            assert validator.validate() is True
            assert any("very high" in w for w in validator.warnings)

    def test_invalid_types(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "sk-test-key"}):
            settings = {
                "timeout": "not_a_number",
                "max_retries": "three",
            }
            validator = ConfigValidator(settings)
            assert validator.validate() is False
