"""AI Code Review & Intelligent Fix Agent — CLI Entry."""
import json
import os

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.git_ops import (
    get_repo_path, get_changes, get_commit_message, get_current_branch,
    ReviewContext, is_git_repo, scan_source_files,
)
from core.pipeline import ReviewPipeline, PipelineResult
from core.output import (
    filter_issues_by_severity, output_human, output_json, output_markdown,
    output_sarif, output_html, save_results,
)
from utils.logger import get_logger, get_log_path
from utils.config_validator import ConfigValidator


console = Console()


def _validate_config(settings: dict = None) -> bool:
    """Run configuration validation and print results."""
    if settings is None:
        from config import get_settings
        settings = get_settings()
    validator = ConfigValidator(settings)
    is_valid = validator.validate()
    summary = validator.get_summary()
    if is_valid:
        console.print(f"[green]{summary}[/green]")
    else:
        console.print(f"[red]{summary}[/red]")
    return is_valid


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """AI Code Review & Intelligent Fix Agent.

    Multi-agent collaborative automated code review tool.
    """
    if ctx.invoked_subcommand is None:
        try:
            from interactive import interactive as _interactive
            _interactive()
        except ImportError:
            console.print("[yellow]Interactive mode unavailable, please use a subcommand (e.g. review, scan). Use --help for all options.[/yellow]")


@cli.command()
def interactive():
    """Start interactive terminal menu mode."""
    try:
        from interactive import interactive as _interactive
        _interactive()
    except ImportError:
        console.print("[red]Interactive mode unavailable: cannot find interactive.py module.[/red]")
        raise SystemExit(1)


@cli.command()
@click.option("--test-connection", is_flag=True, help="Also test API connectivity")
def validate_config(test_connection):
    """Validate configuration and API access."""
    from config import get_settings
    settings = get_settings()

    is_valid = _validate_config(settings)

    if test_connection and is_valid:
        console.print("\n[cyan]Testing API connection...[/cyan]")
        validator = ConfigValidator(settings)
        result = validator.test_connection()
        if result.get("success"):
            console.print(f"[green]Connection successful[/green]")
            console.print(f"  Model: {result.get('model', 'unknown')}")
            console.print(f"  Tokens used: {result.get('tokens_used', 0)}")
        else:
            console.print(f"[red]Connection failed: {result.get('error')}[/red]")

    if not is_valid:
        raise SystemExit(1)


@cli.command()
@click.argument("file_path")
@click.argument("issue_type")
@click.argument("verdict", type=click.Choice(["accepted", "dismissed", "modified"]))
@click.option("--description", default="", help="Issue description")
@click.option("--severity", default="", help="Issue severity")
@click.option("--correction", default="", help="User's correction text")
def feedback(file_path, issue_type, verdict, description, severity, correction):
    """Record feedback on a review issue.

    FILE_PATH: File that was reviewed.
    ISSUE_TYPE: Type of issue (e.g., 'SQL Injection').
    VERDICT: 'accepted', 'dismissed', or 'modified'.
    """
    from utils.feedback_db import FeedbackDB
    db = FeedbackDB()
    db.add_feedback(
        file_path=file_path,
        issue_type=issue_type,
        verdict=verdict,
        issue_description=description,
        severity=severity,
        correction=correction,
    )
    console.print(f"[green]Feedback recorded: {file_path} → {issue_type} → {verdict}[/green]")


@cli.command()
@click.option("--project", default="", help="Filter by project path prefix")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def feedback_stats(project, output_json):
    """Show feedback statistics.

    Shows acceptance rate, false positive rate, and per-issue-type stats.
    """
    from utils.feedback_db import FeedbackDB
    db = FeedbackDB()
    stats = db.get_stats(project_filter=project)

    if output_json:
        console.print(json.dumps(db.export_stats(), ensure_ascii=False, indent=2))
        return

    table = Table()
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Total reviews", str(stats.total_reviews))
    table.add_row("Accepted", f"[green]{stats.accepted}[/green]")
    table.add_row("Dismissed", f"[red]{stats.dismissed}[/red]")
    table.add_row("Modified", f"[yellow]{stats.modified}[/yellow]")
    table.add_row("Acceptance rate", f"{stats.acceptance_rate:.1%}")
    table.add_row("False positive rate", f"{stats.false_positive_rate:.1%}")

    console.print(Panel(table, title="Feedback Statistics", border_style="blue"))

    if stats.type_stats:
        type_table = Table()
        type_table.add_column("Issue Type")
        type_table.add_column("Accepted", justify="right")
        type_table.add_column("Dismissed", justify="right")
        type_table.add_column("Modified", justify="right")
        for itype, s in sorted(stats.type_stats.items()):
            type_table.add_row(itype, str(s.get("accepted", 0)), str(s.get("dismissed", 0)), str(s.get("modified", 0)))
        console.print(Panel(type_table, title="Per-Issue-Type Stats", border_style="blue"))


def _apply_filters(changes, language_filter=None, max_files=20):
    """Filter changes by language and max count."""
    changes = [c for c in changes if c.language not in ("unknown", "")]
    if language_filter:
        langs = {l.strip().lower() for l in language_filter.split(",")}
        changes = [c for c in changes if c.language.lower() in langs]
    return changes[:max_files]


def _output_results(results, repo_path, branch, commit_msg, *, fmt_json=False, fmt_md=False, fmt_sarif=False, fmt_html=False, output_dir=None, compact=False):
    """Output review results in the requested format."""
    if fmt_json:
        output_json(results)
    elif fmt_md:
        output_markdown(results, repo_path, branch, commit_msg)
    elif fmt_sarif:
        output_sarif(results, repo_path, branch)
    elif fmt_html:
        output_html(results, repo_path, branch, commit_msg)
    else:
        output_human(results, compact=compact)

    if output_dir:
        save_results(results, output_dir, repo_path, branch, commit_msg)


@cli.command()
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option("--staged", is_flag=True, help="Only review staged changes")
@click.option("--since", default=None, help="Review changes since a commit, e.g. HEAD~3")
@click.option("--json", "fmt_json", is_flag=True, help="Output as JSON")
@click.option("--markdown", "fmt_md", is_flag=True, help="Output as Markdown")
@click.option("--sarif", "fmt_sarif", is_flag=True, help="Output as SARIF (GitHub Code Scanning)")
@click.option("--html", "fmt_html", is_flag=True, help="Output as HTML report")
@click.option("--max-files", default=20, help="Max files to review")
@click.option("--severity", default=None, help="Min severity to display: critical|high|medium|low")
@click.option("--language", default=None, help="Only review specific languages, comma-separated")
@click.option("--output-dir", default=None, help="Save results to directory")
@click.option("--parallel", is_flag=True, help="Enable parallel processing")
@click.option("--workers", default=3, type=int, help="Parallel worker threads (default 3)")
@click.option("--checkpoint-dir", default=None, help="Checkpoint directory for resume")
@click.option("--resume", is_flag=True, help="Resume from last checkpoint")
@click.option("--budget", default=None, type=float, help="Max budget in USD (stops when exceeded)")
@click.option("--rate-limit", default=1.0, type=float, help="API rate limit (calls/sec)")
@click.option("--verbose", is_flag=True, help="Show detailed debug logs")
@click.option("--no-context", is_flag=True, help="Disable project context detection")
@click.option("--no-custom-rules", is_flag=True, help="Disable custom rules (.codereview.yml)")
@click.option("--no-cross-file", is_flag=True, help="Disable cross-file analysis")
@click.option("--no-fix-quality", is_flag=True, help="Disable fix quality assessment")
@click.option("--no-feedback", is_flag=True, help="Disable feedback learning")
@click.option("--collect-feedback", is_flag=True, help="Collect feedback on review results")
@click.option("--progress", is_flag=True, help="Show progress dashboard")
@click.option("--incremental", is_flag=True, help="Only review changed lines (saves tokens)")
@click.option("--compact", is_flag=True, help="Compact summary output (table format)")
def review(
    path, staged, since, fmt_json, fmt_md, fmt_sarif, fmt_html,
    max_files, severity, language, output_dir, parallel, workers,
    checkpoint_dir, resume, budget, rate_limit, verbose,
    no_context, no_custom_rules, no_cross_file, no_fix_quality, no_feedback,
    collect_feedback, progress, incremental, compact,
):
    """Review code changes in a repository.

    PATH: Repository path (default: current directory).
    """
    # Initialize logging
    logger = get_logger()
    if verbose:
        logger.setLevel("DEBUG")

    repo_path = get_repo_path(path)
    branch = get_current_branch(repo_path)
    commit_msg = get_commit_message(repo_path)

    console.print(Panel(
        f"[bold]Tzpect-CodeReview[/bold]\n"
        f"Project: {repo_path}\n"
        f"Branch: {branch}"
        + (f"\nLanguage filter: {language}" if language else "")
        + (f"\nMin severity: {severity}" if severity else "")
        + (f"\nParallel: {workers} workers" if parallel else "")
        + (f"\nBudget: ${budget}" if budget else "")
        + (f"\nCheckpoint: {'resume' if resume else 'new'}" if checkpoint_dir else "")
        + (f"\nLog: {get_log_path()}" if get_log_path() else ""),
        title="Tzpect-CodeReview",
    ))

    # Get changes
    repo_is_git = is_git_repo(repo_path)
    if repo_is_git:
        changes = get_changes(repo_path, staged=staged, since_commit=since)
    else:
        changes = scan_source_files(repo_path, max_files=max_files)
    if not changes:
        console.print("[yellow]No code changes detected.[/yellow]")
        return

    # Apply filters
    changes = _apply_filters(changes, language, max_files)
    if not changes:
        console.print("[yellow]No reviewable source files found.[/yellow]")
        return

    console.print(f"\n[green]Found {len(changes)} files to review:[/green]")
    for c in changes:
        console.print(f"  - {c.file_path} ({c.language})")

    # Setup optional features
    checkpoint_mgr = None
    cost_tracker = None

    if checkpoint_dir or resume:
        from utils.checkpoint import CheckpointManager
        checkpoint_mgr = CheckpointManager(checkpoint_dir)
        if resume:
            checkpoint_mgr.save_metadata(total_files=len(changes))

    if budget:
        from utils.cost_tracker import CostTracker
        cost_tracker = CostTracker(budget=budget)

    # Run pipeline
    console.print("\n[cyan]Starting review...[/cyan]\n")

    if parallel:
        from utils.parallel import ParallelReviewer
        from utils.rate_limiter import RateLimiter
        limiter = RateLimiter(
            calls_per_second=rate_limit,
            burst_capacity=max(1, int(rate_limit * 2)),
        )
        reviewer = ParallelReviewer(
            max_workers=workers,
            rate_limiter=limiter,
            checkpoint_manager=checkpoint_mgr,
            cost_tracker=cost_tracker,
        )
        context = ReviewContext(
            repo_path=repo_path, branch=branch, changes=changes, commit_message=commit_msg
        )
        results = reviewer.process_files(context)
    else:
        pipeline = ReviewPipeline(
            repo_path=repo_path,
            enable_context=not no_context,
            enable_custom_rules=not no_custom_rules,
            enable_cross_file=not no_cross_file,
            enable_fix_quality=not no_fix_quality,
            enable_feedback=not no_feedback,
            incremental=incremental,
        )
        # Initialize all components
        pipeline.initialize(changes)
        context = ReviewContext(
            repo_path=repo_path, branch=branch, changes=changes, commit_message=commit_msg
        )

        # Optionally show progress dashboard
        if progress:
            from utils.progress_dashboard import ProgressDashboard
            dashboard = ProgressDashboard(total_files=len(changes))
            results = pipeline.process_context(
                context,
                on_progress=dashboard.callback,
            )
            dashboard.print_summary()
        else:
            results = pipeline.process_context(context)

    # Apply severity filter for display
    if severity:
        for r in results:
            issues = r.review_result.get("issues", [])
            r.review_result["issues"] = filter_issues_by_severity(issues, severity)

    # Cost summary
    if cost_tracker:
        console.print(f"\n[cost]{cost_tracker.get_detailed_summary()}[/cost]")

    # Log path
    if get_log_path():
        console.print(f"\n[dim]Detailed log: {get_log_path()}[/dim]")

    # Output results
    _output_results(results, repo_path, branch, commit_msg,
                    fmt_json=fmt_json, fmt_md=fmt_md, fmt_sarif=fmt_sarif,
                    fmt_html=fmt_html, output_dir=output_dir, compact=compact)


@cli.command()
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option("--json", "fmt_json", is_flag=True, help="Output as JSON")
@click.option("--markdown", "fmt_md", is_flag=True, help="Output as Markdown")
@click.option("--html", "fmt_html", is_flag=True, help="Output as HTML report")
@click.option("--max-files", default=20, help="Max files to scan")
@click.option("--severity", default=None, help="Min severity to display")
@click.option("--language", default=None, help="Only review specific languages")
@click.option("--output-dir", default=None, help="Save results to directory")
@click.option("--compact", is_flag=True, help="Compact summary output")
def scan(path, fmt_json, fmt_md, fmt_html, max_files, severity, language, output_dir, compact):
    """Scan and review source files in non-Git projects.

    Directly scans source files without Git.
    PATH: Project path (default: current directory).
    """
    repo_path = os.path.abspath(path)

    console.print(Panel(
        f"[bold]Tzpect-CodeReview[/bold]\n"
        f"Project: {repo_path}\n"
        f"Mode: Direct Scan\n"
        f"Max files: {max_files}",
        title="Tzpect-CodeReview [SCAN]",
    ))

    changes = scan_source_files(repo_path, max_files=max_files)
    if not changes:
        console.print("[yellow]No source files found.[/yellow]")
        return

    changes = _apply_filters(changes, language, max_files)
    if not changes:
        console.print("[yellow]No reviewable source files found.[/yellow]")
        return

    console.print(f"\n[green]Found {len(changes)} source files:[/green]")
    by_lang: dict = {}
    for c in changes:
        by_lang.setdefault(c.language, []).append(c.file_path)
    for lang, files in sorted(by_lang.items()):
        console.print(f"  [cyan]{lang}[/cyan] ({len(files)} files)")
        for f in files[:5]:
            console.print(f"    - {f}")
        if len(files) > 5:
            console.print(f"    ... and {len(files) - 5} more")

    console.print("\n[cyan]Starting review...[/cyan]\n")
    pipeline = ReviewPipeline()
    context = ReviewContext(
        repo_path=repo_path, branch="scan mode", changes=changes, commit_message=""
    )
    results = pipeline.process_context(context)

    if severity:
        for r in results:
            issues = r.review_result.get("issues", [])
            r.review_result["issues"] = filter_issues_by_severity(issues, severity)

    if fmt_json:
        output_json(results)
    elif fmt_md:
        output_markdown(results, repo_path, "scan mode", "")
    elif fmt_html:
        output_html(results, repo_path, "scan mode", "")
    else:
        output_human(results, compact=compact)

    if output_dir:
        save_results(results, output_dir, repo_path, "scan mode", "")


@cli.command()
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option("--staged", is_flag=True)
@click.option("--since", default=None)
@click.option("--all", "scan_all", is_flag=True, help="Scan all source files")
@click.option("--language", default=None, help="Only review specific languages")
@click.option("--max-files", default=50, help="Max files to scan")
def fix(path, staged, since, scan_all, language, max_files):
    """Review and automatically fix code issues."""
    repo_path = get_repo_path(path)
    branch = get_current_branch(repo_path)
    commit_msg = get_commit_message(repo_path)

    if scan_all or not is_git_repo(repo_path):
        changes = scan_source_files(repo_path, max_files=max_files)
    else:
        changes = get_changes(repo_path, staged=staged, since_commit=since)
        if not changes:
            changes = scan_source_files(repo_path, max_files=max_files)
    changes = _apply_filters(changes, language, max_files)

    if not changes:
        console.print("[yellow]No code changes detected.[/yellow]")
        return

    console.print(Panel(
        f"[bold]AI Code Review & Fix Agent[/bold]\n"
        f"Files: {len(changes)}",
        title="Code Review & Fix",
    ))

    pipeline = ReviewPipeline()
    context = ReviewContext(
        repo_path=repo_path, branch=branch, changes=changes, commit_message=commit_msg
    )
    results = pipeline.process_context(context)

    _output_human(results)

    fixed_files = [r for r in results if r.fix_code]
    if fixed_files:
        console.print(f"\n[bold green]Fix suggestions for {len(fixed_files)} files:[/bold green]")
        for r in fixed_files:
            console.print(f"  - {r.file_path}")
            if r.verification:
                decision = r.verification.get("final_decision", "?")
                can_merge = r.verification.get("can_merge", False)
                console.print(f"    Decision: {decision} | Mergeable: {can_merge}")
                console.print(f"    Tokens: {r.total_tokens}")
                console.print()


@cli.command()
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option("--staged", is_flag=True, help="Only review staged changes")
@click.option("--since", default=None, help="Review changes since a commit")
@click.option("--all", "scan_all", is_flag=True, help="Scan all source files (ignore git state)")
@click.option("--dry-run", is_flag=True, help="Preview only, don't modify files")
@click.option("--force", is_flag=True, help="Skip confirmation")
@click.option("--language", default=None, help="Only review specific languages")
@click.option("--max-files", default=50, help="Max files to scan")
def apply_fixes(path, staged, since, scan_all, dry_run, force, language, max_files):
    """Review code and apply fixes to source files.

    Writes AI-generated fixes back to source files.
    By default, shows diff for confirmation (--force skips, --dry-run previews only).

    By default, reviews git changes. Use --all to scan all source files.
    """
    import difflib

    repo_path = get_repo_path(path)
    branch = get_current_branch(repo_path)
    commit_msg = get_commit_message(repo_path)

    # Determine which files to review
    if scan_all or not is_git_repo(repo_path):
        # Full scan mode (non-git or --all flag)
        changes = scan_source_files(repo_path, max_files=max_files)
    else:
        # Git change mode
        changes = get_changes(repo_path, staged=staged, since_commit=since)
        if not changes:
            # Git repo but no changes — fall through to scan if requested
            changes = scan_source_files(repo_path, max_files=max_files)

    changes = _apply_filters(changes, language, max_files)

    if not changes:
        console.print("[yellow]No code changes detected.[/yellow]")
        return

    console.print(Panel(
        f"[bold]AI Code Fix (Apply Fixes)[/bold]\n"
        f"Files: {len(changes)}\n"
        f"Mode: {'Preview' if dry_run else 'Apply'}",
        title="Apply Fixes",
    ))

    pipeline = ReviewPipeline()
    context = ReviewContext(
        repo_path=repo_path, branch=branch, changes=changes, commit_message=commit_msg
    )
    results = pipeline.process_context(context)

    fixed_results = [r for r in results if r.fix_code]
    if not fixed_results:
        console.print("\n[yellow]No fix suggestions generated.[/yellow]")
        return

    console.print(f"\n[cyan]{len(fixed_results)} files have fix suggestions:[/cyan]")
    for r in fixed_results:
        console.print(f"  - {r.file_path} ({len(r.fix_code)} chars)")

    if not dry_run and not force:
        console.print("\n[bold]Fix diffs:[/bold]\n")
        for r in fixed_results:
            full_path = os.path.join(repo_path, r.file_path)
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    original = f.read()
            except Exception:
                continue

            diff = list(difflib.unified_diff(
                original.splitlines(keepends=True),
                r.fix_code.splitlines(keepends=True),
                fromfile=f"a/{r.file_path}",
                tofile=f"b/{r.file_path}",
                n=3,
            ))
            if diff:
                console.print(Panel("".join(diff[:50]), title=r.file_path, border_style="yellow"))

        if not click.confirm("Apply these fixes to source files?"):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    applied = 0
    auto_collected = 0
    for r in fixed_results:
        full_path = os.path.join(repo_path, r.file_path)
        if not os.path.exists(full_path):
            console.print(f"  [yellow]Skipped (file not found): {full_path}[/yellow]")
            continue

        if dry_run:
            console.print(f"  [cyan][Preview] Would write: {full_path}[/cyan]")
        else:
            try:
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(r.fix_code)
                applied += 1
                console.print(f"  [green]Applied: {r.file_path}[/green]")

                # Auto-collect feedback: user accepted this issue by applying the fix
                from utils.feedback_db import FeedbackDB
                db = FeedbackDB()
                issues = r.review_result.get("issues", [])
                applied_types = set()
                skipped_types = set()
                for issue in issues:
                    issue_type = issue.get("type", "Unknown")
                    # All issues that had fixes applied are "accepted"
                    applied_types.add(issue_type)
                auto_collected += db.auto_collect(
                    file_path=r.file_path,
                    issues=issues,
                    applied_issue_types=applied_types,
                    skipped_issue_types=skipped_types,
                    modified_issue_types=set(),
                )
            except Exception as e:
                console.print(f"  [red]Write failed {r.file_path}: {e}[/red]")

    if auto_collected:
        console.print(f"  [dim]Auto-collected {auto_collected} feedback entries from apply-fixes[/dim]")

    if dry_run:
        console.print(f"\n[cyan]Preview mode — {len(fixed_results)} files will be fixed.[/cyan]")
    else:
        console.print(f"\n[bold green]Done! Applied {applied}/{len(fixed_results)} fixes.[/bold green]")


@cli.command()
@click.option("--config", default=None, help="Path to .codereview.yml (default: project root)")
@click.option("--output", default=None, help="Write rules to this file instead of .codereview.yml")
@click.option("--dry-run", is_flag=True, help="Preview generated rules without writing")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def tune_rules(config, output, dry_run, output_json):
    """Auto-generate review rules from accumulated feedback.

    Analyzes feedback patterns and produces suppress/prioritize rules
    that are written to .codereview.yml's auto_tuned section.

    Run this periodically to keep rules up to date as feedback accumulates.
    """
    from utils.auto_tuner import AutoTuner

    db_path = None
    if config:
        db_path = config

    tuner = AutoTuner(db_path)
    tuned_config = tuner.tune()

    if output_json:
        import json
        data = {
            "suppress": [
                {
                    "issue_type": r.issue_type,
                    "file_category": r.file_category,
                    "confidence": round(r.confidence, 3),
                    "dismissed_count": r.dismissed_count,
                    "total_count": r.total_count,
                    "reason": r.reason,
                }
                for r in tuned_config.suppress
            ],
            "prioritize": [
                {
                    "issue_type": r.issue_type,
                    "file_category": r.file_category,
                    "confidence": round(r.confidence, 3),
                    "accepted_count": r.accepted_count,
                    "total_count": r.total_count,
                    "reason": r.reason,
                }
                for r in tuned_config.prioritize
            ],
        }
        console.print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    yaml_output = tuned_config.to_yaml()

    if dry_run:
        console.print("[cyan]Generated rules (preview):[/cyan]")
        console.print(yaml_output)
        return

    target = output
    if not target:
        # Find project root or current directory
        target = os.path.join(os.getcwd(), ".codereview.yml")

    tuner2 = AutoTuner(db_path)
    success = tuner2.apply_to_file(target)
    if success:
        console.print(f"[green]Wrote {len(tuned_config.suppress)} suppress + {len(tuned_config.prioritize)} prioritize rules to {target}[/green]")
    else:
        console.print("[yellow]No rules generated (insufficient feedback data).[/yellow]")


@cli.command()
@click.option("--export", "export_path", default=None, help="Export learned patterns to this JSON file")
@click.option("--import", "import_path", default=None, help="Import learned patterns from this JSON file")
def share_knowledge(export_path, import_path):
    """Export or import learned knowledge patterns across projects.

    Export creates a JSON file with all learned patterns.
    Import merges patterns from a JSON file into the local database.
    """
    from utils.feedback_db import FeedbackDB

    db = FeedbackDB()

    if export_path:
        data = db.export_knowledge()
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        console.print(f"[green]Exported {len(data['learned_patterns'])} learned patterns to {export_path}[/green]")
        console.print(f"  Total reviews in dataset: {data['stats']['total_reviews']}")
        console.print(f"  Acceptance rate: {data['stats']['acceptance_rate']:.1%}")

    elif import_path:
        try:
            with open(import_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            imported = db.import_knowledge(data)
            console.print(f"[green]Imported {imported} learned patterns from {import_path}[/green]")
        except FileNotFoundError:
            console.print(f"[red]File not found: {import_path}[/red]")
        except json.JSONDecodeError:
            console.print(f"[red]Invalid JSON in {import_path}[/red]")
    else:
        console.print("[yellow]Specify --export <file> or --import <file>[/yellow]")


if __name__ == "__main__":
    cli()
