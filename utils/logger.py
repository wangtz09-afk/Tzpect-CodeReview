"""Structured logging with file rotation, API call tracking, and sensitive data sanitization."""
import json
import logging
import os
import re
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_log_dir: Optional[Path] = None
_logger: Optional[logging.Logger] = None

# ── Sensitive Data Patterns ──────────────────────────────────────────────────
# These patterns are scrubbed from all log output to prevent credential leaks.
_SENSITIVE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # API keys (various formats)
    (re.compile(r'(Bearer\s+)[A-Za-z0-9_\-.]+', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(sk-[A-Za-z0-9]{20,})'), '[REDACTED]'),
    (re.compile(r'(AK[A-Za-z0-9]{16,})'), '[REDACTED]'),
    # Common env var assignments in logs
    (re.compile(r'((?:API_KEY|SECRET|TOKEN|PASSWORD)\s*[=:]\s*)[^\s,}"\']+', re.IGNORECASE), r'\1[REDACTED]'),
    # Authorization headers
    (re.compile(r'("Authorization"\s*:\s*")[^"]+', re.IGNORECASE), r'\1[REDACTED]'),
]


def sanitize(text: str) -> str:
    """Remove sensitive data from a string before logging.

    Scraps API keys (sk-*, Bearer tokens), secrets, passwords, and
    authorization headers from log output.

    Args:
        text: Raw text that may contain sensitive data.

    Returns:
        Sanitized text safe for logging.
    """
    if not isinstance(text, str):
        return text
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def sanitize_dict(data: dict) -> dict:
    """Recursively sanitize all string values in a dict."""
    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = sanitize(value)
        elif isinstance(value, dict):
            result[key] = sanitize_dict(value)
        elif isinstance(value, list):
            result[key] = [
                sanitize(v) if isinstance(v, str) else
                sanitize_dict(v) if isinstance(v, dict) else v
                for v in value
            ]
        else:
            result[key] = value
    return result


def _get_log_dir() -> Path:
    global _log_dir
    if _log_dir is None:
        _log_dir = Path(__file__).parent.parent / ".code_review_logs"
        _log_dir.mkdir(exist_ok=True)
    return _log_dir


def get_logger(name: str = "code_review") -> logging.Logger:
    """Get the application logger with console + file handlers."""
    global _logger
    if _logger is not None:
        return _logger

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Console handler (INFO and above)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(console)

    # File handler (DEBUG and above, with rotation)
    log_dir = _get_log_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"review_{timestamp}.log"

    file_handler = RotatingFileHandler(
        str(log_file),
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(file_handler)

    _logger = logger
    return logger


def log_api_call(
    agent: str,
    model: str,
    tokens_used: int,
    duration_seconds: float,
    success: bool,
    error: str = "",
) -> None:
    """Log an API call with structured details. Sensitive data is automatically scrubbed."""
    logger = get_logger("api")
    entry = sanitize_dict({
        "agent": agent,
        "model": model,
        "tokens": tokens_used,
        "duration_s": round(duration_seconds, 2),
        "success": success,
        "error": error[:200] if error else "",
        "timestamp": datetime.now().isoformat(),
    })
    if success:
        logger.debug(f"API call: {json.dumps(entry, ensure_ascii=False)}")
    else:
        logger.warning(f"API call failed: {json.dumps(entry, ensure_ascii=False)}")


def log_review_stage(stage: str, file_path: str, details: dict) -> None:
    """Log a review stage completion. Sensitive data is automatically scrubbed."""
    logger = get_logger("pipeline")
    details = sanitize_dict(details)
    details["stage"] = stage
    details["file"] = file_path
    logger.debug(f"Stage complete: {json.dumps(details, ensure_ascii=False)}")


def log_fix_applied(file_path: str, fix_chars: int, issues_fixed: int) -> None:
    """Log when a fix is applied to a file."""
    logger = get_logger("fixer")
    logger.info(f"Fix applied to {file_path}: {fix_chars} chars, {issues_fixed} issues")


def get_log_path() -> Optional[str]:
    """Return the path to the current log file, if any."""
    if _logger is None:
        return None
    for handler in _logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            return handler.baseFilename
    return None
