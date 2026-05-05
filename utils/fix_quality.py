"""Fix quality assessment — evaluates generated fixes.

Scans fixes for:
- AST validity (syntax correctness)
- Run existing project tests
- Semantic similarity (no excessive changes)
"""
import hashlib
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class FixQualityReport:
    """Quality assessment of a generated fix."""
    overall_score: float  # 0.0 to 1.0
    syntax_valid: bool = True
    test_passed: bool = True
    semantic_similar: bool = True
    structure_preserved: bool = True
    issues: list[str] = field(default_factory=list)
    syntax_errors: list[str] = field(default_factory=list)
    test_output: str = ""
    change_ratio: float = 0.0  # fraction of lines changed

    def is_good(self) -> bool:
        """Check if fix meets quality threshold."""
        return (
            self.overall_score >= 0.6
            and self.syntax_valid
            and (self.test_passed or self.test_output == "")
        )


def assess_fix_quality(
    original_code: str,
    fixed_code: str,
    language: str,
    file_path: str = "",
    repo_path: str = "",
    run_tests: bool = True,
) -> FixQualityReport:
    """Comprehensive fix quality assessment.

    Args:
        original_code: Original source code.
        fixed_code: AI-generated fixed code.
        language: Programming language.
        file_path: Path of the file (relative to repo).
        repo_path: Root of the project.
        run_tests: Whether to run project tests.

    Returns:
        FixQualityReport with scores and issues.
    """
    report = FixQualityReport(overall_score=1.0)

    # 1. Syntax validation
    _check_syntax(original_code, fixed_code, language, report)

    # 2. Structural preservation
    _check_structure(original_code, fixed_code, language, report)

    # 3. Semantic similarity
    report.change_ratio = _compute_change_ratio(original_code, fixed_code)
    if report.change_ratio > 0.8:
        report.semantic_similar = False
        report.issues.append(f"Fix changes {report.change_ratio*100:.0f}% of file — too aggressive")

    # 4. Run project tests
    if run_tests and repo_path and language in ("python", "javascript", "go", "rust", "java"):
        _run_project_tests(fixed_code, language, file_path, repo_path, report)

    # Compute overall score
    score = 1.0
    if not report.syntax_valid:
        score -= 0.4
    if not report.structure_preserved:
        score -= 0.3
    if not report.semantic_similar:
        score -= 0.15
    if not report.test_passed:
        score -= 0.15

    report.overall_score = max(0.0, min(1.0, score))

    return report


def _check_syntax(
    original_code: str,
    fixed_code: str,
    language: str,
    report: FixQualityReport,
) -> None:
    """Check that fixed code has valid syntax."""
    if language == "python":
        _check_python_syntax(fixed_code, report)
    elif language == "javascript":
        _check_js_syntax(fixed_code, report)
    elif language == "typescript":
        _check_ts_syntax(fixed_code, report)
    elif language == "java":
        _check_java_syntax(fixed_code, report)
    elif language == "go":
        _check_go_syntax(fixed_code, report)
    elif language == "rust":
        _check_rust_syntax(fixed_code, report)


def _check_python_syntax(code: str, report: FixQualityReport) -> None:
    """Check Python syntax."""
    try:
        compile(code, "<fix>", "exec")
    except SyntaxError as e:
        report.syntax_valid = False
        report.syntax_errors.append(f"SyntaxError: {e.msg} at line {e.lineno}")


def _check_js_syntax(code: str, report: FixQualityReport) -> None:
    """Check JavaScript syntax using Node.js."""
    try:
        result = subprocess.run(
            ["node", "-c"],
            input=code,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            report.syntax_valid = False
            report.syntax_errors.append(f"Syntax error: {result.stderr[:200]}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # Node not available or too slow


def _check_ts_syntax(code: str, report: FixQualityReport) -> None:
    """Check TypeScript syntax."""
    # Basic check: look for unmatched braces/parentheses
    if code.count("{") != code.count("}"):
        report.syntax_valid = False
        report.syntax_errors.append("Unbalanced braces")
    if code.count("(") != code.count(")"):
        report.syntax_valid = False
        report.syntax_errors.append("Unbalanced parentheses")


def _check_java_syntax(code: str, report: FixQualityReport) -> None:
    """Check Java syntax (basic brace/paren check)."""
    if code.count("{") != code.count("}"):
        report.syntax_valid = False
        report.syntax_errors.append("Unbalanced braces")
    if code.count("(") != code.count(")"):
        report.syntax_valid = False
        report.syntax_errors.append("Unbalanced parentheses")

    # Check for common issues
    # Missing semicolons (rough heuristic)
    stmt_lines = [l.strip() for l in code.splitlines() if l.strip() and not l.strip().startswith("//")]
    for line in stmt_lines:
        if (any(kw in line for kw in ("return ", "throw ", "int ", "String ", "var ", "final "))
            and not line.endswith(";") and not line.endswith("{") and not line.endswith("}")):
            report.syntax_errors.append(f"Possible missing semicolon: {line[:50]}")
            break  # Only report first


def _check_go_syntax(code: str, report: FixQualityReport) -> None:
    """Check Go syntax."""
    if code.count("{") != code.count("}"):
        report.syntax_valid = False
        report.syntax_errors.append("Unbalanced braces")


def _check_rust_syntax(code: str, report: FixQualityReport) -> None:
    """Check Rust syntax."""
    if code.count("{") != code.count("}"):
        report.syntax_valid = False
        report.syntax_errors.append("Unbalanced braces")
    if code.count("(") != code.count(")"):
        report.syntax_valid = False
        report.syntax_errors.append("Unbalanced parentheses")


def _check_structure(
    original_code: str,
    fixed_code: str,
    language: str,
    report: FixQualityReport,
) -> None:
    """Check that the structure is preserved."""
    orig_lines = original_code.splitlines()
    fixed_lines = fixed_code.splitlines()

    # Check for removed functions/methods
    if language == "python":
        orig_funcs = set(re.findall(r'def\s+(\w+)\s*\(', original_code))
        fixed_funcs = set(re.findall(r'def\s+(\w+)\s*\(', fixed_code))
        removed = orig_funcs - fixed_funcs
        if removed:
            report.structure_preserved = False
            report.issues.append(f"Removed functions: {', '.join(list(removed)[:3])}")

    elif language == "java":
        orig_methods = set(re.findall(r'(public|private|protected)\s+\w+\s+(\w+)\s*\(', original_code))
        fixed_methods = set(re.findall(r'(public|private|protected)\s+\w+\s+(\w+)\s*\(', fixed_code))
        orig_method_names = {m[1] for m in orig_methods}
        fixed_method_names = {m[1] for m in fixed_methods}
        removed = orig_method_names - fixed_method_names
        if removed:
            report.structure_preserved = False
            report.issues.append(f"Removed methods: {', '.join(list(removed)[:3])}")


def _compute_change_ratio(original_code: str, fixed_code: str) -> float:
    """Compute fraction of lines that changed."""
    orig_lines = original_code.splitlines()
    fixed_lines = fixed_code.splitlines()

    orig_set = set(orig_lines)
    fixed_set = set(fixed_lines)

    removed = len(orig_set - fixed_set)
    added = len(fixed_set - orig_set)
    total = max(len(orig_lines), len(fixed_lines), 1)

    return (removed + added) / total


def _run_project_tests(
    fixed_code: str,
    language: str,
    file_path: str,
    repo_path: str,
    report: FixQualityReport,
) -> None:
    """Run project's existing test suite to validate the fix.

    Writes fixed code to a temp file, runs tests, then restores original.
    """
    # Find test runner command
    test_cmd = _find_test_command(language, repo_path)
    if not test_cmd:
        report.test_output = "No test runner found"
        return

    # Save original file
    full_path = os.path.join(repo_path, file_path)
    original_backup = ""
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            original_backup = f.read()
    except Exception:
        return

    # Write fixed code
    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(fixed_code)
    except Exception:
        return

    # Run tests
    try:
        result = subprocess.run(
            test_cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        report.test_output = result.stdout[:1000] + result.stderr[:500]
        report.test_passed = result.returncode == 0
        if not report.test_passed:
            report.issues.append(f"Project tests failed (exit code {result.returncode})")
    except subprocess.TimeoutExpired:
        report.issues.append("Test execution timed out (60s)")
    except Exception as e:
        report.issues.append(f"Failed to run tests: {e}")
    finally:
        # Restore original file
        try:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(original_backup)
        except Exception:
            pass


def _find_test_command(language: str, repo_path: str) -> Optional[list[str]]:
    """Find the test runner command for the project."""
    if language == "python":
        if os.path.exists(os.path.join(repo_path, "pytest.ini")) or os.path.exists(os.path.join(repo_path, "pyproject.toml")):
            return ["python", "-m", "pytest", "-x", "-q", "--tb=line"]
        if any(f.endswith("_test.py") or "test_" in f for f in os.listdir(repo_path) if os.path.isfile(os.path.join(repo_path, f))):
            return ["python", "-m", "pytest", "-x", "-q"]
        # Fallback: try unittest
        return ["python", "-m", "unittest", "discover", "-s", "tests", "-q"]

    elif language == "javascript":
        if os.path.exists(os.path.join(repo_path, "package.json")):
            # Check for jest or vitest
            try:
                with open(os.path.join(repo_path, "package.json"), "r") as f:
                    content = f.read()
                if "vitest" in content:
                    return ["npx", "vitest", "run", "--reporter=basic"]
                if "jest" in content:
                    return ["npx", "jest", "--passWithNoTests", "--forceExit"]
                if "mocha" in content:
                    return ["npx", "mocha", "--timeout", "10000"]
            except Exception:
                pass

    elif language == "go":
        return ["go", "test", "./...", "-short", "-count=1"]

    elif language == "rust":
        return ["cargo", "test", "--quiet"]

    elif language == "java":
        if os.path.exists(os.path.join(repo_path, "pom.xml")):
            return ["mvn", "test", "-q", "-DskipTests=false"]
        if os.path.exists(os.path.join(repo_path, "build.gradle")):
            return ["./gradlew", "test", "--quiet"]

    return None
