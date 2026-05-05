"""Shared data models for the code review pipeline.

This module contains all dataclasses and exception classes used across
the codebase. It has NO external dependencies to prevent circular imports.

Usage:
    from core.models import PipelineResult, FixAnalysis, StageError
"""
from dataclasses import dataclass, field
from typing import Optional


# ── Pipeline Exceptions ─────────────────────────────────────────────────────

class PipelineError(Exception):
    """Base exception for pipeline errors."""
    pass


class StageError(PipelineError):
    """Error in a specific pipeline stage."""
    def __init__(self, stage: str, message: str, is_retryable: bool = True):
        self.stage = stage
        self.is_retryable = is_retryable
        super().__init__(f"[{stage}] {message}")


class ConfigurationError(PipelineError):
    """Configuration-related error."""
    pass


class APIError(PipelineError):
    """API-related error."""
    def __init__(self, message: str, status_code: int = 0):
        self.status_code = status_code
        super().__init__(message)


# ── Fix Verification Models ─────────────────────────────────────────────────

@dataclass
class FixIssue:
    """An issue found in fix analysis."""
    severity: str  # critical, high, medium, low
    category: str  # regression, new_issue, incomplete_fix
    description: str
    line_range: str = ""


@dataclass
class FixAnalysis:
    """Result of fix correctness analysis."""
    is_valid: bool = True
    issues: list = field(default_factory=list)  # list[FixIssue]
    lines_removed: int = 0
    lines_added: int = 0
    regression_risk: str = "low"  # low, medium, high


# ── Pipeline Result ─────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """The complete result of a review pipeline run for a single file."""
    file_path: str
    language: str
    review_result: dict = field(default_factory=dict)
    fix_code: str = ""
    fix_analysis: "FixAnalysis" = field(
        default_factory=lambda: FixAnalysis(is_valid=True)
    )
    test_result: dict = field(default_factory=dict)
    verification: dict = field(default_factory=dict)
    total_tokens: int = 0
    stages: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    fix_iterations: int = 0
    elapsed_seconds: float = 0.0
    # Enhanced metadata
    fix_quality_score: float = 1.0
    project_frameworks: list = field(default_factory=list)
