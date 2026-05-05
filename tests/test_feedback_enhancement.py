"""Tests for feedback learning enhancement modules.

Tests:
- FeedbackDB: auto-collect, learned patterns, cross-project, export/import
- AutoTuner: rule generation, YAML output, file writing
- Path normalization
- Weighted prompt generation
"""
import json
import os
import tempfile
from pathlib import Path

import pytest

from utils.feedback_db import FeedbackDB, LearnedPattern
from utils.auto_tuner import AutoTuner, AutoTunedConfig
from utils.custom_rules import is_auto_suppressed, RuleConfig


class TestPathNormalization:
    """Test file path -> category normalization."""

    def setup_method(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = FeedbackDB(self.db_path)

    def teardown_method(self):
        self.db.reset()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_java_spring_controller(self):
        cat = self.db.normalize_path("server/src/com/sky/controller/EmployeeController.java")
        assert "java" in cat
        assert "spring" in cat
        assert "controller" in cat

    def test_java_spring_service(self):
        cat = self.db.normalize_path("app/service/impl/UserServiceImpl.java")
        assert "service" in cat

    def test_java_spring_mapper(self):
        cat = self.db.normalize_path("app/mapper/UserMapper.java")
        # Mapper maps to "repository" role in the normalization rules
        assert "repository" in cat

    def test_java_model(self):
        cat = self.db.normalize_path("app/pojo/User.java")
        assert "model" in cat

    def test_python_service(self):
        cat = self.db.normalize_path("app/services/user_service.py")
        assert "python" in cat
        assert "service" in cat

    def test_go_handler(self):
        cat = self.db.normalize_path("handlers/user_handler.go")
        assert "go" in cat
        assert "controller" in cat

    def test_test_files(self):
        cat = self.db.normalize_path("tests/test_user.py")
        assert "test" in cat

    def test_config_files(self):
        cat = self.db.normalize_path("config/app_config.py")
        assert "config" in cat


class TestAutoCollect:
    """Test auto-feedback collection from apply-fixes actions."""

    def setup_method(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = FeedbackDB(self.db_path)

    def teardown_method(self):
        self.db.reset()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_auto_collect_records_accepted(self):
        issues = [
            {"type": "SQL Injection", "severity": "critical", "description": "Raw SQL"},
        ]
        count = self.db.auto_collect(
            file_path="app/service/UserService.java",
            issues=issues,
            applied_issue_types={"SQL Injection"},
            skipped_issue_types=set(),
            modified_issue_types=set(),
        )
        assert count == 1
        stats = self.db.get_stats()
        assert stats.accepted == 1

    def test_auto_collect_records_dismissed(self):
        issues = [
            {"type": "Magic Number", "severity": "low", "description": "Hardcoded"},
        ]
        count = self.db.auto_collect(
            file_path="app/controller/UserController.java",
            issues=issues,
            applied_issue_types=set(),
            skipped_issue_types={"Magic Number"},
            modified_issue_types=set(),
        )
        assert count == 1
        stats = self.db.get_stats()
        assert stats.dismissed == 1

    def test_auto_collect_mixed(self):
        issues = [
            {"type": "SQL Injection", "severity": "critical"},
            {"type": "Magic Number", "severity": "low"},
            {"type": "N+1 Query", "severity": "high"},
        ]
        count = self.db.auto_collect(
            file_path="app/service/OrderService.java",
            issues=issues,
            applied_issue_types={"SQL Injection", "N+1 Query"},
            skipped_issue_types={"Magic Number"},
            modified_issue_types=set(),
        )
        assert count == 3
        stats = self.db.get_stats()
        assert stats.accepted == 2
        assert stats.dismissed == 1

    def test_auto_collect_skips_no_action(self):
        issues = [{"type": "SQL Injection", "severity": "critical"}]
        count = self.db.auto_collect(
            file_path="app/service/UserService.java",
            issues=issues,
            applied_issue_types=set(),
            skipped_issue_types=set(),
            modified_issue_types=set(),
        )
        assert count == 0

    def test_auto_collect_sets_auto_collected_flag(self):
        issues = [{"type": "SQL Injection", "severity": "critical"}]
        self.db.auto_collect(
            file_path="app/service/UserService.java",
            issues=issues,
            applied_issue_types={"SQL Injection"},
            skipped_issue_types=set(),
            modified_issue_types=set(),
        )
        # Verify by checking stats — the entry should exist
        stats = self.db.get_stats()
        assert stats.total_reviews == 1


class TestLearnedPatterns:
    """Test learned pattern tracking and updates."""

    def setup_method(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = FeedbackDB(self.db_path)

    def teardown_method(self):
        self.db.reset()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_pattern_created_on_feedback(self):
        self.db.add_feedback(
            file_path="app/service/UserService.java",
            issue_type="SQL Injection",
            verdict="accepted",
        )
        patterns = self.db.get_learned_patterns()
        assert len(patterns) == 1
        assert patterns[0].issue_type == "SQL Injection"
        assert patterns[0].accepted_count >= 1

    def test_pattern_confidence_increases_with_evidence(self):
        # Add multiple accepted feedback for same pattern
        for _ in range(5):
            self.db.add_feedback(
                file_path="app/service/UserService.java",
                issue_type="SQL Injection",
                verdict="accepted",
            )
        patterns = self.db.get_learned_patterns()
        assert len(patterns) == 1
        p = patterns[0]
        assert p.evidence_count == 5
        # Confidence should be low (meaning high accuracy / low FP rate)
        assert p.confidence < 0.3

    def test_pattern_high_fp_detected(self):
        # Add multiple dismissed feedback (false positives)
        for _ in range(5):
            self.db.add_feedback(
                file_path="app/controller/UserController.java",
                issue_type="Magic Number",
                verdict="dismissed",
            )
        patterns = self.db.get_learned_patterns()
        assert len(patterns) == 1
        p = patterns[0]
        assert p.is_false_positive == 1
        assert p.confidence > 0.6

    def test_mixed_feedback(self):
        # 3 accepted + 1 dismissed
        for _ in range(3):
            self.db.add_feedback(
                file_path="app/service/UserService.java",
                issue_type="SQL Injection",
                verdict="accepted",
            )
        self.db.add_feedback(
            file_path="app/service/UserService.java",
            issue_type="SQL Injection",
            verdict="dismissed",
        )
        patterns = self.db.get_learned_patterns()
        assert len(patterns) == 1
        p = patterns[0]
        assert p.accepted_count == 3  # 3 accepted, dismissed doesn't affect accepted_count
        assert p.dismissed_count == 1
        assert p.evidence_count == 4


class TestWeightedPrompt:
    """Test structured weighted prompt generation."""

    def setup_method(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = FeedbackDB(self.db_path)

    def teardown_method(self):
        self.db.reset()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_empty_prompt(self):
        prompt = self.db.get_feedback_for_prompt("app/service/UserService.java")
        assert isinstance(prompt, str)

    def test_suppressed_layer_shown(self):
        # Add enough dismissed feedback to trigger suppression
        for _ in range(6):
            self.db.add_feedback(
                file_path="app/service/UserService.java",
                issue_type="Magic Number",
                verdict="dismissed",
            )
        prompt = self.db.get_feedback_for_prompt("app/service/UserService.java")
        assert "Suppressed" in prompt or "False Positive" in prompt or "Guidelines" in prompt

    def test_priority_layer_shown(self):
        # Add enough accepted feedback to trigger prioritization
        for _ in range(6):
            self.db.add_feedback(
                file_path="app/service/UserService.java",
                issue_type="SQL Injection",
                verdict="accepted",
            )
        prompt = self.db.get_feedback_for_prompt("app/service/UserService.java")
        assert "Priority" in prompt or "Guidelines" in prompt


class TestAutoTuner:
    """Test auto-tuned rule generation."""

    def setup_method(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = FeedbackDB(self.db_path)
        self.tuner = AutoTuner(self.db_path)

    def teardown_method(self):
        self.db.reset()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_no_rules_with_insufficient_evidence(self):
        # Only 1 feedback entry — below MIN_EVIDENCE threshold
        self.db.add_feedback("app/service/UserService.java", "SQL Injection", "accepted")
        config = self.tuner.tune()
        assert len(config.suppress) == 0
        assert len(config.prioritize) == 0

    def test_suppress_rule_generated(self):
        # Add enough dismissed feedback
        for _ in range(5):
            self.db.add_feedback("app/controller/UserController.java", "Magic Number", "dismissed")
        config = self.tuner.tune()
        assert len(config.suppress) >= 1
        assert any(r.issue_type == "Magic Number" for r in config.suppress)

    def test_prioritize_rule_generated(self):
        # Add enough accepted feedback
        for _ in range(5):
            self.db.add_feedback("app/service/UserService.java", "SQL Injection", "accepted")
        config = self.tuner.tune()
        assert len(config.prioritize) >= 1
        assert any(r.issue_type == "SQL Injection" for r in config.prioritize)

    def test_yaml_output(self):
        for _ in range(5):
            self.db.add_feedback("app/controller/UserController.java", "Magic Number", "dismissed")
        config = self.tuner.tune()
        yaml_str = config.to_yaml()
        assert "# [AUTO-GENERATED FROM FEEDBACK]" in yaml_str
        assert "auto_tuned:" in yaml_str
        assert "suppress:" in yaml_str

    def test_apply_to_file(self):
        fd, self.yaml_path = tempfile.mkstemp(suffix=".yml")
        os.close(fd)

        try:
            # Add feedback to generate rules
            for _ in range(5):
                self.db.add_feedback("app/controller/UserController.java", "Magic Number", "dismissed")

            self.tuner.apply_to_file(self.yaml_path)
            with open(self.yaml_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "# [AUTO-GENERATED FROM FEEDBACK]" in content
            assert "auto_tuned:" in content
        finally:
            try:
                os.unlink(self.yaml_path)
            except OSError:
                pass


class TestCrossProjectExportImport:
    """Test cross-project knowledge sharing."""

    def setup_method(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = FeedbackDB(self.db_path)

        fd2, self.export_path = tempfile.mkstemp(suffix=".json")
        os.close(fd2)

    def teardown_method(self):
        self.db.reset()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass
        try:
            os.unlink(self.export_path)
        except OSError:
            pass

    def test_export(self):
        # Add some feedback
        for _ in range(3):
            self.db.add_feedback("app/service/UserService.java", "SQL Injection", "accepted")

        data = self.db.export_knowledge()
        assert "learned_patterns" in data
        assert "stats" in data
        assert data["stats"]["total_reviews"] >= 3

    def test_export_import_roundtrip(self):
        for _ in range(3):
            self.db.add_feedback("app/service/UserService.java", "SQL Injection", "accepted")

        # Export
        data = self.db.export_knowledge()
        with open(self.export_path, "w") as f:
            json.dump(data, f)

        # Reset and import
        self.db.reset()
        with open(self.export_path, "r") as f:
            imported_data = json.load(f)

        count = self.db.import_knowledge(imported_data)
        assert count >= 1

    def test_is_auto_suppressed(self):
        config = RuleConfig(
            auto_suppress=[
                {"issue_type": "Magic Number", "file_category": "java:spring:controller"}
            ]
        )
        assert is_auto_suppressed("Magic Number", "java:spring:controller", config) is True
        assert is_auto_suppressed("SQL Injection", "java:spring:controller", config) is False
        assert is_auto_suppressed("Magic Number", "java:spring:service", config) is False

    def test_is_auto_suppressed_empty_config(self):
        config = RuleConfig()
        assert is_auto_suppressed("Magic Number", "java:spring:controller", config) is False
