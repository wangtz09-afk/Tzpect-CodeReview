"""Pipeline — 编排多 Agent 协作的审查流程。"""
import json
import time
from dataclasses import dataclass, field
from typing import Optional

from core.git_ops import CodeChange, ReviewContext
from core.models import (
    PipelineError, StageError, ConfigurationError, APIError,
    PipelineResult, FixAnalysis,
)
from core.context_builder import ReviewContextBuilder
from core.error_handler import StageErrorHandler, _safe_print
from agents.reviewer import ReviewerAgent, ReviewContext as AgentReviewContext
from agents.fixer import FixerAgent
from agents.tester import TesterAgent
from agents.verifier import VerifierAgent
from agents.base import AgentResult
from utils.logger import log_api_call, log_review_stage, get_logger
from utils.fix_verifier import FixVerifier
from utils.fix_quality import assess_fix_quality
from utils.custom_rules import is_auto_suppressed


class ReviewPipeline:
    """
    多 Agent 协作的代码审查流水线。

    流程：Reviewer → (若需要修复，最多迭代 2 轮) Fixer → Reviewer → FixVerifier → Tester → Verifier

    增强功能:
    - 项目上下文感知（框架检测、模式识别）
    - 自定义规则（.codereview.yml）
    - 跨文件分析（接口、继承、依赖）
    - 修复质量评估（语法、结构、测试）
    - 反馈学习（历史误报调整）
    """

    MAX_FIX_ITERATIONS = 2

    def __init__(
        self,
        stage_timeout: float = 300.0,
        retry_on_failure: bool = True,
        repo_path: str = "",
        enable_context: bool = True,
        enable_custom_rules: bool = True,
        enable_cross_file: bool = True,
        enable_fix_quality: bool = True,
        enable_feedback: bool = True,
        incremental: bool = False,
    ):
        self.reviewer = ReviewerAgent()
        self.fixer = FixerAgent()
        self.tester = TesterAgent()
        self.verifier = VerifierAgent()
        self.fix_verifier = FixVerifier()
        self.logger = get_logger("pipeline")
        self.stage_timeout = stage_timeout
        self.retry_on_failure = retry_on_failure
        self.repo_path = repo_path
        self.incremental = incremental

        # Feature flags
        self.enable_context = enable_context
        self.enable_custom_rules = enable_custom_rules
        self.enable_cross_file = enable_cross_file
        self.enable_fix_quality = enable_fix_quality
        self.enable_feedback = enable_feedback

        # Delegate components
        self.context_builder = ReviewContextBuilder(
            repo_path=repo_path,
            enable_context=enable_context,
            enable_custom_rules=enable_custom_rules,
            enable_cross_file=enable_cross_file,
            enable_feedback=enable_feedback,
        )
        self.error_handler = StageErrorHandler(stage_timeout=stage_timeout)

    def initialize(self, all_changes: list[CodeChange] = None) -> None:
        """Initialize all optional components once per pipeline run."""
        self.context_builder.initialize(all_changes)

    def should_ignore(self, file_path: str) -> bool:
        """Check if a file should be ignored based on custom rules."""
        return self.context_builder.should_ignore(file_path)

    def process_file(self, change: CodeChange, commit_message: str = "") -> PipelineResult:
        """
        对一个文件的变更执行完整的审查流程。

        Args:
            change: CodeChange 对象，包含文件路径、diff、内容等。
            commit_message: Git 提交信息。

        Returns:
            PipelineResult 包含所有阶段的输出。
        """
        start_time = time.time()
        result = PipelineResult(
            file_path=change.file_path,
            language=change.language,
        )

        try:
            return self._process_file_impl(change, commit_message, result, start_time)
        except Exception as e:
            self.error_handler.handle("pipeline", e, result)
            result.elapsed_seconds = time.time() - start_time
            return result

    def _process_file_impl(self, change: CodeChange, commit_message: str, result: PipelineResult, start_time: float) -> PipelineResult:
        """Internal implementation of process_file."""
        # Build enhanced review context
        review_ctx = self.context_builder.build_for_file(change, result)

        # ========== Stage 1: Initial Review ==========
        try:
            result = self._run_review(change, commit_message, result, review_ctx=review_ctx)
        except Exception as e:
            self.error_handler.handle("review", e, result)
            result.elapsed_seconds = time.time() - start_time
            return result

        parsed = result.review_result
        issues = parsed.get("issues", [])

        # Apply auto-suppression from feedback learning
        if self.context_builder.rule_config and self.context_builder.feedback_db:
            file_category = ""
            if self.context_builder.feedback_db:
                file_category = self.context_builder.feedback_db.normalize_path(change.file_path)
            if file_category:
                original_count = len(issues)
                issues = [
                    issue for issue in issues
                    if not is_auto_suppressed(issue.get("type", ""), file_category, self.context_builder.rule_config)
                ]
                suppressed = original_count - len(issues)
                if suppressed > 0:
                    parsed["issues"] = issues
                    _safe_print(f"    [dim]Auto-suppressed {suppressed} issue(s) via feedback learning[/dim]")
                    log_review_stage("auto_suppress", change.file_path, {"suppressed": suppressed})

        # If clean code, skip all remaining stages
        if parsed.get("approved") and not issues:
            result.elapsed_seconds = time.time() - start_time
            log_review_stage("review_complete", change.file_path, {
                "quality": parsed.get("overall_quality"),
                "issues": 0,
                "approved": True,
            })
            return result

        # ========== Stage 2: Iterative Fix-Review Loop ==========
        current_content = change.content
        iteration = 0
        while issues and iteration < self.MAX_FIX_ITERATIONS:
            iteration += 1
            result.fix_iterations = iteration
            _safe_print(f"    [Fix Round {iteration}] Fixer generating fixes...")
            self.logger.info(f"[{change.file_path}] Fix round {iteration}")

            t0 = time.time()
            fix_result: AgentResult = self.fixer.run(
                file_path=change.file_path,
                language=change.language,
                content=current_content,
                diff=change.diff,
                issues=issues,
            )
            duration = time.time() - t0

            result.stages.append(f"fix_{iteration}")
            result.total_tokens += fix_result.metadata.get("tokens_used", 0)

            log_api_call(
                agent="FixerAgent",
                model=fix_result.metadata.get("model", "unknown"),
                tokens_used=fix_result.metadata.get("tokens_used", 0),
                duration_seconds=duration,
                success=fix_result.success,
                error=fix_result.error,
            )

            if not fix_result.success:
                _safe_print(f"    [x] Fixer failed: {fix_result.error}")
                result.errors.append(fix_result.error)
                self.logger.warning(f"[{change.file_path}] Fixer failed: {fix_result.error}")
                break

            fixed_code = self.fixer.extract_code(fix_result)
            if not fixed_code:
                _safe_print(f"    [x] Fixer did not produce valid code")
                break

            # ========== Fix Verification ==========
            fix_analysis = self.fix_verifier.verify_fix(
                original_code=change.content,
                fixed_code=fixed_code,
                language=change.language,
                original_issues=issues,
            )
            result.fix_analysis = fix_analysis

            # ========== Fix Quality Assessment (Phase 4) ==========
            fix_quality_report = None
            if self.enable_fix_quality and self.repo_path:
                try:
                    fix_quality_report = assess_fix_quality(
                        original_code=change.content,
                        fixed_code=fixed_code,
                        language=change.language,
                        file_path=change.file_path,
                        repo_path=self.repo_path,
                        run_tests=False,  # Skip tests during fix loop (too slow)
                    )
                    result.fix_quality_score = fix_quality_report.overall_score
                except Exception as e:
                    self.logger.warning(f"Fix quality assessment failed: {e}")

            if not fix_analysis.is_valid:
                _safe_print(f"    [!] Fix verification failed — possible new issues:")
                for fi in fix_analysis.issues:
                    print(f"      [{fi.severity.upper()}] {fi.description}")
                self.logger.warning(
                    f"[{change.file_path}] Fix verification failed: "
                    f"{len(fix_analysis.issues)} issues"
                )

            result.fix_code = fixed_code
            _safe_print(f"    [+] Fix generated ({len(fixed_code)} chars) | Token: {fix_result.metadata.get('tokens_used', 0)}"
                  + (f" | Verify: [!]" if not fix_analysis.is_valid else f" | Verify: [ok]"))

            # If this is the last iteration, skip re-review
            if iteration >= self.MAX_FIX_ITERATIONS:
                break

            # Re-review the fixed code to verify issues are resolved
            _safe_print(f"    [Fix Round {iteration}] Reviewer re-reviewing fixes...")
            re_change = CodeChange(
                file_path=change.file_path,
                status=change.status,
                diff=change.diff,
                content=fixed_code,
                language=change.language,
            )
            result = self._run_review(re_change, commit_message, result, is_rereview=True)
            remaining_issues = result.review_result.get("issues", [])
            if not remaining_issues:
                _safe_print(f"    [ok] Re-review passed — all issues resolved!")
                self.logger.info(f"[{change.file_path}] All issues resolved after fix round {iteration}")
                break
            else:
                _safe_print(f"    [!] Re-review found {len(remaining_issues)} remaining issues, continuing fix...")
                issues = remaining_issues
                current_content = fixed_code

        # ========== Stage 3: Test (if fix was generated) ==========
        if result.fix_code:
            result = self._run_test(change, result)

        # ========== Stage 4: Verify ==========
        result = self._run_verify(change, result)

        result.elapsed_seconds = time.time() - start_time
        log_review_stage("file_complete", change.file_path, {
            "issues": len(result.review_result.get("issues", [])),
            "fix_iterations": result.fix_iterations,
            "fix_valid": result.fix_analysis.is_valid if result.fix_code else None,
            "total_tokens": result.total_tokens,
            "elapsed_s": round(result.elapsed_seconds, 2),
        })

        print(f"    Total tokens: {result.total_tokens} | Time: {result.elapsed_seconds:.1f}s")
        return result

    def _run_review(
        self,
        change: CodeChange,
        commit_message: str,
        result: PipelineResult,
        is_rereview: bool = False,
        review_ctx: AgentReviewContext = None,
    ) -> PipelineResult:
        """Run the Reviewer Agent and parse results."""
        label = "Re-review" if is_rereview else "Review"
        if is_rereview:
            _safe_print(f"    Reviewer re-reviewing...")

        t0 = time.time()
        review_result: AgentResult = self.reviewer.run(
            file_path=change.file_path,
            language=change.language,
            diff=change.diff,
            content=change.content,
            commit_message=commit_message,
            review_context=review_ctx,
            incremental=self.incremental,
        )
        duration = time.time() - t0

        if not is_rereview:
            result.stages.append("review")
        else:
            result.stages.append("re-review")
        result.total_tokens += review_result.metadata.get("tokens_used", 0)

        log_api_call(
            agent="ReviewerAgent",
            model=review_result.metadata.get("model", "unknown"),
            tokens_used=review_result.metadata.get("tokens_used", 0),
            duration_seconds=duration,
            success=review_result.success,
            error=review_result.error,
        )

        if not review_result.success:
            err = f"Reviewer 失败: {review_result.error}"
            _safe_print(f"    [x] Reviewer failed: {review_result.error}")
            result.review_result = {"error": review_result.error, "issues": [], "overall_quality": "N/A"}
            result.errors.append(review_result.error)
            return result

        parsed = self.reviewer.parse_result(review_result)
        result.review_result = parsed
        issues = parsed.get("issues", [])
        quality = parsed.get("overall_quality", "N/A")
        status_icon = "[ok]" if issues else "[ok]"
        _safe_print(f"    {label} complete — quality: {quality} | issues: {len(issues)} | token: {review_result.metadata.get('tokens_used', 0)}")
        return result

    def _run_test(self, change: CodeChange, result: PipelineResult) -> PipelineResult:
        """Run the Tester Agent."""
        _safe_print(f"    Tester generating and running tests...")
        t0 = time.time()
        test_gen_result: AgentResult = self.tester.run(
            file_path=change.file_path,
            language=change.language,
            original_code=change.content,
            fixed_code=result.fix_code,
            issues=result.review_result.get("issues", []),
        )
        duration = time.time() - t0
        result.stages.append("test_gen")
        result.total_tokens += test_gen_result.metadata.get("tokens_used", 0)

        log_api_call(
            agent="TesterAgent",
            model=test_gen_result.metadata.get("model", "unknown"),
            tokens_used=test_gen_result.metadata.get("tokens_used", 0),
            duration_seconds=duration,
            success=test_gen_result.success,
            error=test_gen_result.error,
        )

        if test_gen_result.success:
            test_run_result = self.tester.run_tests(
                test_code=test_gen_result.output,
                file_path=change.file_path,
                language=change.language,
            )
            result.stages.append("test_run")
            result.test_result = test_run_result
            status = "PASS" if test_run_result.get("passed") else "FAIL"
            _safe_print(f"    Test {status} | Token: {test_gen_result.metadata.get('tokens_used', 0)}")
        else:
            _safe_print(f"    [x] Tester failed: {test_gen_result.error}")
            result.errors.append(test_gen_result.error)

        return result

    def _run_verify(self, change: CodeChange, result: PipelineResult) -> PipelineResult:
        """Run the Verifier Agent."""
        _safe_print(f"    Verifier making final decision...")
        t0 = time.time()
        verify_result: AgentResult = self.verifier.run(
            review_result=result.review_result,
            fix_code=result.fix_code,
            test_result=result.test_result,
            file_path=change.file_path,
            language=change.language,
            fix_iterations=result.fix_iterations,
        )
        duration = time.time() - t0
        result.stages.append("verify")
        result.total_tokens += verify_result.metadata.get("tokens_used", 0)

        log_api_call(
            agent="VerifierAgent",
            model=verify_result.metadata.get("model", "unknown"),
            tokens_used=verify_result.metadata.get("tokens_used", 0),
            duration_seconds=duration,
            success=verify_result.success,
            error=verify_result.error,
        )

        if verify_result.success:
            result.verification = self.verifier.parse_result(verify_result)
            decision = result.verification.get("final_decision", "未知")
            confidence = result.verification.get("confidence", "中")
            _safe_print(f"    Decision: {decision} (confidence: {confidence}) | Token: {verify_result.metadata.get('tokens_used', 0)}")
        else:
            _safe_print(f"    [x] Verifier failed: {verify_result.error}")
            result.errors.append(verify_result.error)

        return result

    def _validate_result(self, result: PipelineResult, stage: str) -> bool:
        """Validate that a stage produced valid results."""
        if stage == "review":
            return bool(result.review_result)
        elif stage == "fix":
            return bool(result.fix_code)
        elif stage == "test":
            return "passed" in result.test_result
        elif stage == "verify":
            return bool(result.verification)
        return True

    def process_context(
        self,
        context: ReviewContext,
        on_progress=None,
    ) -> list[PipelineResult]:
        """
        对整个上下文中的所有变更执行审查。

        Args:
            context: ReviewContext 包含所有文件变更。
            on_progress: Optional callback(file_path, language, event, **kwargs).

        Returns:
            所有文件的审查结果列表。
        """
        total_files = len(context.changes)
        print(f"\n{'='*60}")
        print(f"  Code Review Pipeline")
        print(f"  Files: {total_files} | Max fix iterations: {self.MAX_FIX_ITERATIONS}")
        print(f"{'='*60}")

        results = []
        for i, change in enumerate(context.changes):
            print(f"\n[{i+1}/{total_files}] Reviewing {change.file_path} ({change.language})")
            if on_progress:
                on_progress(change.file_path, change.language, "reviewing", index=i, total=total_files)
            file_start = time.time()
            result = self.process_file(change, commit_message=context.commit_message)
            elapsed = time.time() - file_start
            _safe_print(f"  → 文件耗时: {elapsed:.1f}s\n")
            if on_progress:
                on_progress(
                    change.file_path, change.language, "complete",
                    issues=len(result.review_result.get("issues", [])),
                    tokens=result.total_tokens,
                    elapsed=elapsed,
                    index=i, total=total_files,
                )
            results.append(result)

        # Summary
        total_tokens = sum(r.total_tokens for r in results)
        total_issues = sum(len(r.review_result.get("issues", [])) for r in results)
        total_time = sum(r.elapsed_seconds for r in results)
        total_fix_rounds = sum(r.fix_iterations for r in results)
        fix_valid = sum(1 for r in results if r.fix_code and r.fix_analysis.is_valid)
        fix_invalid = sum(1 for r in results if r.fix_code and not r.fix_analysis.is_valid)

        print(f"\n{'='*60}")
        print(f"  Pipeline complete")
        print(f"  Files: {len(results)} | Issues: {total_issues} | Token: {total_tokens:,} | Time: {total_time:.1f}s")
        print(f"  Fix rounds: {total_fix_rounds} | Passed: {fix_valid} | Warnings: {fix_invalid}")
        print(f"{'='*60}\n")

        return results
