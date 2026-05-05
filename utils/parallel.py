"""Parallel processing for file reviews.

Uses ThreadPoolExecutor with dynamic load balancing, progress callbacks,
rate limiting, and checkpointing.
"""
import concurrent.futures
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Optional

from core.pipeline import ReviewPipeline, PipelineResult
from core.git_ops import CodeChange, ReviewContext
from utils.checkpoint import CheckpointManager
from utils.cost_tracker import CostTracker
from utils.rate_limiter import RateLimiter
from utils.logger import get_logger


class ParallelReviewer:
    """Reviews files in parallel with dynamic load balancing and checkpointing.

    Features:
    - Dynamic work distribution (faster files finish first, no idle workers)
    - Progress callbacks for real-time dashboard updates
    - Priority queue (critical/high severity files first)
    - Graceful shutdown on budget exceeded
    """

    def __init__(
        self,
        max_workers: int = 3,
        rate_limiter: Optional[RateLimiter] = None,
        checkpoint_manager: Optional[CheckpointManager] = None,
        cost_tracker: Optional[CostTracker] = None,
        on_progress: Optional[Callable] = None,
    ):
        self.max_workers = max_workers
        self.rate_limiter = rate_limiter or RateLimiter()
        self.checkpoint_manager = checkpoint_manager
        self.cost_tracker = cost_tracker
        self.on_progress = on_progress
        self.logger = get_logger("parallel")
        self._stop_requested = False

    def process_files(
        self,
        context: ReviewContext,
        pipeline_factory: Callable[[], ReviewPipeline] = ReviewPipeline,
    ) -> list[PipelineResult]:
        """Process all files in parallel with dynamic load balancing.

        Args:
            context: ReviewContext with all file changes.
            pipeline_factory: Factory function to create ReviewPipeline instances
                            (each thread gets its own pipeline).

        Returns:
            List of PipelineResult in original order.
        """
        changes = context.changes
        total = len(changes)

        # Check for completed files (resume from checkpoint)
        pending = changes
        if self.checkpoint_manager:
            completed = self.checkpoint_manager.get_completed_files()
            pending = [c for c in changes if c.file_path not in completed]
            self.logger.info(
                f"Resume: {len(completed)} completed, {len(pending)} pending "
                f"out of {total} total"
            )

        if not pending:
            return self.checkpoint_manager.load_all_results() if self.checkpoint_manager else []

        # Sort by priority: critical files first
        sorted_pending = self._sort_by_priority(pending)

        results: dict[str, PipelineResult] = {}
        errors: dict[str, str] = {}

        self.logger.info(
            f"Starting parallel review: {len(sorted_pending)} files, "
            f"{self.max_workers} workers"
        )

        start_time = time.time()

        with ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="review",
        ) as executor:
            # Submit files in priority order
            future_to_file: dict[Future, CodeChange] = {}
            submitted = 0

            for change in sorted_pending:
                if self._stop_requested:
                    break

                # Rate limit before submitting
                self.rate_limiter.acquire_call()

                future = executor.submit(
                    self._process_single, change, pipeline_factory, context.commit_message
                )
                future_to_file[future] = change
                submitted += 1

                # Notify progress callback
                if self.on_progress:
                    self.on_progress(change.file_path, change.language, "reviewing")

            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_file):
                if self._stop_requested:
                    break

                change = future_to_file[future]
                try:
                    result = future.result()
                    results[change.file_path] = result

                    if self.on_progress:
                        self.on_progress(
                            change.file_path, change.language, "complete",
                            issues=len(result.review_result.get("issues", [])),
                            tokens=result.total_tokens,
                            elapsed=result.elapsed_seconds,
                        )

                    self.logger.info(
                        f"Completed [{change.file_path}]: "
                        f"{len(result.review_result.get('issues', []))} issues, "
                        f"{result.total_tokens} tokens"
                    )

                    # Check budget
                    if self.cost_tracker and self.cost_tracker.is_over_budget():
                        self.logger.warning("Budget exceeded — stopping early")
                        self._stop_requested = True

                except Exception as e:
                    errors[change.file_path] = str(e)
                    if self.on_progress:
                        self.on_progress(change.file_path, change.language, "error", error=str(e))
                    self.logger.error(f"Failed [{change.file_path}]: {e}")

        elapsed = time.time() - start_time
        self.logger.info(
            f"All files processed: {len(results)} success, {len(errors)} errors, "
            f"{elapsed:.1f}s"
        )

        # Build results in original order
        all_results = self._build_results(changes, results, errors)
        return all_results

    def _sort_by_priority(self, changes: list[CodeChange]) -> list[CodeChange]:
        """Sort changes by priority. Larger files first for better load balancing."""
        # Priority: longer files first (gives better load distribution)
        return sorted(changes, key=lambda c: len(c.content), reverse=True)

    def _build_results(
        self,
        changes: list[CodeChange],
        results: dict[str, PipelineResult],
        errors: dict[str, str],
    ) -> list[PipelineResult]:
        """Build final results list in original order."""
        all_results = []
        for change in changes:
            if change.file_path in results:
                all_results.append(results[change.file_path])
            elif self.checkpoint_manager and self.checkpoint_manager.is_completed(change.file_path):
                saved = self.checkpoint_manager.load_all_results()
                saved_result = next(
                    (r for r in saved if r.file_path == change.file_path), None
                )
                if saved_result:
                    all_results.append(saved_result)

        # Add failed files as error results
        for file_path, error in errors.items():
            change = next((c for c in changes if c.file_path == file_path), None)
            if change:
                all_results.append(PipelineResult(
                    file_path=file_path,
                    language=change.language,
                    errors=[error],
                ))

        return all_results

    def _process_single(
        self,
        change: CodeChange,
        pipeline_factory: Callable,
        commit_message: str,
    ) -> PipelineResult:
        """Process a single file review."""
        # Each thread creates its own pipeline instance
        pipeline = pipeline_factory()
        result = pipeline.process_file(change, commit_message=commit_message)

        # Save to checkpoint
        if self.checkpoint_manager:
            self.checkpoint_manager.save_result(result)

        # Track cost
        if self.cost_tracker:
            for stage in result.stages:
                # Approximate per-stage token usage
                stage_tokens = result.total_tokens // max(len(result.stages), 1)
                self.cost_tracker.record_stage(
                    change.file_path, stage, stage_tokens
                )

        return result

    def stop(self) -> None:
        """Request graceful shutdown."""
        self._stop_requested = True
        self.logger.info("Stop requested — finishing current files")


def process_files_sequential(
    context: ReviewContext,
    pipeline_factory: Callable[[], ReviewPipeline] = ReviewPipeline,
    on_progress: Optional[Callable] = None,
) -> list[PipelineResult]:
    """Process files sequentially (fallback for single-threaded mode).

    Args:
        context: ReviewContext with all file changes.
        pipeline_factory: Factory function to create ReviewPipeline instances.
        on_progress: Optional callback called for each file progress update.

    Returns:
        List of PipelineResult in original order.
    """
    pipeline = pipeline_factory()
    results = []

    for i, change in enumerate(context.changes):
        if on_progress:
            on_progress(change.file_path, change.language, "reviewing", index=i, total=len(context.changes))

        result = pipeline.process_file(change, commit_message=context.commit_message)
        results.append(result)

        if on_progress:
            on_progress(
                change.file_path, change.language, "complete",
                issues=len(result.review_result.get("issues", [])),
                tokens=result.total_tokens,
                elapsed=result.elapsed_seconds,
                index=i,
                total=len(context.changes),
            )

    return results
