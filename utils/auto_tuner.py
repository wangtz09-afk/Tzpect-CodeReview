"""Auto-Tuner — generates .codereview.yml rules from accumulated feedback.

Analyzes feedback patterns and produces:
- suppress rules: issue types frequently dismissed in certain file categories
- prioritize rules: issue types consistently accepted (high accuracy)
- severity adjustments: override severity based on historical accuracy
"""
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from utils.feedback_db import FeedbackDB, LearnedPattern
from utils.logger import get_logger


@dataclass
class SuppressionRule:
    """A rule to suppress a check in certain file categories."""
    issue_type: str
    file_category: str
    confidence: float
    dismissed_count: int
    total_count: int
    reason: str


@dataclass
class PriorityRule:
    """A rule to prioritize a check in certain file categories."""
    issue_type: str
    file_category: str
    confidence: float
    accepted_count: int
    total_count: int
    reason: str


@dataclass
class AutoTunedConfig:
    """Generated auto-tuned configuration."""
    suppress: list[SuppressionRule] = field(default_factory=list)
    prioritize: list[PriorityRule] = field(default_factory=list)

    def to_yaml(self) -> str:
        """Serialize to YAML format suitable for .codereview.yml."""
        lines = [
            "# [AUTO-GENERATED FROM FEEDBACK] — Do not edit manually",
            f"# Generated at: {datetime.now().isoformat()}",
            f"# Source: feedback learning across {sum(s.dismissed_count for s in self.suppress)} dismissals",
            "#",
            "# Run `py main.py tune-rules` to regenerate.",
            "auto_tuned:",
        ]

        if self.suppress:
            lines.append("  # Issue types frequently dismissed in these file categories")
            lines.append("  suppress:")
            for rule in sorted(self.suppress, key=lambda r: r.confidence, reverse=True):
                fp_pct = rule.dismissed_count / rule.total_count if rule.total_count > 0 else 0
                lines.append(f"    - issue_type: \"{rule.issue_type}\"")
                lines.append(f"      file_category: \"{rule.file_category}\"")
                lines.append(f"      confidence: {rule.confidence:.2f}")
                lines.append(f"      fp_rate: \"{fp_pct:.0%}\"")
                lines.append(f"      reason: \"{rule.reason}\"")

        if self.prioritize:
            lines.append("  # Issue types consistently confirmed in these file categories")
            lines.append("  prioritize:")
            for rule in sorted(self.prioritize, key=lambda r: r.confidence):
                lines.append(f"    - issue_type: \"{rule.issue_type}\"")
                lines.append(f"      file_category: \"{rule.file_category}\"")
                lines.append(f"      confidence: {rule.confidence:.2f}")
                lines.append(f"      reason: \"{rule.reason}\"")

        lines.append("")
        return "\n".join(lines)

    def to_codereview_patch(self) -> str:
        """Generate a patch block to append to .codereview.yml.

        Produces a YAML snippet that can be merged into an existing
        .codereview.yml file's auto_tuned section.
        """
        return self.to_yaml()


class AutoTuner:
    """Generates review tuning rules from accumulated feedback.

    Workflow:
    1. Query learned_patterns table from FeedbackDB
    2. Classify patterns as suppress/prioritize based on confidence
    3. Generate YAML config
    4. Optionally write to .codereview.yml
    """

    # Thresholds for rule generation
    SUPPRESS_CONFIDENCE = 0.65   # FP confidence >= 65% → suppress
    PRIORITIZE_CONFIDENCE = 0.35 # FP confidence < 35% → prioritize (high accuracy)
    MIN_EVIDENCE = 3             # Minimum evidence count for any rule

    def __init__(self, db_path: Optional[str] = None):
        self.db = FeedbackDB(db_path)
        self.logger = get_logger("auto_tuner")

    def tune(self) -> AutoTunedConfig:
        """Generate auto-tuned configuration from feedback data.

        Returns:
            AutoTunedConfig with suppress and prioritize rules.
        """
        patterns = self.db.get_learned_patterns()
        config = AutoTunedConfig()

        for p in patterns:
            if p.evidence_count < self.MIN_EVIDENCE:
                continue

            # Suppression: high FP confidence
            if p.confidence >= self.SUPPRESS_CONFIDENCE and p.dismissed_count >= 2:
                total = p.accepted_count + p.dismissed_count
                reason = p.reason if p.reason else self._default_suppression_reason(p)
                config.suppress.append(SuppressionRule(
                    issue_type=p.issue_type,
                    file_category=p.file_category,
                    confidence=p.confidence,
                    dismissed_count=p.dismissed_count,
                    total_count=total,
                    reason=reason,
                ))

            # Prioritize: low FP confidence (high accuracy)
            elif p.confidence <= self.PRIORITIZE_CONFIDENCE and p.accepted_count >= 2:
                total = p.accepted_count + p.dismissed_count
                reason = p.reason if p.reason else self._default_priority_reason(p)
                config.prioritize.append(PriorityRule(
                    issue_type=p.issue_type,
                    file_category=p.file_category,
                    confidence=p.confidence,
                    accepted_count=p.accepted_count,
                    total_count=total,
                    reason=reason,
                ))

        self.logger.info(
            f"Tuned {len(config.suppress)} suppress + {len(config.prioritize)} prioritize rules "
            f"from {len(patterns)} learned patterns"
        )
        return config

    def apply_to_file(self, config_path: str) -> bool:
        """Write auto-tuned rules to a .codereview.yml file.

        Reads existing file, updates auto_tuned section, writes back.

        Args:
            config_path: Path to .codereview.yml.

        Returns:
            True if file was updated.
        """
        config = self.tune()

        if not config.suppress and not config.prioritize:
            self.logger.info("No rules to write")
            return False

        yaml_block = config.to_yaml()

        path = Path(config_path)
        existing_content = ""
        if path.exists():
            existing_content = path.read_text(encoding="utf-8")

        # Remove old auto_tuned block if present
        if "# [AUTO-GENERATED FROM FEEDBACK]" in existing_content:
            # Find and replace the block
            start = existing_content.find("# [AUTO-GENERATED FROM FEEDBACK]")
            # Find end: either next section marker or end of file
            end = self._find_auto_tuned_end(existing_content, start)
            existing_content = existing_content[:start] + existing_content[end:]
            # Clean up trailing whitespace before next section
            existing_content = existing_content.rstrip() + "\n"

        # Append the new block
        if existing_content and not existing_content.endswith("\n\n"):
            if existing_content.endswith("\n"):
                existing_content += "\n"
            else:
                existing_content += "\n\n"

        updated = existing_content + yaml_block
        path.write_text(updated, encoding="utf-8")

        self.logger.info(f"Wrote auto-tuned rules to {config_path}")
        return True

    def _find_auto_tuned_end(self, content: str, start: int) -> int:
        """Find the end of an auto_tuned block in YAML content."""
        lines = content[start:].split("\n")
        end_offset = start

        in_auto_tuned = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("auto_tuned:"):
                in_auto_tuned = True
                end_offset += len(line) + 1
                continue

            if in_auto_tuned:
                # Block ends when we hit a non-indented, non-empty, non-comment line
                if stripped and not stripped.startswith("#") and not line.startswith(" ") and not line.startswith("\t"):
                    break
                end_offset += len(line) + 1

        return min(end_offset, len(content))

    def _default_suppression_reason(self, pattern: LearnedPattern) -> str:
        total = pattern.accepted_count + pattern.dismissed_count
        fp_pct = pattern.dismissed_count / total if total > 0 else 0
        return (
            f"Dismissed {pattern.dismissed_count}/{total} times ({fp_pct:.0%} FP rate) "
            f"in {pattern.file_category} files"
        )

    def _default_priority_reason(self, pattern: LearnedPattern) -> str:
        total = pattern.accepted_count + pattern.dismissed_count
        acc_pct = pattern.accepted_count / total if total > 0 else 0
        return (
            f"Accepted {pattern.accepted_count}/{total} times ({acc_pct:.0%} accuracy) "
            f"in {pattern.file_category} files"
        )
