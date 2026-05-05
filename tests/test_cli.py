"""Tests for CLI commands."""
import pytest
from click.testing import CliRunner
from main import cli, _apply_filters
from core.output import filter_issues_by_severity
from core.git_ops import CodeChange


class TestApplyFilters:
    def test_filters_unknown_language(self):
        changes = [
            CodeChange(file_path="test.py", language="python"),
            CodeChange(file_path="test.unknown", language="unknown"),
        ]
        result = _apply_filters(changes)
        assert len(result) == 1
        assert result[0].language == "python"

    def test_filters_empty_language(self):
        changes = [
            CodeChange(file_path="test.py", language="python"),
            CodeChange(file_path="test", language=""),
        ]
        result = _apply_filters(changes)
        assert len(result) == 1

    def test_language_filter(self):
        changes = [
            CodeChange(file_path="test.py", language="python"),
            CodeChange(file_path="test.java", language="java"),
            CodeChange(file_path="test.js", language="javascript"),
        ]
        result = _apply_filters(changes, language_filter="java,python")
        assert len(result) == 2

    def test_max_files(self):
        changes = [
            CodeChange(file_path=f"test{i}.py", language="python")
            for i in range(10)
        ]
        result = _apply_filters(changes, max_files=3)
        assert len(result) == 3


class TestSeverityFilter:
    def test_no_filter(self):
        issues = [
            {"severity": "critical"},
            {"severity": "low"},
        ]
        result = filter_issues_by_severity(issues)
        assert len(result) == 2

    def test_filter_high_and_above(self):
        issues = [
            {"severity": "critical"},
            {"severity": "high"},
            {"severity": "medium"},
            {"severity": "low"},
        ]
        result = filter_issues_by_severity(issues, "high")
        assert len(result) == 2

    def test_filter_medium_and_above(self):
        issues = [
            {"severity": "critical"},
            {"severity": "high"},
            {"severity": "medium"},
            {"severity": "low"},
        ]
        result = filter_issues_by_severity(issues, "medium")
        assert len(result) == 3

    def test_filter_critical_only(self):
        issues = [
            {"severity": "critical"},
            {"severity": "high"},
            {"severity": "medium"},
            {"severity": "low"},
        ]
        result = filter_issues_by_severity(issues, "critical")
        assert len(result) == 1

    def test_case_insensitive(self):
        issues = [{"severity": "CRITICAL"}, {"severity": "Low"}]
        result = filter_issues_by_severity(issues, "HIGH")
        assert len(result) == 1


class TestCliRunner:
    def test_cli_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "AI Code Review" in result.output or "code review" in result.output.lower()

    def test_review_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["review", "--help"])
        assert result.exit_code == 0
        assert "--staged" in result.output
        assert "--json" in result.output
        assert "--parallel" in result.output
        assert "--checkpoint-dir" in result.output
        assert "--budget" in result.output

    def test_scan_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["scan", "--help"])
        assert result.exit_code == 0

    def test_fix_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["fix", "--help"])
        assert result.exit_code == 0

    def test_apply_fixes_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["apply-fixes", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.output
        assert "--force" in result.output
