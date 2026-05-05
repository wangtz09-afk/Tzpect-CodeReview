"""Tests for utils.fix_verifier module."""
import pytest
from utils.fix_verifier import FixVerifier


class TestFixVerifier:
    def setup_method(self):
        self.verifier = FixVerifier()

    def test_empty_fix(self):
        analysis = self.verifier.verify_fix(
            original_code="def foo(): pass",
            fixed_code="",
            language="python",
        )
        assert analysis.is_valid is False
        assert len(analysis.issues) > 0

    def test_no_fix(self):
        analysis = self.verifier.verify_fix(
            original_code="",
            fixed_code="def foo(): pass",
            language="python",
        )
        assert analysis.is_valid is False

    def test_unchanged_code(self):
        code = "def foo():\n    print('hello')\n"
        analysis = self.verifier.verify_fix(
            original_code=code,
            fixed_code=code,
            language="python",
        )
        assert analysis.is_valid is True
        assert analysis.lines_added == 0
        assert analysis.lines_removed == 0

    def test_python_eval_detection(self):
        analysis = self.verifier.verify_fix(
            original_code="result = int(x)",
            fixed_code="result = eval(x)",
            language="python",
        )
        assert analysis.is_valid is False
        assert any("eval()" in i.description for i in analysis.issues)

    def test_python_exec_detection(self):
        analysis = self.verifier.verify_fix(
            original_code="pass",
            fixed_code="exec(user_input)",
            language="python",
        )
        assert analysis.is_valid is False
        assert any("exec()" in i.description for i in analysis.issues)

    def test_python_os_system_detection(self):
        analysis = self.verifier.verify_fix(
            original_code="pass",
            fixed_code="os.system(user_cmd)",
            language="python",
        )
        assert analysis.is_valid is False
        assert any("os.system()" in i.description for i in analysis.issues)

    def test_java_statement_detection(self):
        analysis = self.verifier.verify_fix(
            original_code="ps = conn.prepareStatement(sql)",
            fixed_code="stmt = conn.createStatement()",
            language="java",
        )
        assert analysis.is_valid is False
        assert any("Statement" in i.description for i in analysis.issues)

    def test_js_innerhtml_detection(self):
        analysis = self.verifier.verify_fix(
            original_code="element.textContent = data",
            fixed_code="element.innerHTML = userInput",
            language="javascript",
        )
        assert analysis.is_valid is False
        assert any("innerHTML" in i.description for i in analysis.issues)

    def test_js_eval_detection(self):
        analysis = self.verifier.verify_fix(
            original_code="const val = JSON.parse(data)",
            fixed_code="const val = eval(data)",
            language="javascript",
        )
        assert analysis.is_valid is False

    def test_java_unbalanced_braces(self):
        analysis = self.verifier.verify_fix(
            original_code="public class Test {\n    public void foo() {}\n}",
            fixed_code="public class Test {\n    public void foo() {\n}",
            language="java",
        )
        assert analysis.is_valid is False
        assert any("braces" in i.description for i in analysis.issues)

    def test_java_removed_method(self):
        analysis = self.verifier.verify_fix(
            original_code="public String getName() { return name; }\npublic void setName(String n) { name = n; }",
            fixed_code="public String getName() { return name; }",
            language="java",
        )
        assert any("method" in i.description.lower() for i in analysis.issues)

    def test_python_removed_function(self):
        analysis = self.verifier.verify_fix(
            original_code="def foo():\n    pass\n\ndef bar():\n    pass",
            fixed_code="def foo():\n    pass",
            language="python",
        )
        assert any("function" in i.description.lower() for i in analysis.issues)

    def test_removed_imports(self):
        analysis = self.verifier.verify_fix(
            original_code="import os\nimport sys\nimport json",
            fixed_code="import os\nimport json",
            language="python",
        )
        assert any("import" in i.description.lower() for i in analysis.issues)

    def test_excessive_removal(self):
        original = "\n".join([f"line {i}" for i in range(100)])
        fixed = "new code"
        analysis = self.verifier.verify_fix(
            original_code=original,
            fixed_code=fixed,
            language="python",
        )
        # Excessive removal should be at least medium risk
        assert analysis.regression_risk in ("high", "medium")

    def test_regression_risk_levels(self):
        # Low risk - small fix, no issues
        analysis = self.verifier.verify_fix(
            original_code="x = 1",
            fixed_code="x = 2",
            language="python",
        )
        # Small change should not be high risk
        assert analysis.regression_risk != "high"

    def test_diff_stats(self):
        analysis = self.verifier.verify_fix(
            original_code="line1\nline2\nline3",
            fixed_code="line1\nnew_line\nline3\nline4",
            language="python",
        )
        assert analysis.lines_removed >= 1
        assert analysis.lines_added >= 1
