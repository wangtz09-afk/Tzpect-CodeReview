"""Custom rules engine — loads and applies .codereview.yml configuration.

Users can define their own review rules, ignore patterns, and severity overrides.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    import json5
    HAS_JSON5 = True
except ImportError:
    HAS_JSON5 = False


@dataclass
class Rule:
    """A single custom rule."""
    id: str
    name: str
    description: str
    severity: str = "medium"  # critical, high, medium, low
    enabled: bool = True
    languages: list[str] = field(default_factory=list)  # empty = all
    patterns: list[str] = field(default_factory=list)  # regex patterns to match
    ignore: bool = False  # if True, suppress this rule


@dataclass
class RuleConfig:
    """Complete rule configuration."""
    rules: list[Rule] = field(default_factory=list)
    ignore_patterns: list[str] = field(default_factory=list)
    severity_overrides: dict[str, str] = field(default_factory=dict)
    enabled_checks: list[str] = field(default_factory=list)
    disabled_checks: list[str] = field(default_factory=list)
    custom_instructions: str = ""
    max_issues: int = 50
    min_severity: str = "low"
    # Auto-tuned rules from feedback learning
    auto_suppress: list[dict] = field(default_factory=list)   # {issue_type, file_category, confidence, reason}
    auto_prioritize: list[dict] = field(default_factory=list)  # {issue_type, file_category, confidence, reason}


def find_config_file(repo_path: str) -> Optional[str]:
    """Find .codereview.yml in project root or parent directories."""
    current = Path(repo_path).resolve()

    # Check up to 3 levels up
    for _ in range(4):
        for config_name in [".codereview.yml", ".codereview.yaml", ".codereview.json"]:
            config_path = current / config_name
            if config_path.exists():
                return str(config_path)
        current = current.parent
        if str(current) == str(current.parent):  # reached root
            break

    return None


def load_rules(repo_path: str) -> RuleConfig:
    """Load rules from .codereview.yml in project root.

    Falls back to default config if file not found or parsing fails.

    Args:
        repo_path: Path to project root.

    Returns:
        RuleConfig with loaded rules.
    """
    config = RuleConfig()

    config_path = find_config_file(repo_path)
    if not config_path:
        return config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return config

    try:
        if config_path.endswith(".json"):
            data = _parse_json(content)
        else:
            data = _parse_yaml(content)

        if data:
            _apply_config(data, config)
    except Exception:
        pass  # Return defaults on parse error

    return config


def _parse_yaml(content: str) -> Optional[dict]:
    """Parse YAML content."""
    if HAS_YAML:
        try:
            return yaml.safe_load(content)
        except Exception:
            pass
    # Fallback: simple key-value parsing
    return None


def _parse_json(content: str) -> Optional[dict]:
    """Parse JSON content."""
    if HAS_JSON5:
        try:
            return json5.loads(content)
        except Exception:
            pass
    try:
        return json.loads(content)
    except Exception:
        return None


def _apply_config(data: dict, config: RuleConfig) -> None:
    """Apply parsed config data to RuleConfig."""
    if not isinstance(data, dict):
        return

    # Ignore patterns
    if "ignore" in data:
        ignores = data["ignore"]
        if isinstance(ignores, list):
            config.ignore_patterns = [str(p) for p in ignores]
        elif isinstance(ignores, str):
            config.ignore_patterns = [ignores]

    # Severity overrides
    if "severity" in data and isinstance(data["severity"], dict):
        config.severity_overrides = {
            str(k): str(v) for k, v in data["severity"].items()
        }

    # Enabled checks
    if "enabled" in data and isinstance(data["enabled"], (list, dict)):
        if isinstance(data["enabled"], list):
            config.enabled_checks = [str(c) for c in data["enabled"]]
        elif isinstance(data["enabled"], dict):
            for k, v in data["enabled"].items():
                if v:
                    config.enabled_checks.append(k)

    # Disabled checks
    if "disabled" in data and isinstance(data["disabled"], (list, dict)):
        if isinstance(data["disabled"], list):
            config.disabled_checks = [str(c) for c in data["disabled"]]
        elif isinstance(data["disabled"], dict):
            for k, v in data["disabled"].items():
                if v:
                    config.disabled_checks.append(k)

    # Custom rules
    if "rules" in data and isinstance(data["rules"], list):
        for rule_data in data["rules"]:
            if isinstance(rule_data, dict):
                rule = _parse_rule(rule_data)
                if rule:
                    config.rules.append(rule)

    # Custom instructions
    if "instructions" in data:
        config.custom_instructions = str(data["instructions"])

    # Max issues
    if "max_issues" in data:
        try:
            config.max_issues = int(data["max_issues"])
        except (ValueError, TypeError):
            pass

    # Min severity
    if "min_severity" in data:
        config.min_severity = str(data["min_severity"])

    # Auto-tuned rules from feedback learning
    if "auto_tuned" in data and isinstance(data["auto_tuned"], dict):
        auto_data = data["auto_tuned"]
        if "suppress" in auto_data and isinstance(auto_data["suppress"], list):
            config.auto_suppress = [
                s for s in auto_data["suppress"] if isinstance(s, dict)
            ]
        if "prioritize" in auto_data and isinstance(auto_data["prioritize"], list):
            config.auto_prioritize = [
                p for p in auto_data["prioritize"] if isinstance(p, dict)
            ]


def _parse_rule(data: dict) -> Optional[Rule]:
    """Parse a single rule from dict."""
    if "id" not in data:
        return None

    severity = str(data.get("severity", "medium")).lower()
    if severity not in ("critical", "high", "medium", "low"):
        severity = "medium"

    languages = data.get("languages", [])
    if isinstance(languages, str):
        languages = [languages]

    patterns = data.get("patterns", [])
    if isinstance(patterns, str):
        patterns = [patterns]

    return Rule(
        id=str(data["id"]),
        name=str(data.get("name", data["id"])),
        description=str(data.get("description", "")),
        severity=severity,
        enabled=data.get("enabled", True),
        languages=[str(l).lower() for l in languages],
        patterns=[str(p) for p in patterns],
        ignore=data.get("ignore", False),
    )


def should_ignore(file_path: str, rule_config: RuleConfig) -> bool:
    """Check if a file should be ignored based on rule config.

    Args:
        file_path: File path to check.
        rule_config: Rule configuration.

    Returns:
        True if file should be ignored.
    """
    import fnmatch

    for pattern in rule_config.ignore_patterns:
        if fnmatch.fnmatch(file_path, pattern):
            return True
        # Also check basename
        if fnmatch.fnmatch(os.path.basename(file_path), pattern):
            return True

    return False


def is_check_enabled(check_name: str, rule_config: RuleConfig) -> bool:
    """Check if a review check is enabled.

    Args:
        check_name: Name of the check (e.g., "security", "performance").
        rule_config: Rule configuration.

    Returns:
        True if check should be run.
    """
    # Disabled checks take priority
    if check_name in rule_config.disabled_checks:
        return False

    # If enabled list is set, only those are enabled
    if rule_config.enabled_checks:
        return check_name in rule_config.enabled_checks

    return True


def get_severity_override(issue_type: str, rule_config: RuleConfig) -> Optional[str]:
    """Get severity override for an issue type.

    Args:
        issue_type: Type of issue (e.g., "SQL Injection").
        rule_config: Rule configuration.

    Returns:
        Overridden severity or None if no override.
    """
    return rule_config.severity_overrides.get(issue_type)


def is_auto_suppressed(issue_type: str, file_category: str, rule_config: RuleConfig) -> bool:
    """Check if an issue type is auto-suppressed for a given file category.

    Args:
        issue_type: Type of issue (e.g., "Magic Number").
        file_category: Normalized file category (e.g., "java:spring:controller").
        rule_config: Rule configuration with auto_tuned rules.

    Returns:
        True if this issue type should be suppressed for this file category.
    """
    if not rule_config.auto_suppress:
        return False

    for rule in rule_config.auto_suppress:
        if rule.get("issue_type") == issue_type:
            rule_category = rule.get("file_category", "")
            if not rule_category or rule_category == file_category:
                return True

    return False


def to_prompt(rule_config: RuleConfig, language: str = "") -> str:
    """Convert rule config to a prompt section for LLM.

    Args:
        rule_config: Rule configuration.
        language: Current language (for language-specific rules).

    Returns:
        Prompt section string or empty string if no rules.
    """
    lines = []

    # Custom instructions
    if rule_config.custom_instructions:
        lines.append("## Custom Review Instructions")
        lines.append(rule_config.custom_instructions)
        lines.append("")

    # Disabled checks
    if rule_config.disabled_checks:
        lines.append("## Disabled Checks")
        lines.append("Do NOT check for the following (suppressed by project config):")
        for check in rule_config.disabled_checks:
            lines.append(f"- {check}")
        lines.append("")

    # Custom rules
    custom_rules = [r for r in rule_config.rules if r.enabled and (not r.languages or language.lower() in r.languages)]
    if custom_rules:
        lines.append("## Custom Project Rules")
        for rule in custom_rules:
            lines.append(f"- **{rule.name}** ({rule.severity}): {rule.description}")
        lines.append("")

    # Severity overrides
    if rule_config.severity_overrides:
        lines.append("## Severity Overrides")
        for issue_type, severity in rule_config.severity_overrides.items():
            lines.append(f"- {issue_type} → {severity}")
        lines.append("")

    # Auto-tuned rules from feedback learning
    if rule_config.auto_suppress or rule_config.auto_prioritize:
        lines.append("## Feedback-Learned Rules (auto-generated)")
        lines.append("These rules are learned from accumulated review feedback. Run `py main.py tune-rules` to update.")
        lines.append("")

        if rule_config.auto_suppress:
            lines.append("### Auto-Suppressed Checks (do NOT report unless strong evidence)")
            for s in rule_config.auto_suppress:
                issue_type = s.get("issue_type", "Unknown")
                category = s.get("file_category", "")
                reason = s.get("reason", "")
                fp_rate = s.get("fp_rate", "")
                desc = f"- `{issue_type}`"
                if category:
                    desc += f" in `{category}`"
                if fp_rate:
                    desc += f" (FP rate: {fp_rate})"
                lines.append(desc)
                if reason:
                    lines.append(f"  → {reason}")
            lines.append("")

        if rule_config.auto_prioritize:
            lines.append("### Auto-Prioritized Checks (report confidently)")
            for p in rule_config.auto_prioritize:
                issue_type = p.get("issue_type", "Unknown")
                category = p.get("file_category", "")
                reason = p.get("reason", "")
                desc = f"- `{issue_type}`"
                if category:
                    desc += f" in `{category}`"
                lines.append(desc)
                if reason:
                    lines.append(f"  → {reason}")
            lines.append("")

    return "\n".join(lines) if lines else ""
