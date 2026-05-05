"""Review context builder — initializes and builds enhanced context for code review.

Handles project context detection, custom rules loading, cross-file analysis,
and feedback context integration.
"""
from typing import Optional

from core.git_ops import CodeChange
from agents.reviewer import ReviewContext as AgentReviewContext
from utils.logger import get_logger
from utils.project_context import detect_project_context
from utils.custom_rules import load_rules, to_prompt as rules_to_prompt, should_ignore
from utils.cross_file_analyzer import analyze_project
from utils.feedback_db import FeedbackDB


class ReviewContextBuilder:
    """Builds enhanced review context from optional components.

    Manages three initialization phases:
    1. Project context detection (frameworks, patterns)
    2. Custom rules loading (.codereview.yml)
    3. Cross-file analysis (interfaces, inheritance, dependencies)
    4. Feedback learning (historical accuracy)
    """

    def __init__(
        self,
        repo_path: str = "",
        enable_context: bool = True,
        enable_custom_rules: bool = True,
        enable_cross_file: bool = True,
        enable_feedback: bool = True,
    ):
        self.repo_path = repo_path
        self.enable_context = enable_context
        self.enable_custom_rules = enable_custom_rules
        self.enable_cross_file = enable_cross_file
        self.enable_feedback = enable_feedback
        self.logger = get_logger("context_builder")

        # Optional components
        self.project_context = None
        self.rule_config = None
        self.project_graph = None
        self.feedback_db = None

    def initialize(self, all_changes: list[CodeChange] = None) -> None:
        """Initialize all optional components once per pipeline run."""
        if not self.repo_path:
            return

        # Phase 1: Project context detection
        if self.enable_context and all_changes:
            try:
                self.project_context = detect_project_context(self.repo_path)
                self.logger.info(
                    f"Project context: {len(self.project_context.frameworks)} frameworks detected"
                )
            except Exception as e:
                self.logger.warning(f"Failed to detect project context: {e}")

        # Phase 2: Load custom rules
        if self.enable_custom_rules:
            try:
                self.rule_config = load_rules(self.repo_path)
                self.logger.info(
                    f"Custom rules: {len(self.rule_config.rules)} rules, "
                    f"{len(self.rule_config.ignore_patterns)} ignore patterns"
                )
            except Exception as e:
                self.logger.warning(f"Failed to load custom rules: {e}")

        # Phase 3: Cross-file analysis
        if self.enable_cross_file and all_changes:
            try:
                file_paths = [c.file_path for c in all_changes if c.content]
                if len(file_paths) > 1:
                    self.project_graph = analyze_project(self.repo_path, file_paths)
                    self.logger.info(
                        f"Cross-file analysis: {len(self.project_graph.files)} files, "
                        f"{len(self.project_graph.issues)} cross-file issues"
                    )
            except Exception as e:
                self.logger.warning(f"Failed to analyze cross-file: {e}")

        # Phase 4: Feedback learning
        if self.enable_feedback:
            try:
                self.feedback_db = FeedbackDB()
            except Exception:
                self.feedback_db = None

    def should_ignore(self, file_path: str) -> bool:
        """Check if a file should be ignored based on custom rules."""
        if self.rule_config:
            return should_ignore(file_path, self.rule_config)
        return False

    def build_for_file(
        self, change: CodeChange, result: "PipelineResult" = None
    ) -> AgentReviewContext:
        """Build enhanced review context for a specific file."""
        from core.models import PipelineResult as _PR
        ctx = AgentReviewContext()

        # Phase 1: Project context
        if self.project_context:
            ctx.project_context = self.project_context.to_prompt()
            if result:
                result.project_frameworks = [fw.name for fw in self.project_context.frameworks]

        # Phase 2: Custom rules
        if self.rule_config:
            ctx.custom_rules = rules_to_prompt(self.rule_config, change.language)

        # Phase 3: Cross-file context
        if self.project_graph:
            ctx.cross_file_context = self.project_graph.to_context_prompt(change.file_path)

        # Phase 5: Feedback context
        if self.feedback_db:
            ctx.feedback_context = self.feedback_db.get_feedback_for_prompt(change.file_path)

        return ctx
