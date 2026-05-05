"""Project context awareness — detects frameworks, structure, and constraints.

Provides LLM with project-level context to improve review accuracy.
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from utils.common import get_language as _get_language, should_skip_dir


@dataclass
class FrameworkInfo:
    """Detected framework information."""
    name: str
    version: str = ""
    config_files: list[str] = field(default_factory=list)
    characteristics: list[str] = field(default_factory=list)


@dataclass
class ProjectContext:
    """Complete project context for review."""
    frameworks: list[FrameworkInfo] = field(default_factory=list)
    language: str = ""
    directory_structure: str = ""
    key_files: dict[str, str] = field(default_factory=dict)
    common_patterns: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    total_files: int = 0
    total_lines: int = 0

    def to_prompt(self) -> str:
        """Convert context to a prompt section for LLM."""
        if not self.frameworks and not self.common_patterns:
            return ""

        lines = ["## Project Context (for review accuracy)"]

        # Frameworks
        if self.frameworks:
            fw_names = [f"{fw.name}" + (f" {fw.version}" if fw.version else "") for fw in self.frameworks]
            lines.append(f"\n### Detected Frameworks")
            lines.append(f"The project uses: {', '.join(fw_names)}")
            for fw in self.frameworks:
                for char in fw.characteristics:
                    lines.append(f"- {char}")

        # Common patterns
        if self.common_patterns:
            lines.append(f"\n### Common Patterns in this Project")
            for pattern in self.common_patterns:
                lines.append(f"- {pattern}")

        # Constraints
        if self.constraints:
            lines.append(f"\n### Project Constraints")
            for constraint in self.constraints:
                lines.append(f"- {constraint}")

        # Key files
        if self.key_files:
            lines.append(f"\n### Key Files")
            for name, path in self.key_files.items():
                lines.append(f"- {name}: `{path}`")

        lines.append(f"\n**IMPORTANT**: Use this context to improve review accuracy.")
        lines.append(f"- Don't report issues that are framework conventions")
        lines.append(f"- Be stricter about security patterns specific to these frameworks")
        lines.append(f"- Consider project constraints when suggesting fixes")
        lines.append("")

        return "\n".join(lines)


def detect_project_context(repo_path: str, file_path: str = "") -> ProjectContext:
    """Detect project framework, structure, and patterns.

    Args:
        repo_path: Root path of the project.
        file_path: Specific file being reviewed (for targeted context).

    Returns:
        ProjectContext with all detected information.
    """
    context = ProjectContext()

    # Detect all frameworks present in the project
    context.frameworks = detect_frameworks(repo_path)

    # Determine primary language
    if file_path:
        context.language = _get_language(file_path)
    else:
        context.language = detect_primary_language(repo_path)

    # Build directory structure (top 2 levels only)
    context.directory_structure = _build_directory_structure(repo_path, max_depth=2)

    # Find key files (config, entry points)
    context.key_files = _find_key_files(repo_path)

    # Detect common patterns
    context.common_patterns = detect_common_patterns(repo_path, context.frameworks)

    # Generate constraints from frameworks
    context.constraints = generate_constraints(context.frameworks, context.language)

    # Count project stats
    context.total_files, context.total_lines = _count_project_stats(repo_path)

    return context


# ── Framework Detection ───────────────────────────────────────────────────

_FRAMEWORK_RULES = {
    "Spring Boot": {
        "indicators": ["pom.xml", "build.gradle", "src/main/java", "application.properties", "application.yml"],
        "config_files": ["pom.xml", "build.gradle", "application.properties"],
        "characteristics": [
            "Spring MVC pattern (Controller → Service → Repository)",
            "Dependency injection via @Autowired or constructor",
            "RESTful APIs with @RestController",
            "Database access via Spring Data JPA",
            "Configuration via @ConfigurationProperties",
        ],
    },
    "Django": {
        "indicators": ["manage.py", "settings.py", "urls.py", "requirements.txt"],
        "config_files": ["settings.py", "urls.py"],
        "characteristics": [
            "MVT pattern (Model → View → Template)",
            "ORM-based database access",
            "URL routing via urls.py",
            "Template-based rendering",
            "Middleware pattern",
        ],
    },
    "Flask": {
        "indicators": ["app.py", "wsgi.py", "requirements.txt"],
        "config_files": ["app.py"],
        "characteristics": [
            "Lightweight framework, manual routing",
            "Blueprint pattern for modular apps",
            "No built-in ORM (use SQLAlchemy)",
        ],
    },
    "FastAPI": {
        "indicators": ["main.py", "requirements.txt"],
        "config_files": ["main.py"],
        "characteristics": [
            "Type-hint based API definition",
            "Automatic OpenAPI/Swagger docs",
            "Pydantic models for validation",
            "Async support",
        ],
    },
    "React": {
        "indicators": ["package.json", "src/App.tsx", "src/App.jsx", "public/index.html"],
        "config_files": ["package.json", "tsconfig.json"],
        "characteristics": [
            "Component-based architecture",
            "State management (useState, useReducer, or external)",
            "Hooks pattern",
            "JSX/TSX syntax",
        ],
    },
    "Vue": {
        "indicators": ["package.json", "src/App.vue"],
        "config_files": ["package.json", "vue.config.js"],
        "characteristics": [
            "Single File Components (.vue)",
            "Options API or Composition API",
            "Template syntax with directives",
            "Pinia/Vuex for state management",
        ],
    },
    "Angular": {
        "indicators": ["angular.json", "package.json", "src/app/app.module.ts"],
        "config_files": ["angular.json", "package.json"],
        "characteristics": [
            "NgModule-based architecture",
            "TypeScript-first",
            "Dependency injection",
            "RxJS for reactive programming",
        ],
    },
    "Next.js": {
        "indicators": ["package.json", "next.config.js", "pages/", "app/"],
        "config_files": ["package.json", "next.config.js"],
        "characteristics": [
            "SSR/SSG capabilities",
            "File-based routing",
            "API routes in pages/api",
            "Server Components support",
        ],
    },
    "Express.js": {
        "indicators": ["package.json", "app.js", "server.js"],
        "config_files": ["package.json"],
        "characteristics": [
            "Middleware pattern",
            "Route-based API design",
            "Callback/Promise-based async",
        ],
    },
    "Gin": {
        "indicators": ["go.mod", "main.go"],
        "config_files": ["go.mod"],
        "characteristics": [
            "HTTP routing via gin.Engine",
            "Middleware pattern",
            "Context-based request handling",
        ],
    },
    "Rails": {
        "indicators": ["Gemfile", "config/routes.rb", "app/controllers"],
        "config_files": ["Gemfile", "routes.rb"],
        "characteristics": [
            "MVC pattern",
            "Active Record ORM",
            "Convention over configuration",
        ],
    },
    "Laravel": {
        "indicators": ["composer.json", "artisan", "app/Http"],
        "config_files": ["composer.json"],
        "characteristics": [
            "MVC pattern",
            "Eloquent ORM",
            "Service container",
            "Blade templating",
        ],
    },
}


def detect_frameworks(repo_path: str) -> list[FrameworkInfo]:
    """Detect frameworks used in the project."""
    frameworks = []
    seen = set()

    for name, rules in _FRAMEWORK_RULES.items():
        if name in seen:
            continue

        matched = []
        for indicator in rules["indicators"]:
            full_path = os.path.join(repo_path, indicator)
            if os.path.exists(full_path):
                matched.append(indicator)

        # Need at least 2 indicators (or 1 config file) to confirm
        config_matched = [m for m in matched if m in rules["config_files"]]
        if len(matched) >= 2 or len(config_matched) >= 1:
            frameworks.append(FrameworkInfo(
                name=name,
                config_files=config_matched,
                characteristics=rules["characteristics"],
            ))
            seen.add(name)

    return frameworks


def detect_primary_language(repo_path: str) -> str:
    """Detect primary programming language by counting files."""
    from utils.common import EXTENSION_LANGUAGE_MAP

    lang_counts = {}
    for root, dirs, files in os.walk(repo_path):
        # Skip common non-source dirs
        dirs[:] = [d for d in dirs if not should_skip_dir(d)]
        for f in files:
            ext = Path(f).suffix.lower()
            lang = EXTENSION_LANGUAGE_MAP.get(ext)
            if lang:
                lang_counts[lang] = lang_counts.get(lang, 0) + 1

    if not lang_counts:
        return "unknown"
    return max(lang_counts, key=lang_counts.get)


# ── Directory Structure ───────────────────────────────────────────────────

def _build_directory_structure(repo_path: str, max_depth: int = 2) -> str:
    """Build a tree-like directory structure string."""
    lines = []
    for root, dirs, files in os.walk(repo_path):
        depth = root[len(repo_path):].count(os.sep)
        if depth > max_depth:
            dirs.clear()
            continue

        # Skip non-source dirs
        dirs[:] = [d for d in dirs if not should_skip_dir(d) and not d.startswith(".")]

        rel = os.path.relpath(root, repo_path)
        if rel == ".":
            continue

        indent = "  " * depth
        lines.append(f"{indent}{os.path.basename(root)}/")

        # Show key files at this level (config files only)
        key_exts = {".xml", ".gradle", ".toml", ".cfg", ".ini", ".yml", ".yaml", ".json"}
        shown = 0
        for f in sorted(files)[:10]:
            if f.startswith("."):
                continue
            ext = Path(f).suffix.lower()
            if ext in key_exts and shown < 3:
                lines.append(f"{indent}  {f}")
                shown += 1

        if depth == max_depth:
            dirs.clear()  # Don't recurse deeper

    return "\n".join(lines[:30])  # Limit output


def _find_key_files(repo_path: str) -> dict[str, str]:
    """Find key project files (entry points, configs)."""
    key_files = {}

    patterns = {
        "Entry point": ["main.py", "app.py", "index.js", "main.go", "App.java", "Program.cs", "index.ts"],
        "Config": ["package.json", "pom.xml", "build.gradle", "go.mod", "Cargo.toml", "composer.json", "Gemfile"],
        "Database": ["schema.sql", "migrations/", "alembic.ini", "Prisma/schema.prisma"],
        "Docker": ["Dockerfile", "docker-compose.yml"],
    }

    for category, names in patterns.items():
        for name in names:
            full_path = os.path.join(repo_path, name)
            if os.path.exists(full_path):
                key_files[f"{category}: {name}"] = name

    return key_files


# ── Pattern Detection ─────────────────────────────────────────────────────

def detect_common_patterns(repo_path: str, frameworks: list[FrameworkInfo]) -> list[str]:
    """Detect common patterns in the project source code."""
    patterns = []

    # Detect MVC patterns
    has_models = any(os.path.exists(os.path.join(repo_path, d)) for d in ["models", "model", "Entities", "domain"])
    has_controllers = any(os.path.exists(os.path.join(repo_path, d)) for d in ["controllers", "controller", "Handlers", "rest"])
    has_services = any(os.path.exists(os.path.join(repo_path, d)) for d in ["services", "service", "Service", "business"])
    has_repos = any(os.path.exists(os.path.join(repo_path, d)) for d in ["repositories", "repository", "Repository", "dao", "data"])

    if has_models and has_controllers and has_services:
        patterns.append("MVC architecture pattern (models → controllers → services)")
    elif has_models and has_services:
        patterns.append("Service-Repository pattern (models → services)")

    # Detect test patterns
    has_tests = any(os.path.exists(os.path.join(repo_path, d)) for d in ["tests", "test", "spec", "__tests__"])
    if has_tests:
        patterns.append("Has test suite in tests/ directory")

    # Detect API patterns
    has_api = any(os.path.exists(os.path.join(repo_path, d)) for d in ["api", "routes", "graphql", "api_v1"])
    if has_api:
        patterns.append("Has dedicated API layer")

    # Detect frontend patterns
    has_frontend = any(os.path.exists(os.path.join(repo_path, d)) for d in ["public", "static", "assets", "components"])
    if has_frontend:
        patterns.append("Has frontend assets/components")

    # Detect config patterns
    has_config_dir = any(os.path.exists(os.path.join(repo_path, d)) for d in ["config", "configuration", "conf"])
    if has_config_dir:
        patterns.append("Centralized configuration in config/ directory")

    # Framework-specific patterns
    for fw in frameworks:
        if fw.name == "Spring Boot":
            if has_repos:
                patterns.append("Spring Data JPA repositories pattern")
            patterns.append("Layered architecture (Controller → Service → Repository)")
        elif fw.name == "Django":
            patterns.append("Django app pattern (models.py, views.py, urls.py)")
        elif fw.name == "React":
            patterns.append("React component pattern (functional components with hooks)")
        elif fw.name == "Express.js":
            patterns.append("Express middleware pattern")

    return patterns[:10]  # Limit to 10 patterns


def generate_constraints(frameworks: list[FrameworkInfo], language: str) -> list[str]:
    """Generate review constraints from detected frameworks."""
    constraints = []

    for fw in frameworks:
        if fw.name == "Spring Boot":
            constraints.extend([
                "Controllers should be thin — business logic in Services",
                "Use @Transactional for database operations",
                "REST endpoints should follow standard HTTP methods",
                "Input validation with @Valid and DTOs",
            ])
        elif fw.name == "Django":
            constraints.extend([
                "Views should use Class-Based Views or function-based with decorators",
                "Use Django ORM instead of raw SQL",
                "Forms for user input validation",
            ])
        elif fw.name == "React":
            constraints.extend([
                "Prefer functional components with hooks over class components",
                "Don't mutate state directly",
                "Use proper cleanup in useEffect",
            ])
        elif fw.name == "Go":
            constraints.extend([
                "Errors must be handled, not ignored",
                "Use context for cancellation and timeouts",
            ])

    if language == "python":
        constraints.append("Use type hints for function signatures")
    elif language == "typescript":
        constraints.append("Prefer strict TypeScript types over 'any'")

    return constraints


# ── Stats ─────────────────────────────────────────────────────────────────

def _count_project_stats(repo_path: str) -> tuple[int, int]:
    """Count total source files and lines in the project."""
    source_extensions = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".php", ".rb", ".kt", ".cs", ".vue"}
    total_files = 0
    total_lines = 0

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if not should_skip_dir(d)]
        for f in files:
            ext = Path(f).suffix.lower()
            if ext in source_extensions:
                total_files += 1
                try:
                    full_path = os.path.join(root, f)
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as fh:
                        total_lines += sum(1 for _ in fh)
                except Exception:
                    pass

    return total_files, total_lines
