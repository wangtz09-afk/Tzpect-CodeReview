"""Fixer Agent — 自动修复代码问题 Agent."""
from agents.base import BaseAgent, AgentResult
from config import get_settings
from utils.prompt_loader import load_prompt


class FixerAgent(BaseAgent):
    """根据 Reviewer 的问题报告，生成修复代码。"""

    def __init__(self):
        settings = get_settings()
        super().__init__("FixerAgent", model=settings.get("fixer_model", "deepseek-chat"))

    def get_system_prompt(self) -> str:
        return load_prompt("fixer_system.md")

    def build_user_prompt(self, **kwargs) -> str:
        file_path = kwargs.get("file_path", "unknown")
        language = kwargs.get("language", "unknown")
        original_content = kwargs.get("content", "")
        issues = kwargs.get("issues", [])
        diff = kwargs.get("diff", "")

        # Filter fixable issues (critical, high, medium)
        fixable_issues = [
            issue for issue in issues
            if issue.get("severity") in ("critical", "high", "medium")
        ]

        if not fixable_issues:
            return "All issues are low severity. No fix needed. Reply with 'No fix required.'"

        issues_text = "\n".join([
            f"{i+1}. **{issue['location']}** ({issue.get('type', 'unknown')}, {issue['severity']}): "
            f"{issue['description']}\n"
            f"   Fix suggestion: {issue.get('suggestion', 'N/A')}"
            for i, issue in enumerate(fixable_issues)
        ])

        prompt = f"""Fix the following issues found in this {language} file:

**File**: `{file_path}`
**Language**: {language}
**Issues to fix**: {len(fixable_issues)}

## Issues

{issues_text}
"""
        if diff:
            prompt += f"""
## Original Diff

```diff
{diff[:3000]}
```
"""

        prompt += f"""
## Original Code

```{language}
{original_content[:10000]}
```

**Requirements:**
- Fix ALL listed issues while preserving working code
- Output the COMPLETE fixed file
- Add `// FIX: ...` comments next to changes
- Output format: Fix Summary section, then Fixed Code in a fenced code block
"""
        return prompt

    def extract_code(self, result: AgentResult) -> str:
        """从 Agent 输出中提取修复后的代码。"""
        if not result.success:
            return ""

        output = result.output.strip()

        # Strategy 1: Find code block after "## Fixed Code" or "## 修复后的代码"
        for marker in ("## Fixed Code", "## 修复后的代码"):
            if marker in output:
                after_marker = output.split(marker, 1)[1].strip()
                code = self._extract_first_code_block(after_marker)
                if code:
                    return code

        # Strategy 2: Find the last code block in the output
        code = self._extract_first_code_block(output)
        if code:
            return code

        # Strategy 3: Return the entire output as code (fallback)
        return output

    def _extract_first_code_block(self, text: str) -> str:
        """Extract the first fenced code block from markdown text."""
        import re
        # Match ```[lang]\n...\n```
        match = re.search(r'```(?:\w+)?\s*\n(.*?)```', text, re.DOTALL)
        if match:
            code = match.group(1).strip()
            # Remove leading language tag if accidentally included
            lines = code.split("\n")
            if lines and lines[0] in ("python", "javascript", "typescript", "java",
                                       "go", "rust", "c", "cpp", "ruby", "php",
                                       "swift", "kotlin", "csharp", "bash", "sql",
                                       "vue", "css", "html", "xml"):
                return "\n".join(lines[1:])
            return code
        return ""
