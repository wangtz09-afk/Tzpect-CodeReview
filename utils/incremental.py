"""Incremental review mode — only review changed lines, not entire files.

Saves 60-80% tokens by extracting only the hunk context around changed lines.
"""
import re
from dataclasses import dataclass
from typing import Optional


# Pre-compiled unified diff hunk header pattern
_HUNK_HEADER_RE = re.compile(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@')


@dataclass
class ChangedHunk:
    """A contiguous block of changed lines with surrounding context."""
    start_line: int
    end_line: int
    changed_lines: list[tuple[int, str]]  # (line_number, line_text)
    context_before: list[str]
    context_after: list[str]


def parse_diff_hunks(diff: str, context_lines: int = 3) -> list[ChangedHunk]:
    """Parse a unified diff into changed hunks with context.

    Args:
        diff: Unified diff string.
        context_lines: Number of context lines before/after each hunk.

    Returns:
        List of ChangedHunk objects.
    """
    hunks = []
    current_hunk = None
    hunk_header_pattern = _HUNK_HEADER_RE

    # Track original file line numbers
    orig_line = 0

    for line in diff.splitlines():
        match = hunk_header_pattern.match(line)
        if match:
            # Save previous hunk if exists
            if current_hunk and current_hunk.changed_lines:
                hunks.append(current_hunk)

            orig_line = int(match.group(1))
            current_hunk = ChangedHunk(
                start_line=orig_line,
                end_line=orig_line,
                changed_lines=[],
                context_before=[],
                context_after=[],
            )
            continue

        if current_hunk is None:
            continue

        if line.startswith('-'):
            # Removed line
            current_hunk.changed_lines.append((orig_line, f"- {line[1:]}"))
            current_hunk.end_line = orig_line
            orig_line += 1
        elif line.startswith('+'):
            # Added line
            current_hunk.changed_lines.append((orig_line, f"+ {line[1:]}"))
            current_hunk.end_line = orig_line
        elif line.startswith(' '):
            # Context line
            current_hunk.changed_lines.append((orig_line, f"  {line[1:]}"))
            current_hunk.end_line = orig_line
            orig_line += 1
        elif line.startswith('\\'):
            continue  # "\ No newline at end of file"
        else:
            orig_line += 1

    # Save last hunk
    if current_hunk and current_hunk.changed_lines:
        hunks.append(current_hunk)

    return hunks


def extract_changed_lines(
    content: str,
    diff: str,
    context_lines: int = 5,
    max_hunks: int = 50,
) -> str:
    """Extract only changed lines with context from the full file content.

    This reduces token usage by 60-80% for large files with small changes.

    Args:
        content: Full file content.
        diff: Unified diff string.
        context_lines: Lines of context before/after each change.
        max_hunks: Maximum number of hunks to include.

    Returns:
        Filtered content with only changed hunks and context.
    """
    if not diff:
        return content

    hunks = parse_diff_hunks(diff, context_lines)
    if not hunks:
        return content

    # Limit hunks to avoid excessive output
    hunks = hunks[:max_hunks]

    lines = content.splitlines(keepends=True)
    total_lines = len(lines)

    # Collect all line ranges that need to be included
    included_ranges = set()
    for hunk in hunks:
        # Include context before
        for ln in range(max(1, hunk.start_line - context_lines), hunk.start_line):
            included_ranges.add(ln - 1)  # 0-indexed
        # Include changed lines
        for ln, _ in hunk.changed_lines:
            included_ranges.add(ln - 1)  # 0-indexed
        # Include context after
        for ln in range(hunk.end_line + 1, min(total_lines + 1, hunk.end_line + context_lines + 1)):
            included_ranges.add(ln - 1)  # 0-indexed

    if not included_ranges:
        return content

    # Build filtered output with gap markers
    sorted_lines = sorted(included_ranges)
    output_lines = []
    prev_line = -1

    for line_idx in sorted_lines:
        if line_idx >= total_lines:
            break
        if prev_line >= 0 and line_idx > prev_line + 1:
            output_lines.append(f"\n... ({line_idx - prev_line - 1} unchanged lines omitted) ...\n")
        output_lines.append(lines[line_idx])
        if not lines[line_idx].endswith('\n'):
            output_lines.append('\n')
        prev_line = line_idx

    result = ''.join(output_lines).strip()
    if not result:
        return content

    # Add header comment
    header = (
        f"// NOTE: Only changed lines shown (context: {context_lines} lines, "
        f"hunks: {len(hunks)}/{len(parse_diff_hunks(diff))})\n"
    )
    return header + result


def get_changed_line_numbers(diff: str) -> set[int]:
    """Get set of line numbers that were added/changed in the diff.

    Args:
        diff: Unified diff string.

    Returns:
        Set of 1-indexed line numbers that are new/changed.
    """
    changed = set()
    hunk_header_pattern = _HUNK_HEADER_RE
    new_line = 0

    for line in diff.splitlines():
        match = hunk_header_pattern.match(line)
        if match:
            new_line = int(match.group(2))
            continue

        if line.startswith('-'):
            continue  # Removed lines don't affect new line numbers
        elif line.startswith('+'):
            changed.add(new_line)
            new_line += 1
        elif line.startswith(' '):
            new_line += 1

    return changed


def get_diff_stats(diff: str) -> dict:
    """Get statistics about a diff.

    Args:
        diff: Unified diff string.

    Returns:
        Dict with added, removed, modified, hunks, and files counts.
    """
    added = 0
    removed = 0
    hunks = 0
    files = 0
    current_file = None

    for line in diff.splitlines():
        if line.startswith('diff --git'):
            files += 1
            current_file = line
        elif line.startswith('@@'):
            hunks += 1
        elif line.startswith('+') and not line.startswith('+++'):
            added += 1
        elif line.startswith('-') and not line.startswith('---'):
            removed += 1

    return {
        "added": added,
        "removed": removed,
        "modified": min(added, removed),  # Approximate
        "hunks": hunks,
        "files": files,
    }


def is_incremental_beneficial(diff: str, content: str, threshold: int = 50) -> bool:
    """Determine if incremental review would be beneficial.

    Returns True if the diff is small relative to the file size,
    meaning incremental review would save significant tokens.

    Args:
        diff: Unified diff string.
        content: Full file content.
        threshold: Minimum file lines for incremental to be worth it.

    Returns:
        True if incremental review recommended.
    """
    lines = len(content.splitlines())
    if lines < threshold:
        return False  # Small files aren't worth the complexity

    stats = get_diff_stats(diff)
    total_changed = stats["added"] + stats["removed"]

    # If less than 20% of lines changed, incremental is beneficial
    return total_changed < lines * 0.2
