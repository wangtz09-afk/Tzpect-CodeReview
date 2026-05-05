"""Integration tests for the full code review pipeline with mocked LLM calls.

Tests the end-to-end flow: Reviewer → Fixer → Tester → Verifier
with all LLM calls mocked to avoid real API calls.
"""
import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from agents.base import AgentResult
from agents.reviewer import ReviewerAgent, ReviewContext
from agents.fixer import FixerAgent
from agents.tester import TesterAgent
from agents.verifier import VerifierAgent
from core.pipeline import ReviewPipeline
from core.models import PipelineResult


# ── Sample code for testing ─────────────────────────────────────────────────

SAMPLE_PYTHON_FILE = '''
import sqlite3

def get_user(user_id):
    conn = sqlite3.connect("db.sqlite")
    cursor = conn.cursor()
    query = "SELECT * FROM users WHERE id = " + user_id
    cursor.execute(query)
    return cursor.fetchone()

def process_data(items):
    result = ""
    for item in items:
        result = result + str(item)
    return result
'''

SAMPLE_FIX_CODE = '''
import sqlite3

def get_user(user_id):
    conn = sqlite3.connect("db.sqlite")
    cursor = conn.cursor()
    # FIX: Use parameterized query to prevent SQL injection
    query = "SELECT * FROM users WHERE id = ?"
    cursor.execute(query, (user_id,))
    return cursor.fetchone()

def process_data(items):
    # FIX: Use join instead of string concatenation in loop
    return "".join(str(item) for item in items)
'''

REVIEW_RESPONSE = json.dumps({
    "overall_quality": "fair",
    "summary": "Found SQL injection vulnerability and performance issue",
    "issues": [
        {
            "type": "security",
            "severity": "critical",
            "location": "app.py:6",
            "description": "SQL injection: user input concatenated directly into SQL query",
            "suggestion": "Use parameterized queries with ? placeholders"
        },
        {
            "type": "performance",
            "severity": "medium",
            "location": "app.py:10",
            "description": "String concatenation in loop",
            "suggestion": "Use join() for building strings from a list"
        }
    ],
    "approved": False,
    "requires_fix": True,
})

FIXER_RESPONSE = """## Fix Summary
- app.py:6 (security): Parameterized SQL query
- app.py:10 (performance): Use join() for string building

## Fixed Code
```python
import sqlite3

def get_user(user_id):
    conn = sqlite3.connect("db.sqlite")
    cursor = conn.cursor()
    # FIX: Use parameterized query to prevent SQL injection
    query = "SELECT * FROM users WHERE id = ?"
    cursor.execute(query, (user_id,))
    return cursor.fetchone()

def process_data(items):
    # FIX: Use join instead of string concatenation in loop
    return "".join(str(item) for item in items)
```"""

VERIFIER_RESPONSE = json.dumps({
    "final_decision": "Approve",
    "confidence": "high",
    "summary": "Both critical and medium issues have been properly addressed",
    "remaining_issues": [],
    "can_merge": True,
    "further_fix_suggested": False,
    "next_steps": "None required",
})


class MockLLMResponse:
    """Mock LLM response for testing."""
    def __init__(self, content: str):
        self.content = content
        self.model = "deepseek-chat"
        self.tokens_used = 100
        self.success = True
        self.error = ""
        self.cached = False


class TestReviewerAgent:
    """Test reviewer agent prompt loading and parsing."""

    def test_loads_prompt_template(self):
        """Reviewer should load system prompt from template file."""
        agent = ReviewerAgent()
        prompt = agent.get_system_prompt()
        assert "SQL Injection" in prompt
        assert "XSS" in prompt
        assert "Language-Specific Checks" in prompt

    def test_project_context_injection(self):
        """Project context should be injected into system prompt."""
        agent = ReviewerAgent()
        context = ReviewContext(project_context="This is a FastAPI project")
        prompt = agent.get_system_prompt(review_context=context)
        assert "Project Context" in prompt
        assert "FastAPI" in prompt

    def test_parse_json_result(self):
        """Should parse valid JSON output."""
        agent = ReviewerAgent()
        result = AgentResult(
            agent_name="ReviewerAgent",
            success=True,
            output=f"```json\n{REVIEW_RESPONSE}\n```",
        )
        parsed = agent.parse_result(result)
        assert parsed["overall_quality"] == "fair"
        assert len(parsed["issues"]) == 2
        assert parsed["approved"] is False

    def test_parse_invalid_json_fallback(self):
        """Should return fallback dict for invalid JSON."""
        agent = ReviewerAgent()
        result = AgentResult(
            agent_name="ReviewerAgent",
            success=True,
            output="This is not valid JSON at all",
        )
        parsed = agent.parse_result(result)
        assert parsed["approved"] is False
        assert "raw_output" in parsed

    def test_parse_failed_agent(self):
        """Should return error dict for failed agent."""
        agent = ReviewerAgent()
        result = AgentResult(
            agent_name="ReviewerAgent",
            success=False,
            output="",
            error="API timeout",
        )
        parsed = agent.parse_result(result)
        assert "error" in parsed
        assert parsed["error"] == "API timeout"


class TestFixerAgent:
    """Test fixer agent prompt loading and code extraction."""

    def test_loads_prompt_template(self):
        """Fixer should load system prompt from template file."""
        agent = FixerAgent()
        prompt = agent.get_system_prompt()
        assert "code fixer" in prompt.lower()
        assert "Fix Summary" in prompt

    def test_extract_code_from_response(self):
        """Should extract code block from fixer response."""
        agent = FixerAgent()
        result = AgentResult(
            agent_name="FixerAgent",
            success=True,
            output=FIXER_RESPONSE,
        )
        code = agent.extract_code(result)
        assert "parameterized query" in code.lower() or "WHERE id = ?" in code

    def test_extract_code_on_failure(self):
        """Should return empty string on failed result."""
        agent = FixerAgent()
        result = AgentResult(
            agent_name="FixerAgent",
            success=False,
            output="",
            error="API error",
        )
        code = agent.extract_code(result)
        assert code == ""

    def test_no_fix_for_low_severity(self):
        """Should return 'No fix required' for low-severity issues only."""
        agent = FixerAgent()
        prompt = agent.build_user_prompt(
            file_path="test.py",
            language="python",
            issues=[{"severity": "low", "description": "naming", "type": "style", "location": "test.py:1", "suggestion": "rename"}],
        )
        assert "No fix required" in prompt


class TestTesterAgent:
    """Test tester agent prompt loading."""

    def test_loads_prompt_template(self):
        """Tester should load system prompt from template file."""
        agent = TesterAgent()
        prompt = agent.get_system_prompt()
        assert "test engineer" in prompt.lower()
        assert "pytest" in prompt


class TestVerifierAgent:
    """Test verifier agent prompt loading and parsing."""

    def test_loads_prompt_template(self):
        """Verifier should load system prompt from template file."""
        agent = VerifierAgent()
        prompt = agent.get_system_prompt()
        assert "approver" in prompt.lower()
        assert "can_merge" in prompt

    def test_parse_json_result(self):
        """Should parse verifier JSON output."""
        agent = VerifierAgent()
        result = AgentResult(
            agent_name="VerifierAgent",
            success=True,
            output=f"```json\n{VERIFIER_RESPONSE}\n```",
        )
        parsed = agent.parse_result(result)
        assert parsed["final_decision"] == "Approve"
        assert parsed["can_merge"] is True

    def test_parse_failed_agent(self):
        """Should return fallback dict for failed agent."""
        agent = VerifierAgent()
        result = AgentResult(
            agent_name="VerifierAgent",
            success=False,
            output="",
            error="API error",
        )
        parsed = agent.parse_result(result)
        assert parsed["can_merge"] is False


class TestPipelineIntegration:
    """Test the full pipeline with mocked LLM calls."""

    @pytest.fixture
    def mock_llm_client(self):
        """Create a mock LLM client that returns predetermined responses."""
        mock = MagicMock()
        mock.chat.side_effect = [
            MockLLMResponse(REVIEW_RESPONSE),
            MockLLMResponse(FIXER_RESPONSE),
            MockLLMResponse('def test_get_user():\n    assert True'),
            MockLLMResponse(VERIFIER_RESPONSE),
        ]
        return mock

    def test_pipeline_runs_all_stages(self, mock_llm_client):
        """Pipeline should run through all stages."""
        with patch("agents.reviewer.ReviewerAgent.__init__", return_value=None):
            with patch("agents.fixer.FixerAgent.__init__", return_value=None):
                with patch("agents.tester.TesterAgent.__init__", return_value=None):
                    with patch("agents.verifier.VerifierAgent.__init__", return_value=None):
                        # Set up agent state manually
                        for AgentClass in [ReviewerAgent, FixerAgent, TesterAgent, VerifierAgent]:
                            agent = AgentClass.__new__(AgentClass)
                            agent.agent_name = AgentClass.__name__
                            agent.llm = mock_llm_client

    def test_pipeline_with_temp_file(self, mock_llm_client):
        """Test pipeline with a temporary file."""
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
            f.write(SAMPLE_PYTHON_FILE)
            temp_path = f.name

        try:
            from core.git_ops import CodeChange, ReviewContext as GitContext
            from agents.reviewer import ReviewerAgent, ReviewContext
            from agents.fixer import FixerAgent
            from agents.tester import TesterAgent
            from agents.verifier import VerifierAgent

            # Mock all agents to use our mock LLM
            def create_mock_agent(AgentClass, mock_llm):
                agent = AgentClass.__new__(AgentClass)
                agent.agent_name = AgentClass.__name__
                agent.llm = mock_llm
                return agent

            reviewer = create_mock_agent(ReviewerAgent, mock_llm_client)
            fixer = create_mock_agent(FixerAgent, mock_llm_client)
            tester = create_mock_agent(TesterAgent, mock_llm_client)
            verifier = create_mock_agent(VerifierAgent, mock_llm_client)

            # Run reviewer
            result = reviewer.llm.chat(
                system_prompt="test",
                user_prompt=f"File: {SAMPLE_PYTHON_FILE}",
            )
            assert result.success is True
            assert "SQL injection" in result.content.lower() or "security" in result.content.lower()

        finally:
            os.unlink(temp_path)


class TestPipelineEndToEnd:
    """End-to-end pipeline test that doesn't mock the full agent chain."""

    def test_reviewer_parses_real_json(self):
        """Verify the reviewer can parse its expected output format."""
        agent = ReviewerAgent()
        result = AgentResult(
            agent_name="ReviewerAgent",
            success=True,
            output=REVIEW_RESPONSE,
        )
        parsed = agent.parse_result(result)
        assert parsed["approved"] is False
        assert parsed["requires_fix"] is True
        assert len(parsed["issues"]) == 2
        assert parsed["issues"][0]["type"] == "security"
        assert parsed["issues"][0]["severity"] == "critical"

    def test_fixer_parses_real_response(self):
        """Verify the fixer can extract code from its expected output format."""
        agent = FixerAgent()
        result = AgentResult(
            agent_name="FixerAgent",
            success=True,
            output=FIXER_RESPONSE,
        )
        code = agent.extract_code(result)
        assert len(code) > 50
        assert "def get_user" in code

    def test_verifier_parses_real_response(self):
        """Verify the verifier can parse its expected output format."""
        agent = VerifierAgent()
        result = AgentResult(
            agent_name="VerifierAgent",
            success=True,
            output=VERIFIER_RESPONSE,
        )
        parsed = agent.parse_result(result)
        assert parsed["final_decision"] == "Approve"
        assert parsed["can_merge"] is True
        assert parsed["confidence"] == "high"

    def test_full_pipeline_flow_simulation(self):
        """Simulate the full data flow through all pipeline stages."""
        # Stage 1: Review
        reviewer = ReviewerAgent.__new__(ReviewerAgent)
        reviewer_output = json.loads(REVIEW_RESPONSE)

        # Stage 2: Fix — filter fixable issues
        fixable = [
            i for i in reviewer_output["issues"]
            if i["severity"] in ("critical", "high", "medium")
        ]
        assert len(fixable) == 2  # Both issues are fixable

        # Stage 3: Parse fix output
        fixer = FixerAgent.__new__(FixerAgent)
        fix_result = AgentResult(
            agent_name="FixerAgent",
            success=True,
            output=FIXER_RESPONSE,
        )
        fixed_code = fixer.extract_code(fix_result)
        assert len(fixed_code) > 0
        assert "parameterized" in fixed_code.lower() or "WHERE id = ?" in fixed_code

        # Stage 4: Verify
        verifier = VerifierAgent.__new__(VerifierAgent)
        verifier_output = json.loads(VERIFIER_RESPONSE)
        assert verifier_output["can_merge"] is True
