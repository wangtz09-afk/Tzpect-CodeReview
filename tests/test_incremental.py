"""Tests for utils.incremental module."""
import pytest
from utils.incremental import (
    parse_diff_hunks,
    extract_changed_lines,
    get_changed_line_numbers,
    get_diff_stats,
    is_incremental_beneficial,
)


class TestParseDiffHunks:
    def test_simple_hunk(self):
        diff = """@@ -1,3 +1,4 @@
 def foo():
-    pass
+    x = 1
+    return x
 """
        hunks = parse_diff_hunks(diff)
        assert len(hunks) == 1
        # First changed line should be the removed line
        assert any("-" in line[1] for line in hunks[0].changed_lines)
        # Should have both + and - lines
        assert any("+" in line[1] for line in hunks[0].changed_lines)

    def test_multiple_hunks(self):
        diff = """@@ -1,2 +1,3 @@
 line1
+new1
 line2
@@ -10,2 +11,2 @@
 old
+new
 """
        hunks = parse_diff_hunks(diff)
        assert len(hunks) == 2

    def test_empty_diff(self):
        hunks = parse_diff_hunks("")
        assert len(hunks) == 0

    def test_no_hunks(self):
        hunks = parse_diff_hunks("just some text")
        assert len(hunks) == 0


class TestExtractChangedLines:
    def test_no_diff_returns_full(self):
        content = "line1\nline2\nline3"
        result = extract_changed_lines(content, "")
        assert result == content

    def test_empty_diff_returns_full(self):
        content = "line1\nline2\nline3"
        result = extract_changed_lines(content, "no diff header")
        assert result == content

    def test_extract_with_context(self):
        content = "\n".join([f"line {i}" for i in range(1, 21)])
        diff = """@@ -10,3 +10,4 @@
 line10
+new line
 line11
 line12"""
        result = extract_changed_lines(content, diff, context_lines=2)
        # Should contain lines around the change with context
        assert "unchanged lines omitted" in result or "line 10" in result


class TestGetChangedLineNumbers:
    def test_simple_diff(self):
        diff = """@@ -1,3 +1,4 @@
 def foo():
-    pass
+    x = 1
+    return x
     pass
 """
        changed = get_changed_line_numbers(diff)
        assert 2 in changed  # Line 2 was changed (pass -> x = 1)
        assert 3 in changed  # Line 3 was added

    def test_no_changes(self):
        changed = get_changed_line_numbers("")
        assert changed == set()


class TestGetDiffStats:
    def test_simple_stats(self):
        diff = """diff --git a/foo.py b/foo.py
@@ -1,3 +1,4 @@
-old
+new
+extra
 """
        stats = get_diff_stats(diff)
        assert stats["added"] == 2
        assert stats["removed"] == 1
        assert stats["files"] == 1

    def test_empty_stats(self):
        stats = get_diff_stats("")
        assert stats == {"added": 0, "removed": 0, "modified": 0, "hunks": 0, "files": 0}


class TestIsIncrementalBeneficial:
    def test_small_file_not_beneficial(self):
        content = "\n".join(["x"] * 10)
        assert is_incremental_beneficial("diff", content, threshold=50) is False

    def test_large_file_small_diff_is_beneficial(self):
        content = "\n".join([f"line {i}" for i in range(200)])
        diff = """@@ -10,1 +10,2 @@
 old
+new"""
        assert is_incremental_beneficial(diff, content, threshold=50) is True

    def test_large_file_large_diff_not_beneficial(self):
        content = "\n".join([f"line {i}" for i in range(100)])
        diff = "\n".join([
            "@@ -1,1 +1,2 @@",
            "old",
        ] + [f"+new {i}" for i in range(50)])
        assert is_incremental_beneficial(diff, content, threshold=50) is False
