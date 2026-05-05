"""Reviewer Agent — 代码质量审查 Agent."""
import json
from dataclasses import dataclass, field
from typing import Optional

from agents.base import BaseAgent, AgentResult
from config import get_settings
from utils.prompt_loader import load_prompt


@dataclass
class ReviewContext:
    """Extra context for review to improve accuracy."""
    project_context: str = ""  # Framework info, patterns, constraints
    custom_rules: str = ""  # Custom rule config prompt section
    cross_file_context: str = ""  # Related files, interfaces, etc.
    feedback_context: str = ""  # Historical feedback for this file
    commit_message: str = ""

    def to_prompt(self) -> str:
        """Combine all context into a single prompt section."""
        parts = []
        if self.project_context:
            parts.append(self.project_context)
        if self.custom_rules:
            parts.append(self.custom_rules)
        if self.cross_file_context:
            parts.append(self.cross_file_context)
        if self.feedback_context:
            parts.append(self.feedback_context)
        return "\n".join(parts) if parts else ""


class ReviewerAgent(BaseAgent):
    """审查代码变更，输出结构化的问题报告。"""

    def __init__(self):
        settings = get_settings()
        super().__init__("ReviewerAgent", model=settings.get("reviewer_model", "deepseek-chat"))

    def get_system_prompt(self, **kwargs) -> str:
        """Get system prompt from template, optionally augmented with project context."""
        extra_context = kwargs.get("review_context")
        context_prompt = ""
        if extra_context and hasattr(extra_context, 'to_prompt'):
            context_prompt = extra_context.to_prompt()

        base_prompt = load_prompt("reviewer_system.md")

        # Inject project context if available
        if context_prompt:
            base_prompt = base_prompt.replace(
                "## Rules",
                f"## Project Context (IMPORTANT — use to guide your review)\n\n{context_prompt}\n\n## Rules"
            )

        return base_prompt

    def _add_line_numbers(self, code: str, max_lines: int = 500) -> str:
        """Add line numbers to code for precise location references."""
        all_lines = code.split("\n")
        lines = all_lines[:max_lines]
        numbered = "\n".join(f"  {i+1:4d} | {line}" for i, line in enumerate(lines))
        if len(all_lines) > max_lines:
            numbered += f"\n  ... (truncated, {len(all_lines)} total lines)"
        return numbered

    def build_user_prompt(self, **kwargs) -> str:
        file_path = kwargs.get("file_path", "unknown")
        language = kwargs.get("language", "unknown")
        diff = kwargs.get("diff", "")
        content = kwargs.get("content", "")
        commit_message = kwargs.get("commit_message", "")
        incremental = kwargs.get("incremental", False)

        # In incremental mode, extract only changed lines for large files
        if incremental and diff and content:
            from utils.incremental import extract_changed_lines, is_incremental_beneficial
            if is_incremental_beneficial(diff, content):
                content = extract_changed_lines(content, diff)

        code_with_lines = self._add_line_numbers(content) if content else "(No file content available)"

        prompt = f"""You are reviewing changes in a {language} file.

**File**: `{file_path}`
**Language**: {language}
**Commit Message**: {commit_message if commit_message else 'N/A'}
"""
        if incremental and diff:
            prompt += f"**Mode**: Incremental (only changed lines shown)\n\n"

        prompt += f"""## Complete Source Code (with line numbers)

{code_with_lines}
"""
        if diff:
            prompt += f"""
## Git Diff

```diff
{diff[:6000]}
```
"""
        prompt += """
Perform a thorough review following your checklist. Output ONLY the JSON result."""
        return prompt

    def parse_result(self, result: AgentResult) -> dict:
        """解析 Agent 输出为结构化数据。"""
        if not result.success:
            return {"error": result.error, "issues": []}

        output = result.output.strip()

        # Try to extract JSON from markdown code block
        if "```json" in output:
            json_str = output.split("```json")[1].split("```")[0].strip()
        elif "```" in output:
            json_str = output.split("```")[1].strip()
        else:
            json_str = output

        import json
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # Fallback: treat as text review
            return {
                "overall_quality": "一般",
                "summary": "审查完成（格式解析失败，见原文）",
                "issues": [],
                "raw_output": output,
                "approved": False,
                "requires_fix": True,
            }
