"""Output formatting for review results.

Provides human-readable, JSON, Markdown, and file-saving output
for pipeline review results.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.models import PipelineResult

console = Console()

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

SEVERITY_ICONS = {
    "critical": "[red][!][/red]",
    "high": "[red][!!][/red]",
    "medium": "[yellow][~][/yellow]",
    "low": "[blue][i][/blue]",
}


# ── Severity Filtering ──────────────────────────────────────────────────────

def filter_issues_by_severity(issues: list, min_severity: Optional[str] = None) -> list:
    """Filter issues by minimum severity level."""
    if not min_severity:
        return issues
    threshold = SEVERITY_ORDER.get(min_severity.lower(), 3)
    return [i for i in issues if SEVERITY_ORDER.get(i.get("severity", "low").lower(), 3) <= threshold]


# ── Human-Readable Output ───────────────────────────────────────────────────

def output_human(results: list[PipelineResult], compact: bool = False) -> None:
    """Output human-readable results.

    If compact=True, show a summary table instead of detailed per-issue output.
    """
    if compact:
        _output_human_compact(results)
        return

    _output_human_detailed(results)
    _output_summary(results)


def _output_human_detailed(results: list[PipelineResult]) -> None:
    """Detailed per-file output with all issues."""
    for r in results:
        review = r.review_result
        quality = review.get("overall_quality", "N/A")
        issues = review.get("issues", [])
        fix_code = r.fix_code
        test_passed = r.test_result.get("passed", None) if r.test_result else None
        verification = r.verification

        # File header
        console.print("")
        status_label = "[green]PASS[/green]" if not issues else "[red]FAIL[/red]"
        console.print(Panel(
            f"[bold]File:[/bold] {r.file_path}\n"
            f"[bold]Language:[/bold] {r.language}\n"
            f"[bold]Quality:[/bold] {quality}  {status_label}",
            title="Review",
            border_style="green" if not issues else "red",
        ))

        # Issues detail
        if issues:
            console.print("")
            console.print(f"[bold cyan]Found {len(issues)} issue(s):[/bold cyan]\n")

            for i, issue in enumerate(issues, 1):
                severity = issue.get("severity", "unknown").upper()
                issue_type = issue.get("type", "unknown")
                location = issue.get("location", "?")
                description = issue.get("description", "?")
                suggestion = issue.get("suggestion", "?")

                sev_icon = SEVERITY_ICONS.get(severity.lower(), "")

                if severity in ("CRITICAL", "HIGH"):
                    sev_style = "red"
                elif severity == "MEDIUM":
                    sev_style = "yellow"
                else:
                    sev_style = "blue"

                console.print(f"  [bold]{i}. {sev_icon} {issue_type}[/bold]")
                console.print(f"     [dim]{sev_style}[/]{severity}[/]  [dim]{location}[/dim]")
                console.print(f"     {description}")
                console.print(f"     [green]Fix:[/green] {suggestion}")

                # Fix status
                if fix_code:
                    if severity in ("CRITICAL", "HIGH", "MEDIUM"):
                        console.print(f"     [green]Auto-fixed[/green]")
                    else:
                        console.print(f"     [yellow]Not fixed (low severity)[/yellow]")
                elif any(s.startswith("fix") for s in r.stages):
                    console.print(f"     [yellow]Not fixed[/yellow]")
                else:
                    console.print(f"     [dim]No fix needed[/dim]")
                console.print()
        else:
            console.print("  [bold green]No issues found[/bold green]\n")

        # Pipeline summary line
        _output_file_meta(r, test_passed, verification)

    _output_summary(results)


def _output_human_compact(results: list[PipelineResult]) -> None:
    """Compact summary table output."""
    table = Table(title="[bold]Code Review Results[/bold]")
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("File", style="cyan", no_wrap=True)
    table.add_column("Lang", width=8)
    table.add_column("Quality", width=8)
    table.add_column("Issues", justify="right", width=6)
    table.add_column("Critical", justify="right", width=7, style="red")
    table.add_column("High", justify="right", width=5, style="red")
    table.add_column("Med", justify="right", width=4, style="yellow")
    table.add_column("Fix", width=4)
    table.add_column("Tokens", justify="right", width=8)
    table.add_column("Time", justify="right", width=7)

    for idx, r in enumerate(results, 1):
        review = r.review_result
        quality = review.get("overall_quality", "N/A")
        issues = review.get("issues", [])
        crit = sum(1 for i in issues if i.get("severity") == "critical")
        high = sum(1 for i in issues if i.get("severity") == "high")
        med = sum(1 for i in issues if i.get("severity") == "medium")
        has_fix = "[green]Y[/green]" if r.fix_code else "[dim]N[/dim]"
        issue_total = str(len(issues)) if issues else "[green]0[/green]"

        file_style = "red" if crit else "yellow" if high else "green"
        file_display = f"[{file_style}]{r.file_path}[/{file_style}]"

        table.add_row(
            str(idx),
            file_display,
            r.language,
            quality,
            issue_total,
            str(crit) if crit else "",
            str(high) if high else "",
            str(med) if med else "",
            has_fix,
            f"{r.total_tokens:,}",
            f"{r.elapsed_seconds:.1f}s",
        )

    console.print("")
    console.print(table)


def _output_file_meta(r: "PipelineResult", test_passed, verification) -> None:
    """Print metadata line for a single file."""
    test_str = "[green]PASS[/green]" if test_passed else "[dim]SKIP[/dim]" if test_passed is None else "[red]FAIL[/red]"
    console.print(f"  [dim]Test: {test_str}[/dim]", end="")

    if verification:
        decision = verification.get("final_decision", "")
        confidence = verification.get("confidence", "")
        extra = f" ({confidence})" if confidence else ""
        console.print(f"  [dim]Decision: {decision}{extra}[/dim]", end="")

    if r.fix_code:
        valid_str = "PASS" if r.fix_analysis.is_valid else "WARN"
        console.print(f"  [dim]Fix verify: {valid_str}[/dim]", end="")

    console.print(f"  [dim]Tokens: {r.total_tokens:,} | Time: {r.elapsed_seconds:.1f}s[/dim]")
    if r.fix_iterations > 0:
        console.print(f"  [dim]Fix rounds: {r.fix_iterations}[/dim]")


def _output_summary(results: list[PipelineResult]) -> None:
    """Print overall summary panel."""
    total_tokens = sum(r.total_tokens for r in results)
    total_issues = sum(len(r.review_result.get("issues", [])) for r in results)
    files_with_issues = sum(1 for r in results if r.review_result.get("issues"))
    files_fixed = sum(1 for r in results if r.fix_code)
    total_time = sum(r.elapsed_seconds for r in results)
    total_iterations = sum(r.fix_iterations for r in results)
    fix_warnings = sum(1 for r in results if r.fix_code and not r.fix_analysis.is_valid)

    critical = sum(1 for r in results for i in r.review_result.get("issues", []) if i.get("severity") == "critical")
    high = sum(1 for r in results for i in r.review_result.get("issues", []) if i.get("severity") == "high")

    summary_table = Table.grid()
    summary_table.add_column(justify="left")
    summary_table.add_column(justify="right")
    summary_table.add_row("Files reviewed", str(len(results)))
    summary_table.add_row("Issues found", f"{total_issues} ({files_with_issues} files)")
    if critical or high:
        summary_table.add_row("Critical/High", f"[red]{critical}/{high}[/red]")
    summary_table.add_row("Fixed", f"{files_fixed} files")
    if fix_warnings:
        summary_table.add_row("Fix warnings", f"[yellow]{fix_warnings}[/yellow]")
    summary_table.add_row("Fix rounds", str(total_iterations))
    summary_table.add_row("Total tokens", f"{total_tokens:,}")
    summary_table.add_row("Total duration", f"{total_time:.1f}s")

    console.print("")
    console.print(Panel(summary_table, title="[bold]Summary[/bold]", border_style="blue"))


# ── JSON Output ─────────────────────────────────────────────────────────────

def output_json(results: list[PipelineResult]) -> None:
    """Output JSON format results."""
    output = []
    for r in results:
        output.append({
            "file": r.file_path,
            "language": r.language,
            "stages": r.stages,
            "quality": r.review_result.get("overall_quality", "N/A"),
            "review": r.review_result,
            "fix_code": r.fix_code[:2000] if r.fix_code else "",
            "fix_iterations": r.fix_iterations,
            "fix_analysis": {
                "is_valid": r.fix_analysis.is_valid,
                "regression_risk": r.fix_analysis.regression_risk,
                "issues_count": len(r.fix_analysis.issues),
            } if r.fix_code else None,
            "test": r.test_result,
            "verification": r.verification,
            "total_tokens": r.total_tokens,
            "elapsed_seconds": round(r.elapsed_seconds, 1),
        })
    console.print(json.dumps(output, ensure_ascii=False, indent=2))


# ── Markdown Output ─────────────────────────────────────────────────────────

def output_markdown(results: list[PipelineResult], repo_path: str = "", branch: str = "", commit_msg: str = "") -> None:
    """Output Markdown format (suitable for PR comments, CI reports)."""
    from rich.console import Console as _Console
    _console = _Console()

    lines = []
    lines.append("# Code Review Report\n")
    lines.append(f"- **Project**: {repo_path}")
    lines.append(f"- **Branch**: {branch}")
    lines.append(f"- **Time**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    total_tokens = 0
    total_issues = 0

    for r in results:
        review = r.review_result
        quality = review.get("overall_quality", "N/A")
        issues = review.get("issues", [])
        total_tokens += r.total_tokens
        total_issues += len(issues)

        lines.append(f"---\n")
        lines.append(f"## `{r.file_path}`\n")
        lines.append(f"- **Language**: {r.language}")
        lines.append(f"- **Quality**: {quality}")
        lines.append(f"- **Tokens**: {r.total_tokens:,}")
        lines.append(f"- **Duration**: {r.elapsed_seconds:.1f}s")
        if r.fix_iterations:
            lines.append(f"- **Fix Iterations**: {r.fix_iterations}")
        lines.append("")

        if r.verification:
            decision = r.verification.get("final_decision", "?")
            confidence = r.verification.get("confidence", "?")
            can_merge = r.verification.get("can_merge", "?")
            lines.append(f"**Decision**: {decision} (confidence: {confidence}, mergeable: {can_merge})\n")

        if r.fix_code and r.fix_analysis:
            risk = r.fix_analysis.regression_risk
            valid = r.fix_analysis.is_valid
            lines.append(f"**Fix Verification**: {'Passed' if valid else 'Warning'} (regression risk: {risk})\n")

        if issues:
            lines.append(f"### Issues ({len(issues)})\n")
            lines.append("| # | Severity | Type | Location | Description |")
            lines.append("|---|----------|------|----------|-------------|")
            for i, issue in enumerate(issues, 1):
                sev = issue.get("severity", "unknown").upper()
                sev_icon = {"CRITICAL": "[C]", "HIGH": "[H]", "MEDIUM": "[M]", "LOW": "[L]"}.get(sev, "[-]")
                loc = issue.get("location", "?")
                desc = issue.get("description", "?").replace("\n", " ")[:100]
                itype = issue.get("type", "?")
                lines.append(f"| {i} | {sev_icon} {sev} | {itype} | `{loc}` | {desc} |")
            lines.append("")

            lines.append("### Suggestions\n")
            for i, issue in enumerate(issues, 1):
                lines.append(f"**{i}.** {issue.get('suggestion', 'N/A')}\n")
            lines.append("")

        if r.fix_code:
            lines.append("### Fixed Code\n")
            lines.append(f"```{r.language}\n{r.fix_code[:3000]}\n```\n")

        if r.test_result:
            passed = r.test_result.get("passed")
            if passed is not None:
                status = "Passed" if passed else "Failed"
                lines.append(f"### Test: {status}\n")

    # Summary
    lines.append("---\n")
    lines.append("## Summary\n")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Files | {len(results)} |")
    lines.append(f"| Issues | {total_issues} |")
    lines.append(f"| Fixed | {sum(1 for r in results if r.fix_code)} |")
    lines.append(f"| Tokens | {total_tokens:,} |")
    lines.append(f"| Duration | {sum(r.elapsed_seconds for r in results):.1f}s |")
    lines.append("")

    _console.print("\n".join(lines))


# ── SARIF Output ────────────────────────────────────────────────────────────

def output_sarif(results: list[PipelineResult], repo_path: str = "", branch: str = "") -> None:
    """Output SARIF format for GitHub Code Scanning."""
    from utils.output_formatter import to_sarif
    sarif = to_sarif(results, repo_path, branch)
    console.print(json.dumps(sarif, ensure_ascii=False, indent=2))


# ── HTML Output ─────────────────────────────────────────────────────────────

def output_html(results: list[PipelineResult], repo_path: str = "", branch: str = "", commit_msg: str = "") -> None:
    """Output HTML report."""
    from utils.output_formatter import to_html
    html = to_html(results, repo_path, branch, commit_msg)
    console.print(html)


# ── File Saving ─────────────────────────────────────────────────────────────

def save_results(results: list[PipelineResult], output_dir: str, repo_path: str = "", branch: str = "", commit_msg: str = "") -> None:
    """Save results to files."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # JSON
    json_path = os.path.join(output_dir, f"review_{timestamp}.json")
    data = []
    for r in results:
        data.append({
            "file": r.file_path,
            "language": r.language,
            "quality": r.review_result.get("overall_quality", "N/A"),
            "stages": r.stages,
            "review": r.review_result,
            "fix_code": r.fix_code if r.fix_code else "",
            "fix_iterations": r.fix_iterations,
            "fix_analysis": {
                "is_valid": r.fix_analysis.is_valid,
                "regression_risk": r.fix_analysis.regression_risk,
                "issues": [{"severity": i.severity, "category": i.category, "description": i.description}
                           for i in r.fix_analysis.issues],
            } if r.fix_code else None,
            "test": r.test_result,
            "verification": r.verification,
            "total_tokens": r.total_tokens,
            "elapsed_seconds": round(r.elapsed_seconds, 1),
        })
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Markdown
    md_path = os.path.join(output_dir, f"review_{timestamp}.md")
    lines = []
    lines.append(f"# Code Review — {repo_path}\n")
    lines.append(f"- **Branch**: {branch}")
    lines.append(f"- **Time**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **Commit**: {commit_msg}")
    lines.append("")
    for r in results:
        issues = r.review_result.get("issues", [])
        lines.append(f"## `{r.file_path}`\n")
        lines.append(f"Quality: {r.review_result.get('overall_quality', 'N/A')} | "
                     f"Issues: {len(issues)} | Tokens: {r.total_tokens:,}\n")
        if issues:
            for i, issue in enumerate(issues, 1):
                sev = issue.get("severity", "unknown").upper()
                lines.append(f"### {i}. [{sev}] {issue.get('type', '?')}: {issue.get('location', '?')}\n")
                lines.append(f"{issue.get('description', '?')}\n")
                lines.append(f"**Suggestion**: {issue.get('suggestion', '?')}\n")
        if r.fix_code:
            lines.append(f"### Fixed Code\n```{r.language}\n{r.fix_code}\n```\n")
        if r.verification:
            lines.append(f"**Decision**: {r.verification.get('final_decision', '?')} | "
                        f"Mergeable: {r.verification.get('can_merge', '?')}\n")
        lines.append("---\n")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # HTML
    from utils.output_formatter import to_html
    html = to_html(results, repo_path, branch, commit_msg)
    html_path = os.path.join(output_dir, f"review_{timestamp}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    console.print(f"\n[green]Results saved to: {output_dir}/[/green]")
    console.print(f"  - JSON: review_{timestamp}.json")
    console.print(f"  - Markdown: review_{timestamp}.md")
    console.print(f"  - HTML: review_{timestamp}.html")
