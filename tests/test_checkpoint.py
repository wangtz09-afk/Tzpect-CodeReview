"""Tests for utils.checkpoint module."""
import json
import os
import tempfile
import pytest
from utils.checkpoint import CheckpointManager
from core.models import PipelineResult


class TestCheckpointManager:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.manager = CheckpointManager(self.tmpdir)

    def teardown_method(self):
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    def _make_result(self, file_path: str) -> PipelineResult:
        return PipelineResult(
            file_path=file_path,
            language="python",
            review_result={"overall_quality": "good", "issues": []},
            fix_code="def fixed(): pass",
            test_result={"passed": True},
            verification={"final_decision": "Approve"},
            total_tokens=1000,
            stages=["review", "fix", "verify"],
            errors=[],
            fix_iterations=1,
            elapsed_seconds=10.0,
        )

    def test_save_and_load_result(self):
        result = self._make_result("test.py")
        self.manager.save_result(result)

        loaded = self.manager.load_all_results()
        assert len(loaded) == 1
        assert loaded[0].file_path == "test.py"
        assert loaded[0].total_tokens == 1000

    def test_is_completed(self):
        result = self._make_result("test.py")
        self.manager.save_result(result)

        assert self.manager.is_completed("test.py") is True
        assert self.manager.is_completed("other.py") is False

    def test_get_completed_files(self):
        self.manager.save_result(self._make_result("a.py"))
        self.manager.save_result(self._make_result("b.py"))

        completed = self.manager.get_completed_files()
        assert len(completed) == 2
        assert "a.py" in completed
        assert "b.py" in completed

    def test_save_metadata(self):
        self.manager.save_metadata(total_files=5, branch="main")
        info = self.manager.get_session_info()
        assert info["metadata"]["total_files"] == 5
        assert info["metadata"]["branch"] == "main"

    def test_get_session_info(self):
        self.manager.save_metadata(total_files=3)
        self.manager.save_result(self._make_result("a.py"))
        self.manager.save_result(self._make_result("b.py"))

        info = self.manager.get_session_info()
        # total_files comes from metadata, completed_files from saved results
        assert info["completed_files"] == 2
        assert info["total_tokens"] == 2000
        assert info["metadata"]["total_files"] == 3

    def test_persistence(self):
        """Test that data persists across manager instances."""
        self.manager.save_result(self._make_result("test.py"))

        # Create new manager with same directory
        manager2 = CheckpointManager(self.tmpdir)
        # Load the session file from the original manager
        loaded = manager2.load_all_results()
        assert len(loaded) == 1
        assert loaded[0].file_path == "test.py"

    def test_multiple_results(self):
        for i in range(10):
            result = self._make_result(f"file{i}.py")
            result.total_tokens = i * 100
            self.manager.save_result(result)

        loaded = self.manager.load_all_results()
        assert len(loaded) == 10

    def test_clear(self):
        self.manager.save_result(self._make_result("test.py"))
        self.manager.clear()
        assert os.path.exists(self.manager.session_file) is False

    def test_checkpoint_file_format(self):
        self.manager.save_result(self._make_result("test.py"))

        with open(self.manager.session_file, "r") as f:
            data = json.load(f)

        assert "session_id" in data
        assert "files" in data
        assert "test.py" in data["files"]
        assert data["files"]["test.py"]["total_tokens"] == 1000
