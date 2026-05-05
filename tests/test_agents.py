"""Tests for agents module."""
import pytest
from agents.reviewer import ReviewerAgent
from agents.fixer import FixerAgent
from agents.verifier import VerifierAgent
from agents.base import AgentResult


class TestReviewerAgent:
    def setup_method(self):
        self.agent = ReviewerAgent()

    def test_system_prompt(self):
        prompt = self.agent.get_system_prompt()
        assert "SQL Injection" in prompt or "SQL" in prompt
        assert "XSS" in prompt
        assert "JSON" in prompt

    def test_build_user_prompt(self):
        prompt = self.agent.build_user_prompt(
            file_path="test.py",
            language="python",
            diff="--- a\n+++ b\n",
            content="def foo(): pass",
            commit_message="test commit",
        )
        assert "test.py" in prompt
        assert "python" in prompt
        assert "line" in prompt.lower() or "|" in prompt

    def test_build_user_prompt_no_content(self):
        prompt = self.agent.build_user_prompt(
            file_path="test.py",
            language="python",
            content="",
        )
        assert "test.py" in prompt

    def test_parse_result_valid_json(self):
        result = AgentResult(
            agent_name="ReviewerAgent",
            success=True,
            output='```json\n{"overall_quality": "good", "issues": [], "approved": true}\n```',
        )
        parsed = self.agent.parse_result(result)
        assert parsed["overall_quality"] == "good"
        assert parsed["issues"] == []
        assert parsed["approved"] is True

    def test_parse_result_plain_json(self):
        result = AgentResult(
            agent_name="ReviewerAgent",
            success=True,
            output='{"overall_quality": "poor", "issues": [{"severity": "high"}], "approved": false}',
        )
        parsed = self.agent.parse_result(result)
        assert parsed["overall_quality"] == "poor"
        assert len(parsed["issues"]) == 1

    def test_parse_result_invalid_json(self):
        result = AgentResult(
            agent_name="ReviewerAgent",
            success=True,
            output="This is not JSON at all, just some text",
        )
        parsed = self.agent.parse_result(result)
        assert parsed["approved"] is False
        assert parsed["requires_fix"] is True

    def test_parse_result_failed(self):
        result = AgentResult(
            agent_name="ReviewerAgent",
            success=False,
            output="",
            error="API timeout",
        )
        parsed = self.agent.parse_result(result)
        assert "error" in parsed
        assert parsed["issues"] == []

    def test_line_number_addition(self):
        code = "\n".join([f"line {i}" for i in range(100)])
        numbered = self.agent._add_line_numbers(code)
        assert "  1 |" in numbered
        assert " 100 |" in numbered

    def test_line_number_truncation(self):
        code = "\n".join([f"line {i}" for i in range(1000)])
        numbered = self.agent._add_line_numbers(code)
        assert "truncated" in numbered.lower()
        assert "1000" in numbered


class TestFixerAgent:
    def setup_method(self):
        self.agent = FixerAgent()

    def test_system_prompt(self):
        prompt = self.agent.get_system_prompt()
        assert "FIX" in prompt or "fix" in prompt
        assert "code" in prompt.lower()

    def test_build_user_prompt(self):
        prompt = self.agent.build_user_prompt(
            file_path="test.py",
            language="python",
            content="def foo(): pass",
            issues=[
                {"severity": "high", "type": "bug", "location": "test.py:1",
                 "description": "Bug here", "suggestion": "Fix it"},
            ],
        )
        assert "test.py" in prompt
        assert "Bug here" in prompt

    def test_build_user_prompt_no_fixable_issues(self):
        prompt = self.agent.build_user_prompt(
            file_path="test.py",
            language="python",
            content="def foo(): pass",
            issues=[
                {"severity": "low", "type": "style", "location": "test.py:1",
                 "description": "Minor issue"},
            ],
        )
        assert "low" in prompt.lower() or "no fix" in prompt.lower()

    def test_extract_code_from_markdown(self):
        result = AgentResult(
            agent_name="FixerAgent",
            success=True,
            output="## Fix Summary\n- Bug fixed\n\n## Fixed Code\n```python\ndef fixed(): pass\n```\n",
        )
        code = self.agent.extract_code(result)
        assert "def fixed()" in code

    def test_extract_code_from_last_block(self):
        result = AgentResult(
            agent_name="FixerAgent",
            success=True,
            output="Some text\n```java\npublic class Test {}\n```\n",
        )
        code = self.agent.extract_code(result)
        assert "public class Test" in code

    def test_extract_code_no_blocks(self):
        result = AgentResult(
            agent_name="FixerAgent",
            success=True,
            output="Just plain code text",
        )
        code = self.agent.extract_code(result)
        assert code == "Just plain code text"

    def test_extract_code_failed_result(self):
        result = AgentResult(
            agent_name="FixerAgent",
            success=False,
            output="",
            error="API error",
        )
        code = self.agent.extract_code(result)
        assert code == ""


class TestVerifierAgent:
    def setup_method(self):
        self.agent = VerifierAgent()

    def test_system_prompt(self):
        prompt = self.agent.get_system_prompt()
        assert "Approve" in prompt or "approve" in prompt
        assert "JSON" in prompt

    def test_build_user_prompt(self):
        prompt = self.agent.build_user_prompt(
            review_result={
                "overall_quality": "poor",
                "summary": "Many issues",
                "issues": [{"severity": "high", "location": "test.py:1", "description": "Bug"}],
            },
            fix_code="def fixed(): pass",
            test_result={"passed": True, "output": "Tests passed"},
            file_path="test.py",
            language="python",
            fix_iterations=1,
        )
        assert "test.py" in prompt
        assert "poor" in prompt.lower()

    def test_parse_result_valid_json(self):
        result = AgentResult(
            agent_name="VerifierAgent",
            success=True,
            output='```json\n{"final_decision": "Approve", "can_merge": true, "confidence": "high"}\n```',
        )
        parsed = self.agent.parse_result(result)
        assert parsed["final_decision"] == "Approve"
        assert parsed["can_merge"] is True
        assert parsed["confidence"] == "high"

    def test_parse_result_invalid_json(self):
        result = AgentResult(
            agent_name="VerifierAgent",
            success=True,
            output="Not valid JSON",
        )
        parsed = self.agent.parse_result(result)
        assert parsed["can_merge"] is False
        assert "raw_output" in parsed

    def test_parse_result_failed(self):
        result = AgentResult(
            agent_name="VerifierAgent",
            success=False,
            output="",
            error="Timeout",
        )
        parsed = self.agent.parse_result(result)
        assert "error" in parsed
