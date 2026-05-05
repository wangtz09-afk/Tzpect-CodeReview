"""Tests for core.pipeline module."""
import pytest
from core.pipeline import ReviewPipeline
from core.models import PipelineResult
from core.git_ops import CodeChange


class TestPipelineResult:
    def test_default_values(self):
        result = PipelineResult(
            file_path="test.py",
            language="python",
        )
        assert result.review_result == {}
        assert result.fix_code == ""
        assert result.test_result == {}
        assert result.verification == {}
        assert result.total_tokens == 0
        assert result.stages == []
        assert result.errors == []
        assert result.fix_iterations == 0
        assert result.elapsed_seconds == 0.0

    def test_custom_values(self):
        result = PipelineResult(
            file_path="test.py",
            language="python",
            review_result={"overall_quality": "good"},
            fix_code="def fixed(): pass",
            test_result={"passed": True},
            verification={"final_decision": "Approve"},
            total_tokens=5000,
            stages=["review", "fix", "verify"],
            errors=["some error"],
            fix_iterations=1,
            elapsed_seconds=15.5,
        )
        assert result.fix_code == "def fixed(): pass"
        assert result.total_tokens == 5000
        assert len(result.stages) == 3
