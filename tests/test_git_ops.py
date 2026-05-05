"""Tests for core.git_ops module."""
import os
import tempfile
import pytest
from pathlib import Path

from core.git_ops import (
    get_language, is_binary, should_skip_dir,
    get_repo_path, is_git_repo, get_commit_message, get_current_branch,
    scan_source_files, _parse_diff_file_path, get_diff_stats,
)


class TestGetLanguage:
    def test_python(self):
        assert get_language("main.py") == "python"

    def test_java(self):
        assert get_language("App.java") == "java"

    def test_javascript(self):
        assert get_language("index.js") == "javascript"

    def test_typescript(self):
        assert get_language("app.ts") == "typescript"
        assert get_language("component.tsx") == "typescript"

    def test_go(self):
        assert get_language("main.go") == "go"

    def test_rust(self):
        assert get_language("lib.rs") == "rust"

    def test_php(self):
        assert get_language("index.php") == "php"

    def test_unknown_extension(self):
        assert get_language("file.xyz") == "unknown"

    def test_no_extension(self):
        assert get_language("Makefile") == "unknown"

    def test_case_insensitive(self):
        assert get_language("FILE.PY") == "python"
        assert get_language("Main.JAVA") == "java"

    def test_vue_css_html(self):
        assert get_language("App.vue") == "vue"
        assert get_language("style.css") == "css"
        assert get_language("index.html") == "html"


class TestShouldSkipDir:
    def test_skip_node_modules(self):
        assert should_skip_dir("node_modules") is True

    def test_skip_git(self):
        assert should_skip_dir(".git") is True

    def test_skip_venv(self):
        assert should_skip_dir("venv") is True

    def test_skip_build(self):
        assert should_skip_dir("build") is True

    def test_skip_coverage(self):
        assert should_skip_dir("coverage") is True

    def test_skip_target(self):
        assert should_skip_dir("target") is True

    def test_skip_cache(self):
        assert should_skip_dir(".cache") is True

    def test_dont_skip_src(self):
        assert should_skip_dir("src") is False

    def test_dont_skip_lib(self):
        assert should_skip_dir("lib") is False

    def test_case_insensitive(self):
        assert should_skip_dir("NODE_MODULES") is True
        assert should_skip_dir("Build") is True


class TestIsBinary:
    def test_text_file(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Hello world\nLine 2\n")
            f.flush()
            f.close()  # Close before reading
            result = is_binary(f.name)
            assert result is False
            os.unlink(f.name)

    def test_binary_file(self):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"\x00\x01\x02\x03\x00\xff")
            f.flush()
            f.close()
            result = is_binary(f.name)
            assert result is True
            os.unlink(f.name)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.flush()
            f.close()
            result = is_binary(f.name)
            assert result is False
            os.unlink(f.name)

    def test_nonexistent_file(self):
        assert is_binary("/nonexistent/path/file.txt") is True


class TestParseDiffFilePath:
    def test_standard_diff(self):
        result = _parse_diff_file_path("diff --git a/src/main.py b/src/main.py")
        assert result == "src/main.py"

    def test_path_with_spaces(self):
        result = _parse_diff_file_path("diff --git a/my file.java b/my file.java")
        assert result == "my file.java"

    def test_nested_path(self):
        result = _parse_diff_file_path("diff --git a/src/com/example/Main.java b/src/com/example/Main.java")
        assert result == "src/com/example/Main.java"

    def test_invalid_line(self):
        result = _parse_diff_file_path("index 1234567..abcdef 100644")
        assert result is None


class TestScanSourceFiles:
    def test_scan_python_files(self, tmp_path):
        """Test scanning Python source files in a directory."""
        # Create test files
        (tmp_path / "main.py").write_text("def hello():\n    print('hello')\n" * 10)
        (tmp_path / "utils.py").write_text("def util():\n    pass\n" * 10)
        (tmp_path / "README.md").write_text("# README\n")

        changes = scan_source_files(str(tmp_path), max_files=10)
        assert len(changes) == 2
        langs = {c.language for c in changes}
        assert "python" in langs

    def test_scan_respects_max_files(self, tmp_path):
        """Test that max_files limit is respected."""
        for i in range(10):
            (tmp_path / f"file{i}.py").write_text("x = 1\n" * 10)

        changes = scan_source_files(str(tmp_path), max_files=3)
        assert len(changes) == 3

    def test_scan_skips_binary_files(self, tmp_path):
        """Test that binary files are skipped."""
        (tmp_path / "text.py").write_text("x = 1\n" * 10)
        (tmp_path / "binary.bin").write_bytes(b"\x00\x01\x02\x03" * 100)

        changes = scan_source_files(str(tmp_path), max_files=10)
        assert len(changes) == 1
        assert changes[0].file_path == "text.py"

    def test_scan_skips_hidden_dirs(self, tmp_path):
        """Test that hidden directories are skipped."""
        hidden_dir = tmp_path / ".hidden"
        hidden_dir.mkdir()
        (hidden_dir / "secret.py").write_text("x = 1\n" * 10)
        (tmp_path / "main.py").write_text("x = 1\n" * 10)

        changes = scan_source_files(str(tmp_path), max_files=10)
        assert len(changes) == 1

    def test_scan_skips_small_files(self, tmp_path):
        """Test that files with less than 50 chars are skipped."""
        (tmp_path / "tiny.py").write_text("x = 1\n")  # Only 6 chars
        (tmp_path / "big.py").write_text("x = 1\n" * 10)  # 40 chars, still small

        # Make it bigger
        (tmp_path / "big.py").write_text("# Comment line\n" * 6)

        changes = scan_source_files(str(tmp_path), max_files=10)
        assert len(changes) == 1
