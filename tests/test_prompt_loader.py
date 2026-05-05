"""Tests for prompt template loader."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from utils.prompt_loader import load_prompt, list_prompts, _PROMPTS_DIR


class TestPromptLoader:
    """Test prompt template loading and variable substitution."""

    def test_loads_existing_prompt(self):
        """Should load a valid prompt template."""
        content = load_prompt("reviewer_system.md")
        assert isinstance(content, str)
        assert len(content) > 100
        assert "senior code reviewer" in content

    def test_loads_fixer_prompt(self):
        """Should load the fixer prompt template."""
        content = load_prompt("fixer_system.md")
        assert "expert code fixer" in content.lower()

    def test_loads_tester_prompt(self):
        """Should load the tester prompt template."""
        content = load_prompt("tester_system.md")
        assert "test engineer" in content.lower()

    def test_loads_verifier_prompt(self):
        """Should load the verifier prompt template."""
        content = load_prompt("verifier_system.md")
        assert "approver" in content.lower()

    def test_raises_for_missing_prompt(self):
        """Should raise FileNotFoundError for non-existent template."""
        with pytest.raises(FileNotFoundError, match="not found"):
            load_prompt("nonexistent.md")

    def test_variable_substitution(self):
        """Should substitute ${var} placeholders."""
        with tempfile.NamedTemporaryFile(
            suffix=".md", mode="w", delete=False, dir=_PROMPTS_DIR, encoding="utf-8"
        ) as f:
            f.write("Hello ${name}, welcome to ${project}!")
            f.flush()
            basename = Path(f.name).name

        try:
            content = load_prompt(basename, name="Alice", project="CodeReview")
            assert "Hello Alice, welcome to CodeReview!" in content
        finally:
            os.unlink(f.name)

    def test_missing_var_replaced_empty(self):
        """Should replace missing variables with empty string (safe_substitute)."""
        with tempfile.NamedTemporaryFile(
            suffix=".md", mode="w", delete=False, dir=_PROMPTS_DIR, encoding="utf-8"
        ) as f:
            f.write("Hello ${name}, ${missing} stays")
            f.flush()
            basename = Path(f.name).name

        try:
            content = load_prompt(basename, name="Bob")
            assert "Hello Bob" in content
        finally:
            os.unlink(f.name)

    def test_list_prompts(self):
        """Should list all .md files in prompts directory."""
        prompts = list_prompts()
        assert isinstance(prompts, list)
        assert "reviewer_system.md" in prompts
        assert "fixer_system.md" in prompts
        assert "tester_system.md" in prompts
        assert "verifier_system.md" in prompts

    def test_all_prompts_exist(self):
        """All expected prompts should be present."""
        prompts = list_prompts()
        assert len(prompts) >= 4
