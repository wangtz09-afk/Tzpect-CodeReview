"""Prompt template loader for agent system prompts.

Loads prompt templates from the prompts/ directory and supports
variable substitution via Python str.format().

Usage:
    from utils.prompt_loader import load_prompt

    system = load_prompt("reviewer_system.md")
    system = load_prompt("reviewer_system.md", extra_context="Be strict about null checks")
"""
from pathlib import Path
from string import Template
from typing import Optional

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(filename: str, **kwargs: str) -> str:
    """Load a prompt template from the prompts/ directory.

    Args:
        filename: Template filename (e.g. "reviewer_system.md").
        **kwargs: Variables to substitute using ${var} syntax in the template.

    Returns:
        The rendered prompt string.

    Raises:
        FileNotFoundError: If the template file doesn't exist.
    """
    path = _PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")

    content = path.read_text(encoding="utf-8")

    if kwargs:
        template = Template(content)
        content = template.safe_substitute(kwargs)

    return content


def list_prompts() -> list[str]:
    """List all available prompt template filenames."""
    if not _PROMPTS_DIR.exists():
        return []
    return [f.name for f in _PROMPTS_DIR.iterdir() if f.suffix == ".md"]
