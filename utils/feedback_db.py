"""Feedback learning — tracks review accuracy and improves future reviews.

Stores:
- False positives (user dismissed issues)
- Confirmed issues (user accepted issues)
- Issue patterns that are consistently wrong/right
- Per-project feedback history
- Cross-project learned patterns (shared knowledge)
- Auto-collected feedback from apply-fixes actions
"""
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from utils.common import get_language as _get_language


@dataclass
class FeedbackEntry:
    """A single feedback entry."""
    id: int = 0
    file_path: str = ""
    issue_type: str = ""
    issue_description: str = ""
    severity: str = ""
    verdict: str = ""  # accepted, dismissed, modified
    timestamp: str = ""
    session_id: str = ""
    correction: str = ""  # user's correction if modified
    auto_collected: int = 0  # 1 = auto-collected, 0 = manual
    file_category: str = ""  # normalized category, e.g. "java:spring:service"
    language: str = ""


@dataclass
class FeedbackStats:
    """Aggregated feedback statistics."""
    total_reviews: int = 0
    accepted: int = 0
    dismissed: int = 0
    modified: int = 0
    acceptance_rate: float = 0.0
    false_positive_rate: float = 0.0
    # Per-issue-type stats
    type_stats: dict[str, dict] = field(default_factory=dict)


@dataclass
class LearnedPattern:
    """A learned pattern from cross-project feedback."""
    id: int = 0
    issue_type: str = ""
    file_category: str = ""
    language: str = ""
    is_false_positive: int = 0
    confidence: float = 0.5
    evidence_count: int = 0
    accepted_count: int = 0
    dismissed_count: int = 0
    reason: str = ""
    updated_at: str = ""


class FeedbackDB:
    """SQLite-backed feedback database for review accuracy tracking.

    Stores user feedback on review results and uses it to improve
    future reviews by learning which issue types are commonly
    false positives for each project.

    Supports:
    - Auto-collected feedback from apply-fixes actions
    - Cross-project knowledge transfer via normalized file categories
    - Time-weighted confidence decay
    - LLM-inferred suppression reasons
    """

    # Time decay half-life: 90 days — feedback older than this contributes less
    DECAY_HALF_LIFE_DAYS = 90

    # --- Path-to-category normalization rules ---
    # Maps path segments / file name patterns to file role labels
    _ROLE_PATTERNS = {
        "controller": ["controller", "controller", "handlers", "rest", "views"],
        "service": ["service", "services", "service_impl", "business", "logic"],
        "repository": ["repository", "repositories", "dao", "data", "mapper", "mappers"],
        "model": ["model", "models", "entity", "entities", "domain", "pojo", "bean", "beans"],
        "config": ["config", "configuration", "conf", "settings", "properties"],
        "test": ["test", "tests", "spec", "specs", "__tests__", "e2e", "integration"],
        "util": ["util", "utils", "helpers", "helper", "common"],
        "middleware": ["middleware", "interceptor", "interceptors", "filter", "filters"],
    }

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(Path(__file__).parent.parent / ".feedback.db")
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema with migration support."""
        with sqlite3.connect(self.db_path) as conn:
            # Create tables first (IF NOT EXISTS is safe for fresh DBs)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL,
                    issue_type TEXT NOT NULL,
                    issue_description TEXT,
                    severity TEXT,
                    verdict TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    session_id TEXT,
                    correction TEXT,
                    auto_collected INTEGER DEFAULT 0,
                    file_category TEXT,
                    language TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learned_patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issue_type TEXT NOT NULL,
                    file_category TEXT NOT NULL,
                    language TEXT NOT NULL DEFAULT '',
                    is_false_positive INTEGER DEFAULT 0,
                    confidence REAL DEFAULT 0.5,
                    evidence_count INTEGER DEFAULT 0,
                    accepted_count INTEGER DEFAULT 0,
                    dismissed_count INTEGER DEFAULT 0,
                    reason TEXT DEFAULT '',
                    updated_at TEXT NOT NULL,
                    UNIQUE(issue_type, file_category, language)
                )
            """)

            # Migrate existing tables — add new columns if missing
            cursor = conn.execute("PRAGMA table_info(feedback)")
            existing_columns = {row[1] for row in cursor.fetchall()}

            if "auto_collected" not in existing_columns:
                conn.execute("ALTER TABLE feedback ADD COLUMN auto_collected INTEGER DEFAULT 0")
            if "file_category" not in existing_columns:
                conn.execute("ALTER TABLE feedback ADD COLUMN file_category TEXT")
            if "language" not in existing_columns:
                conn.execute("ALTER TABLE feedback ADD COLUMN language TEXT")

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_file_type
                ON feedback(file_path, issue_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_verdict
                ON feedback(verdict, issue_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_category
                ON feedback(file_category, issue_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp
                ON feedback(timestamp)
            """)
            conn.commit()

    # ── Core Feedback Operations ─────────────────────────────────────────

    def add_feedback(
        self,
        file_path: str,
        issue_type: str,
        verdict: str,
        issue_description: str = "",
        severity: str = "",
        session_id: str = "",
        correction: str = "",
        auto_collected: bool = False,
        file_category: str = "",
        language: str = "",
    ) -> int:
        """Add feedback entry.

        Args:
            file_path: File that was reviewed.
            issue_type: Type of issue (e.g., "SQL Injection").
            verdict: "accepted", "dismissed", or "modified".
            issue_description: Description of the issue.
            severity: Issue severity.
            session_id: Review session ID.
            correction: User's correction text (if modified).
            auto_collected: Whether this was auto-collected.
            file_category: Normalized file category (for cross-project learning).
            language: Programming language.

        Returns:
            ID of the inserted row.
        """
        if not file_category:
            file_category = self.normalize_path(file_path)
        if not language:
            language = _get_language(file_path)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO feedback (file_path, issue_type, issue_description, severity, verdict, timestamp, session_id, correction, auto_collected, file_category, language)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (file_path, issue_type, issue_description, severity, verdict,
                 datetime.now().isoformat(), session_id, correction,
                 1 if auto_collected else 0, file_category, language),
            )
            conn.commit()

            # Immediately update learned pattern
            self._update_learned_pattern(
                conn, issue_type, file_category, language, verdict
            )

            return cursor.lastrowid

    def auto_collect(
        self,
        file_path: str,
        issues: list[dict],
        applied_issue_types: set[str],
        skipped_issue_types: set[str],
        modified_issue_types: set[str],
    ) -> int:
        """Auto-collect feedback based on apply-fixes actions.

        Records which issues the user acted on (applied/skipped/modified).

        Args:
            file_path: File being fixed.
            issues: List of issue dicts from review result.
            applied_issue_types: Issue types that were applied via apply-fixes.
            skipped_issue_types: Issue types that were skipped.
            modified_issue_types: Issue types where fix was manually modified.

        Returns:
            Number of feedback entries recorded.
        """
        file_category = self.normalize_path(file_path)
        language = _get_language(file_path)
        session_id = f"auto-{int(time.time())}"
        count = 0

        for issue in issues:
            issue_type = issue.get("type", "Unknown")
            severity = issue.get("severity", "medium")
            description = issue.get("description", "")

            if issue_type in applied_issue_types:
                verdict = "accepted"
            elif issue_type in skipped_issue_types:
                verdict = "dismissed"
            elif issue_type in modified_issue_types:
                verdict = "modified"
                correction = issue.get("fix_suggestion", "")
            else:
                continue  # No action taken, skip

            self.add_feedback(
                file_path=file_path,
                issue_type=issue_type,
                verdict=verdict,
                issue_description=description,
                severity=severity,
                session_id=session_id,
                auto_collected=True,
                file_category=file_category,
                language=language,
            )
            count += 1

        return count

    # ── Learned Pattern Management ───────────────────────────────────────

    def _update_learned_pattern(
        self,
        conn: sqlite3.Connection,
        issue_type: str,
        file_category: str,
        language: str,
        verdict: str,
    ) -> None:
        """Update learned pattern after a new feedback entry.

        Uses exponential moving average for confidence updates:
        confidence_new = confidence_old + alpha * (target - confidence_old)
        where alpha = 1 / (evidence_count + 1) for faster convergence early.
        """
        row = conn.execute(
            """SELECT confidence, evidence_count, accepted_count, dismissed_count
               FROM learned_patterns
               WHERE issue_type = ? AND file_category = ? AND language = ?""",
            (issue_type, file_category, language),
        ).fetchone()

        if row:
            old_confidence, evidence_count, accepted_count, dismissed_count = row
        else:
            old_confidence = 0.5
            evidence_count = 0
            accepted_count = 0
            dismissed_count = 0

        if verdict == "accepted":
            accepted_count += 1
        elif verdict == "dismissed":
            dismissed_count += 1
        elif verdict == "modified":
            accepted_count += 0.5  # Partial credit
            dismissed_count += 0.5

        evidence_count += 1
        total = accepted_count + dismissed_count

        if total > 0:
            # Target: 1.0 if mostly dismissed (false positive), 0.0 if mostly accepted
            target = dismissed_count / total if total > 0 else 0.5
            alpha = 1.0 / (evidence_count + 1)
            new_confidence = old_confidence + alpha * (target - old_confidence)
            is_fp = 1 if dismissed_count > accepted_count * 2 else 0
        else:
            new_confidence = 0.5
            is_fp = 0

        now = datetime.now().isoformat()

        conn.execute(
            """INSERT OR REPLACE INTO learned_patterns
               (issue_type, file_category, language, is_false_positive, confidence,
                evidence_count, accepted_count, dismissed_count, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (issue_type, file_category, language, is_fp, round(new_confidence, 3),
             evidence_count, int(accepted_count), int(dismissed_count), now),
        )

    def get_learned_patterns(
        self,
        file_category: str = "",
        language: str = "",
        min_confidence: float = 0.0,
    ) -> list[LearnedPattern]:
        """Get learned patterns, optionally filtered.

        Args:
            file_category: Filter by file category.
            language: Filter by language.
            min_confidence: Only return patterns with at least this confidence.

        Returns:
            List of LearnedPattern objects.
        """
        query = "SELECT id, issue_type, file_category, language, is_false_positive, confidence, evidence_count, accepted_count, dismissed_count, reason, updated_at FROM learned_patterns WHERE 1=1"
        params = []

        if file_category:
            query += " AND file_category = ?"
            params.append(file_category)
        if language:
            query += " AND language = ?"
            params.append(language)
        if min_confidence > 0:
            query += " AND confidence >= ?"
            params.append(min_confidence)

        query += " ORDER BY confidence DESC, evidence_count DESC"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()

        return [
            LearnedPattern(
                id=r["id"], issue_type=r["issue_type"], file_category=r["file_category"],
                language=r["language"], is_false_positive=r["is_false_positive"],
                confidence=r["confidence"], evidence_count=r["evidence_count"],
                accepted_count=r["accepted_count"], dismissed_count=r["dismissed_count"],
                reason=r["reason"], updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def infer_reasons(self, llm_call_fn=None) -> int:
        """Use LLM to infer suppression reasons for high-confidence false positives.

        Calls the provided LLM function to generate a human-readable reason
        for why an issue type is consistently a false positive in a file category.

        Args:
            llm_call_fn: Async function(issue_type, file_category, dismissed_count) -> str.
                         If None, generates a default reason.

        Returns:
            Number of patterns with inferred reasons.
        """
        patterns = self.get_learned_patterns(min_confidence=0.65)
        fp_patterns = [p for p in patterns if p.is_false_positive and not p.reason]

        updated = 0
        for p in fp_patterns:
            if llm_call_fn:
                reason = llm_call_fn(p.issue_type, p.file_category, p.dismissed_count)
            else:
                reason = self._default_reason(p)

            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE learned_patterns SET reason = ? WHERE issue_type = ? AND file_category = ? AND language = ?",
                    (reason, p.issue_type, p.file_category, p.language),
                )
            updated += 1

        return updated

    def _default_reason(self, pattern: LearnedPattern) -> str:
        """Generate a default reason based on pattern data."""
        total = pattern.accepted_count + pattern.dismissed_count
        fp_rate = pattern.dismissed_count / total if total > 0 else 0
        return (
            f"Consistently dismissed in {pattern.file_category} files "
            f"({fp_rate:.0%} false positive rate across {pattern.evidence_count} reviews)"
        )

    # ── Path Normalization ───────────────────────────────────────────────

    def normalize_path(self, file_path: str) -> str:
        """Normalize a file path to a cross-project category.

        Converts raw paths like:
            "sky-server/src/com/sky/controller/EmployeeController.java"
        to:
            "java:spring:controller"

        The category is: language:framework:role

        Args:
            file_path: Raw file path (relative to project root).

        Returns:
            Normalized category string.
        """
        language = _get_language(file_path)
        framework = self._detect_framework(file_path)
        role = self._detect_role(file_path)

        return f"{language}:{framework}:{role}"

    def _detect_framework(self, file_path: str) -> str:
        """Detect framework from file path patterns."""
        lower = file_path.lower()
        if any(kw in lower for kw in ["controller", "service", "mapper", "spring"]):
            return "spring"
        if any(kw in lower for kw in ["django", "settings", "views"]):
            return "django"
        if any(kw in lower for kw in ["react", "jsx", "tsx", "component"]):
            return "react"
        if any(kw in lower for kw in ["vue", ".vue"]):
            return "vue"
        if any(kw in lower for kw in ["gin", "handler", "middleware"]):
            return "gin"
        return "generic"

    def _detect_role(self, file_path: str) -> str:
        """Detect file role from path and name."""
        lower = file_path.lower()
        parts = lower.replace("\\", "/").split("/")

        # Check each path segment against role patterns
        for role, keywords in self._ROLE_PATTERNS.items():
            if any(kw in parts for kw in keywords):
                return role
            if any(kw in lower for kw in keywords):
                return role

        # Check file name suffixes
        if "controller" in lower or "controller" in lower:
            return "controller"
        if "service" in lower or "serviceimpl" in lower:
            return "service"
        if "mapper" in lower or "dao" in lower or "repository" in lower:
            return "repository"
        if "entity" in lower or "pojo" in lower or "model" in lower:
            return "model"
        if "config" in lower:
            return "config"

        return "other"

    # ── Statistics ───────────────────────────────────────────────────────

    def get_stats(self, project_filter: str = "") -> FeedbackStats:
        """Get aggregated feedback statistics.

        Args:
            project_filter: Filter by file path prefix.

        Returns:
            FeedbackStats with counts and rates.
        """
        query = "SELECT verdict, issue_type, COUNT(*) FROM feedback"
        params = []
        if project_filter:
            query += " WHERE file_path LIKE ?"
            params.append(f"{project_filter}%")
        query += " GROUP BY verdict, issue_type"

        stats = FeedbackStats()
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()

        type_data = {}
        for verdict, issue_type, count in rows:
            stats.total_reviews += count
            if verdict == "accepted":
                stats.accepted += count
            elif verdict == "dismissed":
                stats.dismissed += count
            elif verdict == "modified":
                stats.modified += count

            if issue_type not in type_data:
                type_data[issue_type] = {"accepted": 0, "dismissed": 0, "modified": 0}
            type_data[issue_type][verdict] = count

        if stats.accepted + stats.dismissed > 0:
            stats.acceptance_rate = stats.accepted / (stats.accepted + stats.dismissed)
            stats.false_positive_rate = stats.dismissed / (stats.accepted + stats.dismissed)

        stats.type_stats = type_data
        return stats

    def export_stats(self) -> dict:
        """Export statistics as a dict for JSON/CLI output.

        Returns:
            Dict with stats and per-type breakdown.
        """
        stats = self.get_stats()
        return {
            "total_reviews": stats.total_reviews,
            "accepted": stats.accepted,
            "dismissed": stats.dismissed,
            "modified": stats.modified,
            "acceptance_rate": round(stats.acceptance_rate, 3),
            "false_positive_rate": round(stats.false_positive_rate, 3),
            "type_stats": stats.type_stats,
        }

    def get_dismissed_types(self, project_filter: str = "", min_count: int = 3) -> list[str]:
        """Get issue types that are commonly dismissed (false positives).

        Args:
            project_filter: Filter by file path prefix.
            min_count: Minimum dismiss count to be considered.

        Returns:
            List of issue types that are likely false positives.
        """
        query = """
            SELECT issue_type,
                   SUM(CASE WHEN verdict = 'dismissed' THEN 1 ELSE 0 END) as dismissed,
                   COUNT(*) as total
            FROM feedback
        """
        params: list = []
        if project_filter:
            query += " WHERE file_path LIKE ?"
            params.append(f"{project_filter}%")
        query += " GROUP BY issue_type HAVING dismissed >= ?"
        params.append(min_count)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()

        return [row[0] for row in rows]

    def get_high_accuracy_types(self, project_filter: str = "", min_acceptance: float = 0.7) -> list[str]:
        """Get issue types with high acceptance rate.

        Args:
            project_filter: Filter by file path prefix.
            min_acceptance: Minimum acceptance rate.

        Returns:
            List of issue types that are consistently accurate.
        """
        query = """
            SELECT issue_type,
                   SUM(CASE WHEN verdict = 'accepted' THEN 1 ELSE 0 END) as accepted,
                   COUNT(*) as total
            FROM feedback
        """
        params: list = []
        if project_filter:
            query += " WHERE file_path LIKE ?"
            params.append(f"{project_filter}%")
        query += " GROUP BY issue_type HAVING accepted * 1.0 / total >= ? AND total >= 2"
        params.append(min_acceptance)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()

        return [row[0] for row in rows]

    # ── Prompt Generation (Weighted) ────────────────────────────────────

    def get_feedback_for_prompt(self, file_path: str) -> str:
        """Generate structured weighted feedback context for LLM prompt.

        Combines per-project feedback data with cross-project learned patterns
        to produce a layered, confidence-weighted prompt section.

        Args:
            file_path: File being reviewed.

        Returns:
            Prompt section string with adaptive review guidelines.
        """
        file_category = self.normalize_path(file_path)
        language = _get_language(file_path)

        # Get per-project feedback (dir-level)
        dir_path = os.path.dirname(file_path)
        project_dismissed = self.get_dismissed_types(dir_path, min_count=2)
        project_high_accuracy = self.get_high_accuracy_types(dir_path)

        # Get cross-project learned patterns
        cross_patterns = self.get_learned_patterns(
            file_category=file_category,
            language=language,
            min_confidence=0.6,
        )

        # Calculate weighted stats from raw feedback
        weighted_stats = self._compute_weighted_stats(file_category, language)

        # Build layered prompt
        layers = []

        if weighted_stats:
            layers.append(self._build_suppressed_layer(weighted_stats))
            layers.append(self._build_priority_layer(weighted_stats))
            layers.append(self._build_conditional_layer(weighted_stats))

        if not layers:
            # Fallback: simple text
            return self._build_fallback_prompt(
                file_category, project_dismissed, project_high_accuracy, cross_patterns
            )

        header = f"## Adaptive Review Guidelines (Learned from {sum(s['evidence'] for s in weighted_stats)} reviews across projects)\n"
        return header + "\n".join(layers)

    def _compute_weighted_stats(self, file_category: str, language: str) -> list[dict]:
        """Compute time-weighted stats per issue type for a given category.

        Applies exponential time decay: weight = 0.5^(age_days / half_life).
        Older feedback contributes less to the final confidence score.
        """
        patterns = self.get_learned_patterns(
            file_category=file_category, language=language, min_confidence=0.0
        )

        now = datetime.now()
        results = []

        for p in patterns:
            # Time decay
            try:
                updated = datetime.fromisoformat(p.updated_at)
                age_days = (now - updated).days
            except (ValueError, TypeError):
                age_days = 0
            decay = 0.5 ** (age_days / self.DECAY_HALF_LIFE_DAYS)
            weighted_evidence = p.evidence_count * decay

            results.append({
                "issue_type": p.issue_type,
                "confidence": p.confidence,
                "evidence": p.evidence_count,
                "weighted_evidence": weighted_evidence,
                "accepted": p.accepted_count,
                "dismissed": p.dismissed_count,
                "reason": p.reason,
                "is_false_positive": p.is_false_positive,
            })

        return sorted(results, key=lambda x: x["weighted_evidence"], reverse=True)

    def _build_suppressed_layer(self, stats: list[dict]) -> str:
        """Build the 'suppressed patterns' layer of the prompt."""
        suppressed = [
            s for s in stats
            if s["confidence"] >= 0.7 and s["dismissed"] >= 2
        ]
        if not suppressed:
            return ""

        lines = ["### Suppressed Patterns (high confidence — do not report without strong evidence)"]
        for s in suppressed:
            fp_pct = s["dismissed"] / (s["accepted"] + s["dismissed"]) if (s["accepted"] + s["dismissed"]) > 0 else 0
            lines.append(f"- `{s['issue_type']}` — dismissed {s['dismissed']}/{s['accepted'] + s['dismissed']} times ({fp_pct:.0%} FP rate)")
            if s["reason"]:
                lines.append(f"  → Reason: {s['reason']}")
            lines.append(f"  → Only report if there is clear, concrete evidence of a real issue")
        lines.append("")
        return "\n".join(lines)

    def _build_priority_layer(self, stats: list[dict]) -> str:
        """Build the 'priority checks' layer of the prompt."""
        priorities = [
            s for s in stats
            if s["confidence"] < 0.35 and s["accepted"] >= 2
        ]
        if not priorities:
            return ""

        lines = ["### Priority Checks (high confidence — report aggressively)"]
        for s in priorities:
            accept_pct = s["accepted"] / (s["accepted"] + s["dismissed"]) if (s["accepted"] + s["dismissed"]) > 0 else 0
            lines.append(f"- `{s['issue_type']}` — accepted {s['accepted']}/{s['accepted'] + s['dismissed']} times ({accept_pct:.0%} accuracy)")
            lines.append(f"  → Report confidently with specific details")
        lines.append("")
        return "\n".join(lines)

    def _build_conditional_layer(self, stats: list[dict]) -> str:
        """Build the 'conditional checks' layer (medium confidence)."""
        conditional = [
            s for s in stats
            if 0.35 <= s["confidence"] < 0.7 and s["evidence"] >= 2
        ]
        if not conditional:
            return ""

        lines = ["### Conditional Checks (medium confidence — apply context-dependent judgment)"]
        for s in conditional:
            fp_pct = s["dismissed"] / (s["accepted"] + s["dismissed"]) if (s["accepted"] + s["dismissed"]) > 0 else 0
            lines.append(f"- `{s['issue_type']}` — {s['accepted']}/{s['accepted'] + s['dismissed']} accepted ({fp_pct:.0%} FP rate)")
            if s["reason"]:
                lines.append(f"  → Reason: {s['reason']}")
            lines.append(f"  → Distinguish between true issues and framework conventions before reporting")
        lines.append("")
        return "\n".join(lines)

    def _build_fallback_prompt(
        self,
        file_category: str,
        project_dismissed: list[str],
        project_high_accuracy: list[str],
        cross_patterns: list[LearnedPattern],
    ) -> str:
        """Build a simple fallback prompt when weighted stats are empty."""
        lines = []

        if project_dismissed or cross_patterns:
            lines.append("## Historical False Positives (suppress these)")
            lines.append("The following issue types have been frequently marked as false positives")
            lines.append("in similar files. Be more strict before reporting them:")
            seen = set()
            for itype in project_dismissed:
                lines.append(f"- `{itype}` — only report with strong evidence")
                seen.add(itype)
            for p in cross_patterns:
                if p.issue_type not in seen and p.is_false_positive:
                    lines.append(f"- `{p.issue_type}` (cross-project: {p.confidence:.0%} FP confidence)")
                    seen.add(p.issue_type)
            lines.append("")

        if project_high_accuracy:
            lines.append("## Historically Accurate Checks (prioritize these)")
            lines.append("The following issue types are consistently accurate in this project:")
            for itype in project_high_accuracy:
                lines.append(f"- `{itype}` — report confidently")
            lines.append("")

        return "\n".join(lines)

    # ── Export / Import (Cross-Project Sharing) ─────────────────────────

    def export_knowledge(self) -> dict:
        """Export all learned patterns as JSON-serializable dict."""
        patterns = self.get_learned_patterns()
        stats = self.get_stats()
        return {
            "version": 1,
            "exported_at": datetime.now().isoformat(),
            "learned_patterns": [
                {
                    "issue_type": p.issue_type,
                    "file_category": p.file_category,
                    "language": p.language,
                    "confidence": p.confidence,
                    "evidence_count": p.evidence_count,
                    "accepted_count": p.accepted_count,
                    "dismissed_count": p.dismissed_count,
                    "reason": p.reason,
                }
                for p in patterns
            ],
            "stats": {
                "total_reviews": stats.total_reviews,
                "acceptance_rate": round(stats.acceptance_rate, 3),
                "false_positive_rate": round(stats.false_positive_rate, 3),
            },
        }

    def import_knowledge(self, data: dict) -> int:
        """Import learned patterns from exported data.

        Merges with existing patterns using confidence-weighted averaging.

        Args:
            data: Exported knowledge dict.

        Returns:
            Number of patterns imported.
        """
        imported = 0
        patterns = data.get("learned_patterns", [])

        with sqlite3.connect(self.db_path) as conn:
            for p in patterns:
                # Check if pattern already exists
                existing = conn.execute(
                    "SELECT confidence, evidence_count, accepted_count, dismissed_count FROM learned_patterns WHERE issue_type = ? AND file_category = ? AND language = ?",
                    (p["issue_type"], p["file_category"], p.get("language", "")),
                ).fetchone()

                if existing:
                    # Merge: weighted average by evidence count
                    old_conf, old_ev, old_acc, old_dis = existing
                    new_conf = p["confidence"]
                    new_ev = p["evidence_count"]
                    merged_conf = (old_conf * old_ev + new_conf * new_ev) / (old_ev + new_ev) if (old_ev + new_ev) > 0 else new_conf
                    merged_ev = old_ev + new_ev
                    merged_acc = old_acc + p["accepted_count"]
                    merged_dis = old_dis + p["dismissed_count"]
                    is_fp = 1 if merged_dis > merged_acc * 2 else 0
                    reason = p.get("reason", "")

                    conn.execute(
                        """UPDATE learned_patterns SET confidence = ?, evidence_count = ?,
                           accepted_count = ?, dismissed_count = ?, is_false_positive = ?,
                           reason = ?, updated_at = ?
                           WHERE issue_type = ? AND file_category = ? AND language = ?""",
                        (round(merged_conf, 3), merged_ev, merged_acc, merged_dis, is_fp,
                         reason, datetime.now().isoformat(),
                         p["issue_type"], p["file_category"], p.get("language", "")),
                    )
                else:
                    conn.execute(
                        """INSERT INTO learned_patterns
                           (issue_type, file_category, language, is_false_positive, confidence,
                            evidence_count, accepted_count, dismissed_count, reason, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (p["issue_type"], p["file_category"], p.get("language", ""),
                         1 if p.get("confidence", 0) >= 0.7 else 0,
                         p["confidence"], p["evidence_count"],
                         p["accepted_count"], p["dismissed_count"],
                         p.get("reason", ""), datetime.now().isoformat()),
                    )
                imported += 1

            conn.commit()

        return imported

    def reset(self) -> None:
        """Clear all feedback and learned pattern data."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM feedback")
            conn.execute("DELETE FROM learned_patterns")
            conn.commit()
