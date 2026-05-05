"""Git operations and direct file scanning."""
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from utils.common import get_language, should_skip_dir


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    """Run a git command, returning text output."""
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


@dataclass
class CodeChange:
    """Represents a single file change or scanned file."""
    file_path: str
    status: str = "M"  # M=modified, A=added, D=deleted, S=scanned
    diff: str = ""
    content: str = ""
    language: str = ""


@dataclass
class ReviewContext:
    """Full context for a code review session."""
    repo_path: str
    branch: str
    changes: list[CodeChange] = field(default_factory=list)
    commit_message: str = ""
    metadata: dict = field(default_factory=dict)


def get_repo_path(path: str) -> str:
    """Resolve to the git repo root, or return the path itself."""
    path = os.path.abspath(path)
    result = _run_git(["git", "rev-parse", "--show-toplevel"], cwd=path)
    if result.returncode == 0:
        return result.stdout.strip()
    return path


def is_binary(file_path: str) -> bool:
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(8192)
        return b"\x00" in chunk
    except Exception:
        return True


def scan_source_files(repo_path: str, max_files: int = 30) -> list[CodeChange]:
    """
    Directly scan source files in a directory (for non-Git projects).
    Scans common source directories and files.

    Args:
        repo_path: Path to the project.
        max_files: Maximum number of files to scan.

    Returns:
        List of CodeChange objects with file contents.
    """
    changes: list[CodeChange] = []
    source_extensions = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go",
        ".rs", ".c", ".cpp", ".h", ".hpp", ".rb", ".php",
        ".swift", ".kt", ".vue", ".sql", ".cs", ".scala",
    }

    def _scan_dir(base_path: str, depth: int = 0):
        """Recursively scan directories."""
        if depth > 6:
            return
        if len(changes) >= max_files:
            return

        try:
            entries = sorted(os.listdir(base_path))
        except PermissionError:
            return

        for entry in entries:
            if entry.startswith("."):
                continue

            full_path = os.path.join(base_path, entry)
            rel_path = os.path.relpath(full_path, repo_path)

            if os.path.isdir(full_path):
                if should_skip_dir(entry):
                    continue
                _scan_dir(full_path, depth + 1)
            elif os.path.isfile(full_path):
                ext = Path(entry).suffix.lower()
                if ext in source_extensions:
                    if is_binary(full_path):
                        continue
                    try:
                        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                    except Exception:
                        continue

                    # Only include files with meaningful content
                    if len(content.strip()) > 50:
                        changes.append(CodeChange(
                            file_path=rel_path,
                            status="S",
                            diff="",
                            content=content,
                            language=get_language(entry),
                        ))

                    if len(changes) >= max_files:
                        return

    # Prefer common source directories, fall back to whole project
    source_dirs = [
        "src", "sky-server/src", "src/main",
        "server/src", "app", "lib", "backend/src",
    ]

    scanned = False
    for src_dir in source_dirs:
        full_src = os.path.join(repo_path, src_dir)
        if os.path.isdir(full_src):
            _scan_dir(full_src)
            scanned = True
            break

    if not scanned or not changes:
        _scan_dir(repo_path)

    return changes[:max_files]


def get_changes(
    repo_path: str,
    staged: bool = False,
    since_commit: Optional[str] = None,
) -> list[CodeChange]:
    """
    Extract code changes from a git repo. Falls back to file scanning if not a git repo.

    Args:
        repo_path: Path to the git repository or project.
        staged: If True, get staged changes.
        since_commit: If provided, get changes since this commit.

    Returns:
        List of CodeChange objects.
    """
    result = _run_git(["git", "rev-parse", "--show-toplevel"], cwd=repo_path)

    if result.returncode == 0:
        return _get_git_changes(repo_path, staged, since_commit)
    else:
        return scan_source_files(repo_path)


def _parse_diff_file_path(line: str) -> Optional[str]:
    """Safely parse a file path from a 'diff --git a/... b/...' line."""
    match = re.match(r'diff --git a/(.*) b/(.*)', line)
    if match:
        return match.group(2)
    return None


def _get_git_changes(
    repo_path: str,
    staged: bool,
    since_commit: Optional[str],
) -> list[CodeChange]:
    """Get changes via git commands."""
    changes: list[CodeChange] = []

    if since_commit:
        diff_cmd = ["git", "diff", f"{since_commit}"]
        status_cmd = ["git", "diff", "--name-status", f"{since_commit}"]
    elif staged:
        diff_cmd = ["git", "diff", "--staged"]
        status_cmd = ["git", "diff", "--staged", "--name-status"]
    else:
        diff_cmd = ["git", "diff", "HEAD"]
        status_cmd = ["git", "diff", "--name-status", "HEAD"]

    result = _run_git(status_cmd, cwd=repo_path)
    if result.returncode != 0:
        return changes

    file_statuses: dict[str, str] = {}
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.strip().split("\t")
        status = parts[0]
        file_path = parts[-1] if len(parts) > 1 else parts[0]
        file_statuses[file_path] = status

    diff_result = _run_git(diff_cmd, cwd=repo_path)
    full_diff = diff_result.stdout if diff_result.returncode == 0 else ""

    current_file: Optional[str] = None
    current_diff_lines: list[str] = []

    for line in full_diff.split("\n"):
        if line.startswith("diff --git"):
            # Save previous file
            if current_file and current_diff_lines:
                changes.append(CodeChange(
                    file_path=current_file,
                    status=file_statuses.get(current_file, "M"),
                    diff="\n".join(current_diff_lines),
                    language=get_language(current_file),
                ))
            current_diff_lines = []

            # Parse new file
            parsed = _parse_diff_file_path(line)
            current_file = parsed
        elif current_file:
            current_diff_lines.append(line)

    # Don't forget the last file
    if current_file and current_diff_lines:
        changes.append(CodeChange(
            file_path=current_file,
            status=file_statuses.get(current_file, "M"),
            diff="\n".join(current_diff_lines),
            language=get_language(current_file),
        ))

    # Load file content for modified and added files
    for change in changes:
        if change.status in ("M", "A"):
            full_path = os.path.join(repo_path, change.file_path)
            try:
                if is_binary(full_path):
                    continue
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    change.content = f.read()
            except (FileNotFoundError, PermissionError, IsADirectoryError):
                change.content = ""

    return changes


def is_git_repo(path: str) -> bool:
    """Check if path is inside a git repo."""
    result = _run_git(["git", "rev-parse", "--show-toplevel"], cwd=path)
    return result.returncode == 0


def get_commit_message(repo_path: str) -> str:
    """Get the latest commit message."""
    result = _run_git(["git", "log", "-1", "--format=%s"], cwd=repo_path)
    return result.stdout.strip() if result.returncode == 0 else ""


def get_current_branch(repo_path: str) -> str:
    """Get the current git branch name."""
    result = _run_git(["git", "branch", "--show-current"], cwd=repo_path)
    return result.stdout.strip() if result.returncode == 0 else "(非Git仓库，直接扫描)"


def get_file_at_commit(repo_path: str, file_path: str, commit: str = "HEAD") -> str:
    """Get the content of a file at a specific commit."""
    full_path = os.path.join(file_path)
    result = _run_git(
        ["git", "show", f"{commit}:{full_path}"],
        cwd=repo_path,
    )
    if result.returncode == 0:
        return result.stdout
    return ""


def get_diff_stats(repo_path: str) -> dict:
    """Get summary stats of current diff."""
    result = _run_git(
        ["git", "diff", "--stat", "HEAD"],
        cwd=repo_path,
    )
    if result.returncode != 0:
        return {"files_changed": 0, "insertions": 0, "deletions": 0}

    output = result.stdout.strip()
    # Parse last line like "X files changed, Y insertions(+), Z deletions(-)"
    stats = {"files_changed": 0, "insertions": 0, "deletions": 0}
    if output:
        last_line = output.split("\n")[-1]
        m_files = re.search(r'(\d+) files? changed', last_line)
        m_ins = re.search(r'(\d+) insertions?\(\+\)', last_line)
        m_del = re.search(r'(\d+) deletions?\(-\)', last_line)
        if m_files:
            stats["files_changed"] = int(m_files.group(1))
        if m_ins:
            stats["insertions"] = int(m_ins.group(1))
        if m_del:
            stats["deletions"] = int(m_del.group(1))
    return stats
