"""Tests for utils.cost_tracker module."""
import pytest
from utils.cost_tracker import CostTracker


class TestCostTracker:
    def setup_method(self):
        self.tracker = CostTracker()

    def test_record_stage(self):
        self.tracker.record_stage("file.py", "review", 1000)
        assert self.tracker.get_total_tokens() == 1000

    def test_record_multiple_stages(self):
        self.tracker.record_stage("file.py", "review", 1000)
        self.tracker.record_stage("file.py", "fix", 500)
        self.tracker.record_stage("file.py", "verify", 300)
        assert self.tracker.get_total_tokens() == 1800

    def test_record_multiple_files(self):
        self.tracker.record_stage("file1.py", "review", 1000)
        self.tracker.record_stage("file2.py", "review", 2000)
        assert self.tracker.get_total_tokens() == 3000

    def test_get_file_cost(self):
        self.tracker.record_stage("file.py", "review", 1000)
        file_cost = self.tracker.get_file_cost("file.py")
        assert file_cost is not None
        assert file_cost.total_tokens == 1000
        assert len(file_cost.stages) == 1

    def test_get_file_cost_missing(self):
        assert self.tracker.get_file_cost("nonexistent.py") is None

    def test_cost_estimation(self):
        self.tracker.record_stage("file.py", "review", 10000)
        assert self.tracker.get_total_cost() > 0

    def test_budget_not_set(self):
        assert self.tracker.is_over_budget() is False
        assert self.tracker.get_remaining_budget() is None

    def test_budget_enforcement(self):
        tracker = CostTracker(budget=0.001)  # Very low budget
        tracker.record_stage("file.py", "review", 100000)  # Large usage
        assert tracker.is_over_budget() is True
        assert tracker.get_remaining_budget() == 0.0

    def test_budget_not_exceeded(self):
        tracker = CostTracker(budget=10.0)  # High budget
        tracker.record_stage("file.py", "review", 1000)
        assert tracker.is_over_budget() is False
        assert tracker.get_remaining_budget() > 0

    def test_get_summary(self):
        self.tracker.record_stage("file1.py", "review", 1000)
        self.tracker.record_stage("file2.py", "review", 2000)
        summary = self.tracker.get_summary()
        assert summary["files_reviewed"] == 2
        assert summary["total_tokens"] == 3000
        assert summary["total_cost_usd"] > 0
        assert summary["budget"] is None

    def test_detailed_summary(self):
        self.tracker.record_stage("file.py", "review", 1000)
        summary_str = self.tracker.get_detailed_summary()
        assert "Cost Summary" in summary_str
        assert "file.py" in summary_str
        assert "review" in summary_str

    def test_avg_cost_per_file(self):
        self.tracker.record_stage("file1.py", "review", 1000)
        self.tracker.record_stage("file2.py", "review", 2000)
        summary = self.tracker.get_summary()
        assert summary["avg_cost_per_file"] > 0

    def test_empty_tracker(self):
        assert self.tracker.get_total_tokens() == 0
        assert self.tracker.get_total_cost() == 0.0
        summary = self.tracker.get_summary()
        assert summary["files_reviewed"] == 0
        assert summary["avg_cost_per_file"] == 0
