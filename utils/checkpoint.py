"""Checkpoint and resume for long-running reviews.

Saves progress per file so interrupted reviews can resume.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.models import PipelineResult


class CheckpointManager:
    """Manages review checkpoints for resume capability."""

    def __init__(self, checkpoint_dir: Optional[str] = None):
        if checkpoint_dir is None:
            checkpoint_dir = str(Path(__file__).parent.parent / ".checkpoints")
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_file = self.checkpoint_dir / f"session_{self.session_id}.json"

    def save_result(self, result: PipelineResult) -> None:
        """Save a completed file result to checkpoint."""
        data = self._load_session_data()
        file_key = result.file_path
        data["files"][file_key] = {
            "file_path": result.file_path,
            "language": result.language,
            "review_result": result.review_result,
            "fix_code": result.fix_code,
            "test_result": result.test_result,
            "verification": result.verification,
            "total_tokens": result.total_tokens,
            "stages": result.stages,
            "errors": result.errors,
            "fix_iterations": result.fix_iterations,
            "elapsed_seconds": round(result.elapsed_seconds, 2),
            "completed_at": datetime.now().isoformat(),
        }
        data["last_updated"] = datetime.now().isoformat()
        data["completed_count"] = len(data["files"])
        self._save_session_data(data)

    def is_completed(self, file_path: str) -> bool:
        """Check if a file has already been reviewed (in checkpoint)."""
        data = self._load_session_data()
        return file_path in data.get("files", {})

    def get_completed_files(self) -> set[str]:
        """Get set of already-completed file paths."""
        data = self._load_session_data()
        return set(data.get("files", {}).keys())

    def load_all_results(self) -> list[PipelineResult]:
        """Load all saved results from checkpoint."""
        data = self._load_session_data()
        results = []
        for file_key, file_data in data["files"].items():
            r = PipelineResult(
                file_path=file_data["file_path"],
                language=file_data["language"],
                review_result=file_data.get("review_result", {}),
                fix_code=file_data.get("fix_code", ""),
                test_result=file_data.get("test_result", {}),
                verification=file_data.get("verification", {}),
                total_tokens=file_data.get("total_tokens", 0),
                stages=file_data.get("stages", []),
                errors=file_data.get("errors", []),
                fix_iterations=file_data.get("fix_iterations", 0),
                elapsed_seconds=file_data.get("elapsed_seconds", 0.0),
            )
            results.append(r)
        return results

    def save_metadata(self, **kwargs) -> None:
        """Save session metadata."""
        data = self._load_session_data()
        data["metadata"].update(kwargs)
        data["metadata"]["last_saved"] = datetime.now().isoformat()
        self._save_session_data(data)

    def get_session_info(self) -> dict:
        """Get session summary info."""
        data = self._load_session_data()
        return {
            "session_id": self.session_id,
            "total_files": data.get("metadata", {}).get("total_files", 0),
            "completed_files": data.get("completed_count", 0),
            "total_tokens": sum(
                f.get("total_tokens", 0) for f in data.get("files", {}).values()
            ),
            "last_updated": data.get("last_updated"),
            "metadata": data.get("metadata", {}),
        }

    def _load_session_data(self) -> dict:
        if self.session_file.exists():
            with open(self.session_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "session_id": self.session_id,
            "created_at": datetime.now().isoformat(),
            "last_updated": None,
            "total_files": 0,
            "completed_count": 0,
            "files": {},
            "metadata": {},
        }

    def _save_session_data(self, data: dict) -> None:
        with open(self.session_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def clear(self) -> None:
        """Clear all checkpoint data."""
        if self.session_file.exists():
            self.session_file.unlink()
