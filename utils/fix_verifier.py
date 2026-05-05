"""Fix correctness verification.

Analyzes diffs between original and fixed code to detect:
- New issues introduced by the fix
- Whether original issues are actually resolved
- Potential regressions (removed important code, broken imports, etc.)
"""
import difflib
import re
from typing import Optional

from core.models import FixIssue, FixAnalysis


class FixVerifier:
    """Analyzes code fixes for correctness and regressions."""

    DANGEROUS_PATTERNS = {
        "python": [
            (r'\beval\s*\(', 'eval() usage detected'),
            (r'\bexec\s*\(', 'exec() usage detected'),
            (r'os\.system\s*\(', 'os.system() usage detected'),
            (r'pickle\.loads?\s*\(', 'pickle deserialization detected'),
            (r'__import__\s*\(', 'dynamic import detected'),
            (r'subprocess\.call\s*\([^)]*shell\s*=\s*True', 'subprocess with shell=True'),
        ],
        "java": [
            (r'\.createStatement\s*\(', 'Raw Statement (not PreparedStatement)'),
            (r'\.createQuery\s*\(\s*["\']?SELECT.*\+', 'SQL injection via string concatenation'),
            (r'DriverManager\.getConnection\s*\([^)]*\+', 'Hardcoded connection string'),
            (r'\.execute\s*\([^)]*\+', 'Dynamic SQL execution'),
        ],
        "javascript": [
            (r'\beval\s*\(', 'eval() usage'),
            (r'innerHTML\s*=', 'innerHTML assignment'),
            (r'document\.write\s*\(', 'document.write() usage'),
            (r'new\s+Function\s*\(', 'Function constructor'),
            (r'eval\(\s*at\s', 'eval() in stack trace'),
        ],
        "typescript": [
            (r'\beval\s*\(', 'eval() usage'),
            (r'innerHTML\s*=', 'innerHTML assignment'),
            (r'document\.write\s*\(', 'document.write() usage'),
            (r'new\s+Function\s*\(', 'Function constructor'),
        ],
        "go": [
            (r'exec\.Command\s*\(\s*"sh"', 'Shell command execution'),
            (r'\.Exec\s*\(\s*fmt\.Sprintf', 'SQL injection via string formatting'),
            (r'interface\{\}\)', 'Empty interface (type safety loss)'),
            (r'go\s+func\s*\(\s*\)\s*{', 'Goroutine without context or wait group'),
            (r'defers?\s+.*\.Close\s*\(', 'Deferred Close in loop'),
        ],
        "rust": [
            (r'\.unwrap\s*\(\)', 'Unsafe unwrap()'),
            (r'\.expect\s*\([^)]*\)\s*//\s*TODO', 'Temporary expect()'),
            (r'unsafe\s*{', 'Unsafe block'),
            (r'CString::from_vec_unchecked', 'Unsafe CString conversion'),
            (r' transmute\b', 'Type transmutation'),
        ],
        "php": [
            (r'\beval\s*\(', 'eval() usage'),
            (r'\bexec\s*\(', 'exec() usage'),
            (r'\bsystem\s*\(', 'system() usage'),
            (r'->query\s*\(\s*\$', 'SQL injection via variable concatenation'),
            (r'unserialize\s*\(', 'Unsafe deserialization'),
            (r'file_get_contents\s*\(\s*["\']?php://', 'PHP stream wrapper usage'),
        ],
        "ruby": [
            (r'\beval\s+\(', 'eval() usage'),
            (r'\bsystem\s*\(', 'system() call'),
            (r'`[^`]*#\{[^}]+\}[^`]*`', 'Command injection via string interpolation'),
            (r'YAML\.load\s*\(', 'Unsafe YAML deserialization'),
            (r'render\s+.*:\s*html', 'XSS via raw HTML rendering'),
        ],
        "kotlin": [
            (r'\.createStatement\s*\(', 'Raw Statement'),
            (r'WebView.*javascriptInterface', 'WebView JavaScript interface'),
            (r'ProcessBuilder\s*\(', 'Process execution'),
        ],
        "csharp": [
            (r'SqlCommand\s*\(\s*["\']?SELECT.*\+', 'SQL injection'),
            (r'ViewState\["', 'ViewState manipulation'),
            (r'HttpUtility\.HtmlDecode', 'HTML injection risk'),
            (r'\.CreateScript', 'Dynamic script execution'),
        ],
    }

    # Pre-compiled patterns for performance
    _COMPILED_PATTERNS = {
        lang: [(re.compile(p, re.IGNORECASE), d) for p, d in patterns]
        for lang, patterns in DANGEROUS_PATTERNS.items()
    }

    def verify_fix(
        self,
        original_code: str,
        fixed_code: str,
        language: str,
        original_issues: list[dict] = None,
    ) -> FixAnalysis:
        """Analyze a fix for correctness and regressions."""
        analysis = FixAnalysis(is_valid=True)

        if not original_code or not fixed_code:
            analysis.is_valid = False
            analysis.issues.append(FixIssue(
                severity="high",
                category="incomplete_fix",
                description="Fix code is empty",
            ))
            return analysis

        # Compute diff stats
        diff = list(difflib.unified_diff(
            original_code.splitlines(keepends=True),
            fixed_code.splitlines(keepends=True),
            n=0,
        ))
        analysis.lines_removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
        analysis.lines_added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))

        # Check for excessive removal (potential regression)
        original_lines = len(original_code.splitlines())
        if original_lines > 0 and analysis.lines_removed > original_lines * 0.5:
            analysis.regression_risk = "high"
            analysis.issues.append(FixIssue(
                severity="high",
                category="regression",
                description=f"Removed {analysis.lines_removed}/{original_lines} lines ({analysis.lines_removed/original_lines*100:.0f}% of file)",
            ))

        # Check for dangerous patterns in fixed code
        lang = language.lower()
        compiled_patterns = self._COMPILED_PATTERNS.get(lang, [])
        for compiled_pattern, description in compiled_patterns:
            matches = compiled_pattern.findall(fixed_code)
            if matches:
                analysis.issues.append(FixIssue(
                    severity="critical",
                    category="new_issue",
                    description=f"Fix introduced: {description} ({len(matches)} occurrence(s))",
                ))
                analysis.is_valid = False

        # Check for removed imports (potential regression)
        if lang in ("python", "java", "javascript", "typescript", "go", "rust", "php"):
            orig_imports = self._extract_imports(original_code, lang)
            fixed_imports = self._extract_imports(fixed_code, lang)
            removed_imports = orig_imports - fixed_imports
            if removed_imports:
                import_list = ", ".join(list(removed_imports)[:5])
                analysis.issues.append(FixIssue(
                    severity="medium",
                    category="regression",
                    description=f"Removed imports: {import_list}",
                ))

        # Check for broken structure
        if lang == "java":
            self._check_java_structure(original_code, fixed_code, analysis)
        elif lang == "python":
            self._check_python_structure(original_code, fixed_code, analysis)
        elif lang == "go":
            self._check_go_structure(original_code, fixed_code, analysis)
        elif lang == "rust":
            self._check_rust_structure(original_code, fixed_code, analysis)

        # Determine regression risk
        critical_count = sum(1 for i in analysis.issues if i.severity == "critical")
        high_count = sum(1 for i in analysis.issues if i.severity == "high")
        if critical_count > 0 or high_count > 2:
            analysis.regression_risk = "high"
        elif high_count > 0 or len(analysis.issues) > 3:
            analysis.regression_risk = "medium"
        else:
            analysis.regression_risk = "low"

        return analysis

    def _extract_imports(self, code: str, language: str) -> set[str]:
        """Extract import statements."""
        imports = set()
        if language == "python":
            for line in code.splitlines():
                line = line.strip()
                if line.startswith("import ") or line.startswith("from "):
                    imports.add(line.split()[1] if len(line.split()) > 1 else line)
        elif language == "java":
            for line in code.splitlines():
                line = line.strip()
                if line.startswith("import "):
                    imports.add(line.replace("import ", "").replace(";", "").strip())
        elif language in ("javascript", "typescript"):
            for line in code.splitlines():
                line = line.strip()
                if line.startswith("import ") or (line.startswith("const ") and "= require(" in line):
                    imports.add(line[:60])
        elif language == "go":
            in_import = False
            for line in code.splitlines():
                line = line.strip()
                if line.startswith("import "):
                    if "(" in line:
                        in_import = True
                    else:
                        imports.add(line.replace("import ", "").strip('"'))
                elif in_import:
                    if line == ")":
                        in_import = False
                    else:
                        imports.add(line.strip('"').strip())
        elif language == "rust":
            for line in code.splitlines():
                line = line.strip()
                if line.startswith("use "):
                    imports.add(line.replace("use ", "").replace(";", "").strip())
        elif language == "php":
            for line in code.splitlines():
                line = line.strip()
                if line.startswith("require ") or line.startswith("include ") or line.startswith("use "):
                    imports.add(line[:60])
        return imports

    def _check_java_structure(self, original: str, fixed: str, analysis: FixAnalysis) -> None:
        """Check for structural issues in Java code."""
        # Count braces
        orig_open = original.count("{")
        orig_close = original.count("}")
        fixed_open = fixed.count("{")
        fixed_close = fixed.count("}")

        if fixed_open != fixed_close:
            analysis.issues.append(FixIssue(
                severity="high",
                category="regression",
                description=f"Unbalanced braces in fixed code: {fixed_open} open, {fixed_close} close",
            ))
            analysis.is_valid = False

        # Check for removed class/method declarations
        orig_methods = set(re.findall(r'(public|private|protected)\s+\w+\s+(\w+)\s*\(', original))
        fixed_methods = set(re.findall(r'(public|private|protected)\s+\w+\s+(\w+)\s*\(', fixed))
        removed_methods = orig_methods - fixed_methods
        if removed_methods:
            method_names = [m[1] for m in list(removed_methods)[:3]]
            analysis.issues.append(FixIssue(
                severity="high",
                category="regression",
                description=f"Removed methods: {', '.join(method_names)}",
            ))

    def _check_python_structure(self, original: str, fixed: str, analysis: FixAnalysis) -> None:
        """Check for structural issues in Python code."""
        # Check for removed function definitions
        orig_funcs = set(re.findall(r'def\s+(\w+)\s*\(', original))
        fixed_funcs = set(re.findall(r'def\s+(\w+)\s*\(', fixed))
        removed_funcs = orig_funcs - fixed_funcs
        if removed_funcs:
            analysis.issues.append(FixIssue(
                severity="high",
                category="regression",
                description=f"Removed functions: {', '.join(removed_funcs)}",
            ))

    def _check_go_structure(self, original: str, fixed: str, analysis: FixAnalysis) -> None:
        """Check for structural issues in Go code."""
        # Check for removed function declarations
        orig_funcs = set(re.findall(r'func\s+\(.*?\)\s+(\w+)', original))
        fixed_funcs = set(re.findall(r'func\s+\(.*?\)\s+(\w+)', fixed))
        # Also check package-level functions
        orig_funcs.update(re.findall(r'func\s+(\w+)\s*\(', original))
        fixed_funcs.update(re.findall(r'func\s+(\w+)\s*\(', fixed))
        removed_funcs = orig_funcs - fixed_funcs
        if removed_funcs:
            analysis.issues.append(FixIssue(
                severity="high",
                category="regression",
                description=f"Removed functions: {', '.join(list(removed_funcs)[:3])}",
            ))
        # Check unbalanced braces
        if fixed.count('{') != fixed.count('}'):
            analysis.issues.append(FixIssue(
                severity="high",
                category="regression",
                description=f"Unbalanced braces: {fixed.count('{')} open, {fixed.count('}')} close",
            ))
            analysis.is_valid = False

    def _check_rust_structure(self, original: str, fixed: str, analysis: FixAnalysis) -> None:
        """Check for structural issues in Rust code."""
        # Check for removed function definitions
        orig_funcs = set(re.findall(r'fn\s+(\w+)\s*[<\(]', original))
        fixed_funcs = set(re.findall(r'fn\s+(\w+)\s*[<\(]', fixed))
        removed_funcs = orig_funcs - fixed_funcs
        if removed_funcs:
            analysis.issues.append(FixIssue(
                severity="high",
                category="regression",
                description=f"Removed functions: {', '.join(list(removed_funcs)[:3])}",
            ))
        # Check unbalanced braces
        if fixed.count('{') != fixed.count('}'):
            analysis.issues.append(FixIssue(
                severity="high",
                category="regression",
                description=f"Unbalanced braces: {fixed.count('{')} open, {fixed.count('}')} close",
            ))
            analysis.is_valid = False
