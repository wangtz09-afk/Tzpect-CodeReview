"""Tests for utils.output_formatter module."""
import json
import pytest
from utils.output_formatter import to_sarif, to_html, to_enhanced_json, _sarif_level, _parse_line


class TestToSarif:
    def test_empty_results(self):
        sarif = to_sarif([])
        assert sarif["version"] == "2.1.0"
        assert sarif["runs"] == []

    def test_with_issues(self, mock_result):
        sarif = to_sarif([mock_result])
        assert len(sarif["runs"]) == 1
        run = sarif["runs"][0]
        assert run["tool"]["driver"]["name"] == "AI Code Review Agent"
        assert len(run["results"]) > 0

    def test_sarif_level_mapping(self):
        assert _sarif_level("critical") == "error"
        assert _sarif_level("high") == "error"
        assert _sarif_level("medium") == "warning"
        assert _sarif_level("low") == "note"
        assert _sarif_level("unknown") == "warning"


class TestToHtml:
    def test_html_output(self, mock_result):
        html = to_html([mock_result], repo_path="/test", branch="main")
        assert "<html>" in html
        assert "<style>" in html
        assert "Code Review Report" in html
        assert "/test" in html

    def test_html_escaping(self):
        """Ensure HTML entities are properly escaped."""
        from core.pipeline import PipelineResult
        result = PipelineResult(
            file_path="<script>.py",
            language="python",
            review_result={"issues": [], "overall_quality": "<b>good</b>"},
        )
        html = to_html([result])
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_summary_cards(self, mock_result):
        html = to_html([mock_result])
        assert "Files Reviewed" in html
        assert "Issues Found" in html
        assert "Total Tokens" in html


class TestToEnhancedJson:
    def test_json_output(self, mock_result):
        json_str = to_enhanced_json([mock_result])
        data = json.loads(json_str)
        assert data["schema_version"] == "1.0"
        assert "summary" in data
        assert "files" in data
        assert len(data["files"]) == 1

    def test_summary_aggregation(self, mock_result):
        results = [mock_result, mock_result]
        json_str = to_enhanced_json(results)
        data = json.loads(json_str)
        assert data["summary"]["total_files"] == 2

    def test_fix_analysis_included(self):
        from core.pipeline import PipelineResult
        from utils.fix_verifier import FixAnalysis
        result = PipelineResult(
            file_path="test.py",
            language="python",
            review_result={"issues": [], "overall_quality": "good"},
            fix_code="def fixed(): pass",
            fix_analysis=FixAnalysis(is_valid=True, regression_risk="low"),
        )
        json_str = to_enhanced_json([result])
        data = json.loads(json_str)
        assert data["files"][0]["fix"]["generated"] is True
        assert data["files"][0]["fix"]["analysis"]["is_valid"] is True


class TestHelpers:
    def test_parse_line_from_location(self):
        assert _parse_line("line 42") == 42
        assert _parse_line("L42") == 42
        assert _parse_line("file.py:42") == 42
        assert _parse_line("unknown") == 1
        assert _parse_line("") == 1


@pytest.fixture
def mock_result():
    """Create a mock PipelineResult for testing."""
    from core.pipeline import PipelineResult
    return PipelineResult(
        file_path="test.py",
        language="python",
        review_result={
            "issues": [
                {
                    "severity": "high",
                    "type": "SQL Injection",
                    "location": "line 42",
                    "description": "SQL query uses string concatenation",
                    "suggestion": "Use parameterized queries",
                }
            ],
            "overall_quality": "needs improvement",
        },
        fix_code="def fixed(): pass",
        fix_iterations=1,
        verification={"final_decision": "Needs More Work", "confidence": "medium", "can_merge": False},
        total_tokens=5000,
        elapsed_seconds=30.5,
    )
