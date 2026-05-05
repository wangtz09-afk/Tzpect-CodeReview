"""Shared constants and utilities used across the project.

This module is the single source of truth for:
- Language detection from file extensions
- Directory skip lists
- API key environment variable names
"""
import os
from pathlib import Path
from typing import Optional

# ── Language Detection ──────────────────────────────────────────────────────

EXTENSION_LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".sh": "bash",
    ".sql": "sql",
    ".vue": "vue",
    ".css": "css",
    ".html": "html",
    ".xml": "xml",
    ".svelte": "svelte",
    ".scala": "scala",
}

SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go",
    ".rs", ".c", ".cpp", ".h", ".hpp", ".rb", ".php",
    ".swift", ".kt", ".vue", ".sql", ".cs", ".scala",
}


def get_language(file_path: str) -> str:
    """Detect programming language from file extension.

    Args:
        file_path: File path (absolute or relative).

    Returns:
        Language name string, or "unknown" if not recognized.
    """
    ext = Path(file_path).suffix.lower()
    return EXTENSION_LANGUAGE_MAP.get(ext, "unknown")


# ── Directory Filtering ─────────────────────────────────────────────────────

SKIP_DIRS = {
    "__pycache__", "node_modules", ".git", ".idea", ".vscode",
    "target", "build", "dist", "out", ".gradle", ".settings",
    ".classpath", ".project", "venv", ".venv", "env",
    "coverage", ".cache", "tmp", "temp", ".tox", ".mypy_cache",
    ".next", ".nuxt", ".output",
}


def should_skip_dir(dir_name: str) -> bool:
    """Check if a directory should be skipped during source scanning.

    Args:
        dir_name: Directory name (not full path).

    Returns:
        True if the directory should be skipped.
    """
    return dir_name.lower() in SKIP_DIRS


# ── API Key Resolution ──────────────────────────────────────────────────────

API_KEY_ENV_VARS = (
    "DASHSCOPE_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
)


def find_api_key() -> str:
    """Find the first available API key from environment variables.

    Checks DASHSCOPE_API_KEY, DEEPSEEK_API_KEY, OPENAI_API_KEY in order.

    Returns:
        API key string, or empty string if none found.
    """
    for key_name in API_KEY_ENV_VARS:
        val = os.getenv(key_name, "")
        if val:
            return val
    return ""
