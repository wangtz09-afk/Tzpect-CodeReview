"""Verifier Agent — 最终验证 Agent。"""
import json
from agents.base import BaseAgent, AgentResult
from config import get_settings
from utils.prompt_loader import load_prompt


class VerifierAgent(BaseAgent):
    """综合审查结果、修复内容和测试结果，给出最终结论。"""

    def __init__(self):
        settings = get_settings()
        super().__init__("VerifierAgent", model=settings.get("verifier_model", "deepseek-chat"))

    def get_system_prompt(self) -> str:
        return load_prompt("verifier_system.md")

    def build_user_prompt(self, **kwargs) -> str:
        review_result = kwargs.get("review_result", {})
        fix_code = kwargs.get("fix_code", "")
        test_result = kwargs.get("test_result", {})
        file_path = kwargs.get("file_path", "unknown")
        language = kwargs.get("language", "unknown")
        fix_iterations = kwargs.get("fix_iterations", 0)

        review_quality = review_result.get("overall_quality", "N/A")
        review_summary = review_result.get("summary", "")
        issues = review_result.get("issues", [])

        issues_text = ""
        for issue in issues:
            issues_text += (
                f"- [{issue.get('severity', 'unknown').upper()}] "
                f"{issue.get('location', '?')}: {issue.get('description', '?')}\n"
                f"  Suggestion: {issue.get('suggestion', 'N/A')}\n"
            )

        test_passed = test_result.get("passed") if test_result else None
        test_output = test_result.get("output", "")[:500] if test_result else ""
        test_error = test_result.get("error", "")[:500] if test_result else ""

        test_status = "PASSED" if test_passed else ("FAILED" if test_passed is False else "SKIPPED")
        fix_code_block = f"```{language}\n{fix_code[:3000]}\n```" if fix_code else "(No fix was generated)"
        no_issues_text = "  (No issues found)" + "\n"
        issues_display = issues_text if issues_text else no_issues_text

        return f"""Review the code review pipeline results for `{file_path}` and make your final decision.

## File Info
- **Path**: {file_path}
- **Language**: {language}
- **Fix Iterations**: {fix_iterations}

## Review Findings
- **Quality Rating**: {review_quality}
- **Summary**: {review_summary}
- **Total Issues**: {len(issues)}
- **Issue Details**:
{issues_display}

## Fix Code
{fix_code_block}

## Test Results
- **Status**: {test_status}
- **Output**: {test_output if test_output else '(none)'}
- **Error**: {test_error if test_error else '(none)'}

Based on all the above, output your JSON decision."""

    def parse_result(self, result: AgentResult) -> dict:
        """Parse agent output into structured JSON."""
        if not result.success:
            return {"error": result.error, "final_decision": "Unknown", "can_merge": False}

        output = result.output.strip()

        # Extract JSON from markdown code blocks
        if "```json" in output:
            json_str = output.split("```json")[1].split("```")[0].strip()
        elif "```" in output:
            parts = output.split("```")
            json_str = parts[1].strip() if len(parts) > 1 else output
        else:
            json_str = output

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return {
                "final_decision": output[:200],
                "can_merge": False,
                "confidence": "low",
                "summary": "Verifier output was not valid JSON (see raw output)",
                "raw_output": output[:500],
            }
