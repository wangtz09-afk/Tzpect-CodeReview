"""Tests for utils.logger module."""
import os
import tempfile
import pytest
import logging
from utils.logger import get_logger, log_api_call, log_review_stage, get_log_path


class TestLogger:
    def test_get_logger(self):
        logger = get_logger()
        assert logger is not None
        assert isinstance(logger, logging.Logger)

    def test_get_logger_returns_same_instance(self):
        logger1 = get_logger()
        logger2 = get_logger()
        assert logger1 is logger2

    def test_logger_has_handlers(self):
        logger = get_logger()
        assert len(logger.handlers) >= 1

    def test_log_api_call_success(self):
        log_api_call(
            agent="ReviewerAgent",
            model="deepseek-v4-flash",
            tokens_used=1000,
            duration_seconds=2.5,
            success=True,
        )
        # Should not raise

    def test_log_api_call_failure(self):
        log_api_call(
            agent="ReviewerAgent",
            model="deepseek-v4-flash",
            tokens_used=0,
            duration_seconds=0.0,
            success=False,
            error="API timeout",
        )
        # Should not raise

    def test_log_review_stage(self):
        log_review_stage("review_complete", "test.py", {
            "quality": "good",
            "issues": 0,
            "approved": True,
        })
        # Should not raise

    def test_log_path(self):
        # Get logger first to initialize
        logger = get_logger()
        path = get_log_path()
        # Should return a path if logging is initialized
        # (may be None if log dir doesn't exist yet)
        if path:
            assert path.endswith(".log")
            assert os.path.dirname(path).endswith(".code_review_logs")
