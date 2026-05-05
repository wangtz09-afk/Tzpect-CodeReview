"""Tests for new modules integration."""
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from utils.project_context import (
    detect_project_context,
    detect_frameworks,
    detect_primary_language,
    ProjectContext,
)
from utils.custom_rules import (
    load_rules,
    should_ignore,
    is_check_enabled,
    RuleConfig,
    Rule,
)
from utils.cross_file_analyzer import (
    analyze_project,
    FileInfo,
    ProjectGraph,
)
from utils.fix_quality import (
    assess_fix_quality,
    FixQualityReport,
)
from utils.feedback_db import (
    FeedbackDB,
    FeedbackStats,
)


class TestProjectContext:
    def test_detect_no_frameworks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Empty dir should detect nothing
            context = detect_project_context(tmpdir)
            assert context.frameworks == []

    def test_detect_python_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a Python project structure
            with open(os.path.join(tmpdir, "main.py"), "w") as f:
                f.write("print('hello')")
            with open(os.path.join(tmpdir, "requirements.txt"), "w") as f:
                f.write("flask\n")

            context = detect_project_context(tmpdir)
            assert context.language == "python"
            assert context.total_files >= 1

    def test_detect_spring_boot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a Spring Boot project structure
            os.makedirs(os.path.join(tmpdir, "src", "main", "java"))
            with open(os.path.join(tmpdir, "pom.xml"), "w") as f:
                f.write("<project></project>")
            with open(os.path.join(tmpdir, "application.properties"), "w") as f:
                f.write("server.port=8080")

            frameworks = detect_frameworks(tmpdir)
            fw_names = [fw.name for fw in frameworks]
            assert "Spring Boot" in fw_names

    def test_detect_django(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "manage.py"), "w") as f:
                f.write("# Django manage.py")
            with open(os.path.join(tmpdir, "settings.py"), "w") as f:
                f.write("INSTALLED_APPS = []")

            frameworks = detect_frameworks(tmpdir)
            fw_names = [fw.name for fw in frameworks]
            assert "Django" in fw_names

    def test_context_to_prompt(self):
        context = ProjectContext(
            frameworks=[],
            common_patterns=["MVC architecture"],
            constraints=["Use @Transactional"],
        )
        prompt = context.to_prompt()
        assert "MVC architecture" in prompt
        assert "@Transactional" in prompt

    def test_empty_context_to_prompt(self):
        context = ProjectContext()
        prompt = context.to_prompt()
        assert prompt == ""

    def test_detect_primary_language(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create multiple Python files
            for i in range(5):
                with open(os.path.join(tmpdir, f"file{i}.py"), "w") as f:
                    f.write("x = 1")
            # Create one Java file
            with open(os.path.join(tmpdir, "Main.java"), "w") as f:
                f.write("class Main {}")

            lang = detect_primary_language(tmpdir)
            assert lang == "python"


class TestCustomRules:
    def test_default_config(self):
        config = RuleConfig()
        assert config.ignore_patterns == []
        assert config.rules == []
        assert config.max_issues == 50

    def test_should_ignore(self):
        config = RuleConfig(ignore_patterns=["tests/*", "generated/**"])
        assert should_ignore("tests/test_foo.py", config) is True
        assert should_ignore("generated/api.py", config) is True
        assert should_ignore("src/main.py", config) is False

    def test_should_ignore_basename(self):
        config = RuleConfig(ignore_patterns=["conftest.py"])
        assert should_ignore("tests/conftest.py", config) is True

    def test_is_check_enabled(self):
        config = RuleConfig(disabled_checks=["performance", "style"])
        assert is_check_enabled("security", config) is True
        assert is_check_enabled("performance", config) is False
        assert is_check_enabled("style", config) is False

    def test_is_check_enabled_with_whitelist(self):
        config = RuleConfig(enabled_checks=["security"])
        assert is_check_enabled("security", config) is True
        assert is_check_enabled("performance", config) is False

    def test_rules_to_prompt(self):
        config = RuleConfig(
            disabled_checks=["performance"],
            custom_instructions="Be strict about null handling",
        )
        prompt = config.to_prompt() if hasattr(config, 'to_prompt') else ""
        # custom_rules.to_prompt function, not RuleConfig method
        from utils.custom_rules import to_prompt as rules_to_prompt
        prompt = rules_to_prompt(config)
        assert "performance" in prompt
        assert "null handling" in prompt

    def test_load_rules_no_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_rules(tmpdir)
            assert isinstance(config, RuleConfig)
            assert config.rules == []


class TestCrossFileAnalyzer:
    def test_empty_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            graph = analyze_project(tmpdir, [])
            assert len(graph.files) == 0

    def test_analyze_python_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a Python file
            with open(os.path.join(tmpdir, "main.py"), "w") as f:
                f.write("class MyClass:\n    def my_func(self):\n        pass\n")

            graph = analyze_project(tmpdir, ["main.py"])
            assert "main.py" in graph.files
            assert "MyClass" in graph.classes
            assert "my_func" in graph.functions

    def test_content_hash_computed(self):
        """Content hash should be computed for each file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "main.py"), "w") as f:
                f.write("x = 1\n")

            graph = analyze_project(tmpdir, ["main.py"])
            file_info = graph.files["main.py"]
            assert file_info.content_hash != ""
            assert len(file_info.content_hash) == 16  # SHA-256 truncated to 16 chars

    def test_deduplication(self):
        """Duplicate symbols should be deduplicated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Function appears in multiple patterns
            with open(os.path.join(tmpdir, "main.py"), "w") as f:
                f.write("def my_func():\n    pass\n\ndef my_func():\n    pass\n")

            graph = analyze_project(tmpdir, ["main.py"])
            assert graph.files["main.py"].functions.count("my_func") == 1

    def test_analyze_java_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a Java file
            with open(os.path.join(tmpdir, "Service.java"), "w") as f:
                f.write("""
public class UserService {
    public void save(User user) {}
    public User findById(Long id) { return null; }
}
""")

            graph = analyze_project(tmpdir, ["Service.java"])
            assert "UserService" in graph.classes
            assert "save" in graph.functions

    def test_cross_file_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create two related files
            with open(os.path.join(tmpdir, "Interface.java"), "w") as f:
                f.write("public interface MyService { void doSomething(); }")
            with open(os.path.join(tmpdir, "Impl.java"), "w") as f:
                f.write("public class MyServiceImpl implements MyService { public void doSomething() {} }")

            graph = analyze_project(tmpdir, ["Interface.java", "Impl.java"])
            context = graph.to_context_prompt("Impl.java")
            # Should show interface relationship
            assert isinstance(context, str)

    def test_project_graph_empty_context(self):
        graph = ProjectGraph()
        context = graph.to_context_prompt("nonexistent.py")
        assert context == ""


class TestFixQuality:
    def test_perfect_fix(self):
        original = "def foo():\n    return 1\n"
        fixed = "def foo():\n    return 2\n"
        report = assess_fix_quality(original, fixed, "python")
        assert report.overall_score >= 0.5
        assert report.syntax_valid is True

    def test_syntax_error(self):
        original = "def foo():\n    return 1\n"
        fixed = "def foo(\n    return 1\n"  # Missing closing paren
        report = assess_fix_quality(original, fixed, "python")
        assert report.syntax_valid is False

    def test_excessive_changes(self):
        original = "\n".join([f"line {i}" for i in range(100)])
        fixed = "totally different"
        report = assess_fix_quality(original, fixed, "python")
        assert report.semantic_similar is False  # >80% changed

    def test_removed_function(self):
        original = "def foo():\n    pass\n\ndef bar():\n    pass\n"
        fixed = "def foo():\n    pass\n"  # Removed bar
        report = assess_fix_quality(original, fixed, "python")
        assert report.structure_preserved is False

    def test_good_score_range(self):
        original = "x = 1"
        fixed = "x = 2"
        report = assess_fix_quality(original, fixed, "python")
        assert 0.0 <= report.overall_score <= 1.0

    def test_is_good_method(self):
        report = FixQualityReport(overall_score=0.8, syntax_valid=True, test_passed=True)
        assert report.is_good() is True

    def test_is_bad_method(self):
        report = FixQualityReport(overall_score=0.3, syntax_valid=False)
        assert report.is_good() is False


class TestFeedbackDB:
    def test_add_and_get_feedback(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            db = FeedbackDB(db_path=db_path)
            db.add_feedback("test.py", "SQL Injection", "accepted", "test desc", "high")
            db.add_feedback("test.py", "Null Pointer", "dismissed", "test desc", "medium")

            stats = db.get_stats()
            assert stats.total_reviews == 2
            assert stats.accepted == 1
            assert stats.dismissed == 1
        finally:
            os.unlink(db_path)

    def test_acceptance_rate(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            db = FeedbackDB(db_path=db_path)
            db.add_feedback("a.py", "XSS", "accepted")
            db.add_feedback("b.py", "XSS", "accepted")
            db.add_feedback("c.py", "XSS", "dismissed")

            stats = db.get_stats()
            assert abs(stats.acceptance_rate - 0.667) < 0.01
        finally:
            os.unlink(db_path)

    def test_dismissed_types(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            db = FeedbackDB(db_path=db_path)
            # Add 3 dismissed entries for same type
            for i in range(3):
                db.add_feedback(f"test{i}.py", "Magic Number", "dismissed")

            dismissed = db.get_dismissed_types(min_count=3)
            assert "Magic Number" in dismissed
        finally:
            os.unlink(db_path)

    def test_feedback_for_prompt(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            db = FeedbackDB(db_path=db_path)
            prompt = db.get_feedback_for_prompt("src/main.py")
            assert isinstance(prompt, str)
        finally:
            os.unlink(db_path)

    def test_reset(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            db = FeedbackDB(db_path=db_path)
            db.add_feedback("test.py", "Bug", "accepted")
            db.reset()
            stats = db.get_stats()
            assert stats.total_reviews == 0
        finally:
            os.unlink(db_path)

    def test_export_stats(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            db = FeedbackDB(db_path=db_path)
            db.add_feedback("test.py", "Bug", "accepted")
            exported = db.export_stats()
            assert "acceptance_rate" in exported
            assert "type_stats" in exported
        finally:
            os.unlink(db_path)
