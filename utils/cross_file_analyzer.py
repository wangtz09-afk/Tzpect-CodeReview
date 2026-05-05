"""Cross-file analysis — builds project knowledge graph.

Analyzes relationships between files to detect cross-file issues:
- Interface/implementation mismatches
- Duplicate code
- Missing implementations
- Inconsistent patterns

NOTE: Symbol extraction uses regex-based heuristics. For production-grade
accuracy, consider migrating to tree-sitter (https://tree-sitter.github.io/).
"""
import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from utils.common import get_language


@dataclass
class FileInfo:
    """Extracted information from a source file."""
    path: str
    language: str
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    extends: dict[str, str] = field(default_factory=dict)  # class -> parent
    implements: dict[str, list[str]] = field(default_factory=dict)  # class -> interfaces
    dependencies: list[str] = field(default_factory=list)  # files this file depends on
    line_count: int = 0
    content_hash: str = ""


@dataclass
class CrossFileIssue:
    """An issue detected across files."""
    severity: str  # critical, high, medium, low
    category: str  # interface_mismatch, duplicate, missing_impl, inconsistency
    files: list[str]
    description: str
    suggestion: str = ""


@dataclass
class ProjectGraph:
    """Complete project knowledge graph."""
    files: dict[str, FileInfo] = field(default_factory=dict)
    issues: list[CrossFileIssue] = field(default_factory=list)
    classes: dict[str, str] = field(default_factory=dict)  # class_name -> file_path
    functions: dict[str, str] = field(default_factory=dict)  # function_name -> file_path
    interfaces: dict[str, str] = field(default_factory=dict)  # interface_name -> file_path

    def to_context_prompt(self, target_file: str) -> str:
        """Generate context prompt for reviewing a specific file.

        Args:
            target_file: The file being reviewed.

        Returns:
            Prompt section with relevant cross-file context.
        """
        if target_file not in self.files:
            return ""

        target = self.files[target_file]
        lines = []

        # Related classes
        related_classes = []
        for imp in target.imports:
            if imp in self.classes:
                related_classes.append(f"{imp} → {self.classes[imp]}")
        if related_classes:
            lines.append("### Related Classes in this Project")
            lines.append(f"File `{target.path}` depends on:")
            for cls in related_classes[:10]:
                lines.append(f"- {cls}")
            lines.append("")

        # Implemented interfaces
        if target.interfaces:
            lines.append("### Interfaces")
            for iface in target.interfaces:
                lines.append(f"- `{iface}` defined in `{target.path}`")
            lines.append("")

        # Parent classes
        for cls, parent in target.extends.items():
            if parent in self.classes:
                lines.append(f"### Inheritance: `{cls}` extends `{parent}`")
                lines.append(f"- Parent class is in `{self.classes[parent]}`")
                lines.append("- Review `"+target.path+"` for proper override patterns")
                lines.append("")

        return "\n".join(lines) if lines else ""


def analyze_project(repo_path: str, files: list[str]) -> ProjectGraph:
    """Build a project knowledge graph from source files.

    Args:
        repo_path: Root path of the project.
        files: List of file paths to analyze (relative to repo_path).

    Returns:
        ProjectGraph with all extracted information.
    """
    graph = ProjectGraph()

    for file_path in files:
        full_path = os.path.join(repo_path, file_path)
        if not os.path.isfile(full_path):
            continue

        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue

        language = get_language(file_path)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        file_info = FileInfo(
            path=file_path,
            language=language,
            line_count=len(content.splitlines()),
            content_hash=content_hash,
        )

        # Extract symbols based on language
        if language in ("java", "kotlin", "csharp"):
            _extract_java_like(content, file_info)
        elif language in ("python",):
            _extract_python(content, file_info)
        elif language in ("javascript", "typescript"):
            _extract_js_ts(content, file_info)
        elif language in ("go",):
            _extract_go(content, file_info)
        elif language in ("rust",):
            _extract_rust(content, file_info)
        elif language in ("php",):
            _extract_php(content, file_info)
        elif language in ("ruby",):
            _extract_ruby(content, file_info)

        # Deduplicate extracted symbols (regex may match same symbol multiple times)
        file_info.classes = list(dict.fromkeys(file_info.classes))
        file_info.functions = list(dict.fromkeys(file_info.functions))
        file_info.interfaces = list(dict.fromkeys(file_info.interfaces))
        file_info.imports = list(dict.fromkeys(file_info.imports))

        graph.files[file_path] = file_info

        # Register symbols in global index (deduplicate)
        for cls in file_info.classes:
            if cls not in graph.classes:
                graph.classes[cls] = file_path
        for func in file_info.functions:
            if func not in graph.functions:
                graph.functions[func] = file_path
        for iface in file_info.interfaces:
            if iface not in graph.interfaces:
                graph.interfaces[iface] = file_path

    # Run cross-file analysis
    graph.issues = _find_cross_file_issues(graph)

    return graph


def _extract_java_like(content: str, info: FileInfo) -> None:
    """Extract symbols from Java/Kotlin/C# code."""
    # Classes
    for match in re.finditer(r'(?:public|private|protected)?\s*(?:abstract\s+)?(?:class|enum|record)\s+(\w+)', content):
        info.classes.append(match.group(1))

    # Interfaces
    for match in re.finditer(r'(?:public\s+)?interface\s+(\w+)', content):
        info.interfaces.append(match.group(1))

    # Methods
    for match in re.finditer(r'(?:public|private|protected)\s+[\w<>\[\]]+\s+(\w+)\s*\(', content):
        info.functions.append(match.group(1))

    # Imports
    for match in re.finditer(r'import\s+([\w.]+(?:\.\*)?);', content):
        info.imports.append(match.group(1))

    # extends
    for match in re.finditer(r'class\s+(\w+)\s+extends\s+(\w+)', content):
        info.extends[match.group(1)] = match.group(2)

    # implements
    for match in re.finditer(r'(?:class|interface)\s+(\w+)\s+implements\s+([\w,\s]+)', content):
        cls = match.group(1)
        ifaces = [i.strip() for i in match.group(2).split(",")]
        info.implements[cls] = ifaces


def _extract_python(content: str, info: FileInfo) -> None:
    """Extract symbols from Python code."""
    # Classes
    for match in re.finditer(r'^\s*class\s+(\w+)', content, re.MULTILINE):
        info.classes.append(match.group(1))

    # Functions
    for match in re.finditer(r'^\s*def\s+(\w+)\s*\(', content, re.MULTILINE):
        info.functions.append(match.group(1))

    # Async functions
    for match in re.finditer(r'^\s*async\s+def\s+(\w+)\s*\(', content, re.MULTILINE):
        info.functions.append(match.group(1))

    # Imports
    for match in re.finditer(r'^(?:from\s+([\w.]+)\s+)?import\s+([\w,.\s*]+)', content, re.MULTILINE):
        module = match.group(1) or match.group(2)
        info.imports.append(module.strip())


def _extract_js_ts(content: str, info: FileInfo) -> None:
    """Extract symbols from JavaScript/TypeScript code."""
    # Classes
    for match in re.finditer(r'(?:export\s+)?(?:abstract\s+)?class\s+(\w+)', content):
        info.classes.append(match.group(1))

    # Interfaces (TypeScript)
    for match in re.finditer(r'(?:export\s+)?interface\s+(\w+)', content):
        info.interfaces.append(match.group(1))

    # Functions
    for match in re.finditer(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)', content):
        info.functions.append(match.group(1))

    # Arrow functions assigned to variables
    for match in re.finditer(r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(', content):
        info.functions.append(match.group(1))

    # Exports
    for match in re.finditer(r'export\s+(?:default\s+)?(?:class|function|const|let|var)\s+(\w+)', content):
        info.exports.append(match.group(1))

    # Imports
    for match in re.finditer(r'import\s+.*?from\s+["\']([^"\']+)["\']', content):
        info.imports.append(match.group(1))


def _extract_go(content: str, info: FileInfo) -> None:
    """Extract symbols from Go code."""
    # Structs (classes)
    for match in re.finditer(r'type\s+(\w+)\s+struct', content):
        info.classes.append(match.group(1))

    # Interfaces
    for match in re.finditer(r'type\s+(\w+)\s+interface', content):
        info.interfaces.append(match.group(1))

    # Functions
    for match in re.finditer(r'func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(', content):
        info.functions.append(match.group(1))

    # Imports
    for match in re.finditer(r'import\s+"([^"]+)"', content):
        info.imports.append(match.group(1))


def _extract_rust(content: str, info: FileInfo) -> None:
    """Extract symbols from Rust code."""
    # Structs
    for match in re.finditer(r'(?:pub\s+)?struct\s+(\w+)', content):
        info.classes.append(match.group(1))

    # Traits (interfaces)
    for match in re.finditer(r'(?:pub\s+)?trait\s+(\w+)', content):
        info.interfaces.append(match.group(1))

    # Functions
    for match in re.finditer(r'(?:pub\s+)?fn\s+(\w+)\s*[<\(]', content):
        info.functions.append(match.group(1))

    # Use statements
    for match in re.finditer(r'use\s+([^;]+);', content):
        info.imports.append(match.group(1).strip())


def _extract_php(content: str, info: FileInfo) -> None:
    """Extract symbols from PHP code."""
    # Classes
    for match in re.finditer(r'(?:abstract\s+)?class\s+(\w+)', content):
        info.classes.append(match.group(1))

    # Interfaces
    for match in re.finditer(r'interface\s+(\w+)', content):
        info.interfaces.append(match.group(1))

    # Functions
    for match in re.finditer(r'(?:public\s+)?function\s+(\w+)\s*\(', content):
        info.functions.append(match.group(1))

    # Use statements
    for match in re.finditer(r'use\s+([\w\\]+);', content):
        info.imports.append(match.group(1))


def _extract_ruby(content: str, info: FileInfo) -> None:
    """Extract symbols from Ruby code."""
    # Classes
    for match in re.finditer(r'^\s*class\s+(\w+)', content, re.MULTILINE):
        info.classes.append(match.group(1))

    # Modules
    for match in re.finditer(r'^\s*module\s+(\w+)', content, re.MULTILINE):
        info.classes.append(match.group(1))

    # Methods
    for match in re.finditer(r'^\s*def\s+(?:self\.)?(\w+[?!]?)', content, re.MULTILINE):
        info.functions.append(match.group(1))

    # Requires
    for match in re.finditer(r'require\s+["\']([^"\']+)["\']', content):
        info.imports.append(match.group(1))


# ── Cross-File Issue Detection ────────────────────────────────────────────

def _find_cross_file_issues(graph: ProjectGraph) -> list[CrossFileIssue]:
    """Find issues that span multiple files."""
    issues = []

    issues.extend(_find_interface_mismatches(graph))
    issues.extend(_find_missing_implementations(graph))
    issues.extend(_find_inconsistent_patterns(graph))

    return issues


def _find_interface_mismatches(graph: ProjectGraph) -> list[CrossFileIssue]:
    """Find interface implementations that don't match the interface."""
    issues = []

    for file_path, file_info in graph.files.items():
        for cls, ifaces in file_info.implements.items():
            for iface_name in ifaces:
                if iface_name in graph.interfaces:
                    iface_file = graph.interfaces[iface_name]
                    issues.append(CrossFileIssue(
                        severity="medium",
                        category="interface_mismatch",
                        files=[iface_file, file_path],
                        description=f"`{cls}` implements `{iface_name}` — review for correct method signatures",
                        suggestion="Check that all interface methods are implemented with matching signatures",
                    ))

    return issues


def _find_missing_implementations(graph: ProjectGraph) -> list[CrossFileIssue]:
    """Find abstract classes or interfaces with no implementations."""
    issues = []

    for iface_name, iface_file in graph.interfaces.items():
        has_impl = False
        for file_info in graph.files.values():
            for cls, ifaces in file_info.implements.items():
                if iface_name in ifaces:
                    has_impl = True
                    break
            if has_impl:
                break

        if not has_impl:
            issues.append(CrossFileIssue(
                severity="low",
                category="missing_impl",
                files=[iface_file],
                description=f"Interface `{iface_name}` has no implementations",
                suggestion="Remove unused interface or add implementation",
            ))

    return issues


def _find_inconsistent_patterns(graph: ProjectGraph) -> list[CrossFileIssue]:
    """Find inconsistent naming/error-handling patterns."""
    issues = []

    # Check for inconsistent naming in similar files
    controller_files = [f for f in graph.files if "controller" in f.lower() or "handler" in f.lower()]
    service_files = [f for f in graph.files if "service" in f.lower() or "logic" in f.lower()]

    if controller_files and service_files:
        # Check if controllers import their services
        for cf in controller_files:
            file_info = graph.files[cf]
            if not file_info.imports:
                issues.append(CrossFileIssue(
                    severity="low",
                    category="inconsistency",
                    files=[cf],
                    description=f"Controller `{cf}` has no imports — might not be using service layer",
                    suggestion="Inject service dependencies via constructor or @Autowired",
                ))

    return issues
