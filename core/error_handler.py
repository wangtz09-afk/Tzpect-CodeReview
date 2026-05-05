"""Error handler for pipeline stages.

Provides user-friendly error messages and structured logging for
pipeline stage failures.
"""
import sys
import traceback

from utils.logger import log_review_stage, get_logger


def _safe_print(*args, **kwargs):
    """Print with fallback for non-UTF-8 console encodings (e.g. GBK on Windows)."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "ascii"
        safe_args = [
            str(a).encode(enc, errors="replace").decode(enc) if isinstance(a, str) else a
            for a in args
        ]
        print(*safe_args, **kwargs)


class StageErrorHandler:
    """Handles errors from pipeline stages with user-friendly output."""

    def __init__(self, stage_timeout: float = 300.0):
        self.stage_timeout = stage_timeout
        self.logger = get_logger("error_handler")

    def handle(self, stage: str, error: Exception, result, context: dict = None) -> None:
        """Handle a stage error gracefully.

        Args:
            stage: Stage name (e.g., "review", "fix", "test", "verify").
            error: The exception that occurred.
            result: PipelineResult to append the error to.
            context: Optional context dict for logging.
        """
        error_msg = f"[{stage}] {type(error).__name__}: {error}"
        result.errors.append(error_msg)

        # Log detailed traceback
        self.logger.error(
            f"Stage {stage} failed: {error}\n"
            f"Traceback:\n{traceback.format_exc()}"
        )

        # Log to structured log
        log_review_stage(f"{stage}_failed", result.file_path, {
            "error": str(error),
            "type": type(error).__name__,
            "context": context or {},
        })

        # Print user-friendly message
        error_type = type(error).__name__
        if error_type == "APIError":
            status_code = getattr(error, "status_code", 0)
            if status_code == 401:
                _safe_print(f"    ✗ API认证失败 — 请检查 API Key")
            elif status_code == 429:
                _safe_print(f"    ✗ API 速率限制 — 请稍后重试")
            else:
                _safe_print(f"    ✗ API 错误 ({status_code}): {error}")
        elif error_type == "TimeoutError":
            _safe_print(f"    ✗ {stage} 超时 (>{self.stage_timeout}s) — 跳过此阶段")
        else:
            _safe_print(f"    ✗ {stage} 失败: {error}")
