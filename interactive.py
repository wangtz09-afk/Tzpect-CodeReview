"""Tzpect-CodeReview interactive terminal menu mode.

User-friendly flow:
  1. Select an action (review / scan / fix / HTML report)
  2. Paste project path
  3. Select output format
  4. Select language filter (optional)
  5. Select severity filter (optional)
  6. Execute
"""
import os

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt, Confirm

from core.git_ops import (
    get_repo_path, is_git_repo, scan_source_files,
)
from core.pipeline import ReviewPipeline
from core.output import (
    filter_issues_by_severity, output_human, output_json, output_markdown,
    output_html, save_results,
)
from utils.logger import get_logger, get_log_path


console = Console()

# ── Action Menu ───────────────────────────────────────────────────────────────

MENU_ACTIONS = {
    "1": ("Review Changes (Git)", "Review committed code changes"),
    "2": ("Scan Files (Non-Git)", "Scan source files directly, no Git needed"),
    "3": ("Review + Fix Suggestions", "Review and generate AI fix suggestions"),
    "4": ("Generate HTML Report", "Review and generate an openable HTML report"),
}

MENU_OUTPUTS = {
    "1": ("Terminal (default)", False, False, False, None),
    "2": ("JSON", True, False, False, None),
    "3": ("Markdown", False, True, False, None),
    "4": ("HTML", False, False, True, None),
    "5": ("HTML + Save to File", False, False, True, "auto"),
}

MENU_LANGUAGES = {
    "1": ("No restriction", None),
    "2": ("Python", "python"),
    "3": ("Java", "java"),
    "4": ("JavaScript/TypeScript", "javascript,typescript"),
    "5": ("Go", "go"),
    "6": ("All listed languages", None),  # special marker
}

MENU_SEVERITY = {
    "1": ("All", None),
    "2": ("High (Critical+High)", "high"),
    "3": ("Medium+ (Critical+High+Medium)", "medium"),
    "4": ("Critical Only", "critical"),
}


def print_banner():
    """Print welcome panel."""
    console.print(Panel(
        "[bold cyan]Tzpect-CodeReview[/bold cyan] [dim]v1.0 Interactive Mode[/dim]\n\n"
        "Multi-agent collaborative code review tool\n"
        "Review → Fix → Test → Verify, fully automated\n\n"
        "[dim]Type [cyan]help[/cyan] for help | [cyan]quit[/cyan] to exit[/dim]",
        title="Welcome",
        border_style="blue",
    ))


def print_commands():
    """Print available commands."""
    console.print("\n[dim]Available commands:[/dim]")
    console.print("  [cyan]help[/cyan]    - Show this help")
    console.print("  [cyan]config[/cyan]  - View configuration status")
    console.print("  [cyan]review[/cyan]  - Review a Git project")
    console.print("  [cyan]scan[/cyan]    - Scan a non-Git project")
    console.print("  [cyan]fix[/cyan]     - Review and generate fix suggestions")
    console.print("  [cyan]html[/cyan]    - Generate HTML report")
    console.print("  [cyan]quit[/cyan]    - Exit")


def print_actions():
    """Print action menu."""
    console.print("\n[bold]Please select an action:[/bold]")
    for key, (name, desc) in MENU_ACTIONS.items():
        console.print(f"  [{key}] [cyan]{name}[/cyan] — {desc}")


def print_output_menu():
    """Print output format menu."""
    console.print("\n[bold]Please select output format:[/bold]")
    for key, (name, *_rest) in MENU_OUTPUTS.items():
        console.print(f"  [{key}] {name}")


def print_language_menu():
    """Print language filter menu."""
    console.print("\n[bold]Language filter (optional, Enter=no restriction):[/bold]")
    for key, (name, _lang) in MENU_LANGUAGES.items():
        console.print(f"  [{key}] {name}")


def print_severity_menu():
    """Print severity filter menu."""
    console.print("\n[bold]Severity filter (optional, Enter=all):[/bold]")
    for key, (name, _sev) in MENU_SEVERITY.items():
        console.print(f"  [{key}] {name}")


# ── Command Mapping ───────────────────────────────────────────────────────────

COMMAND_ACTION_MAP = {
    "review": "1",
    "scan": "2",
    "fix": "3",
    "html": "4",
}


def _get_action_choice():
    """Get user's selected action number (1-4)."""
    while True:
        choice = Prompt.ask(
            "\n[tzpect][bold]Tzpect[/bold]",
            default="",
        ).strip().lower()

        if not choice:
            print_actions()
            continue

        if choice in ("quit", "exit", "q"):
            console.print("[dim]Bye![/dim]")
            raise SystemExit(0)

        if choice in ("help", "h", "?"):
            print_commands()
            continue

        if choice in ("config", "c"):
            _show_config()
            continue

        # Check for command alias
        if choice in COMMAND_ACTION_MAP:
            return COMMAND_ACTION_MAP[choice]

        # Check for action number
        if choice in MENU_ACTIONS:
            return choice

        console.print(f"[red]Unknown command: {choice}, type [cyan]help[/cyan] for help[/red]")


def _get_repo_path():
    """Get and validate project path."""
    while True:
        path = Prompt.ask(
            "\nPlease enter project path",
            default=".",
        ).strip()

        if path.lower() in ("quit", "exit", "q"):
            console.print("[dim]Bye![/dim]")
            raise SystemExit(0)

        if not path:
            console.print("[yellow]Please enter a valid path[/yellow]")
            continue

        abs_path = os.path.abspath(path)
        if not os.path.exists(abs_path):
            console.print(f"[red]Path does not exist: {abs_path}[/red]")
            continue

        if not os.path.isdir(abs_path):
            console.print(f"[red]Not a directory: {abs_path}[/red]")
            continue

        console.print(f"[green]Project path: {abs_path}[/green]")
        return abs_path


def _get_output_choice():
    """Get output format selection."""
    print_output_menu()
    while True:
        out_choice = Prompt.ask("Output format", default="1").strip()
        if out_choice in MENU_OUTPUTS:
            name, fmt_json, fmt_md, fmt_html, save_html = MENU_OUTPUTS[out_choice]
            return fmt_json, fmt_md, fmt_html, save_html
        console.print("[yellow]Please enter a number 1-5[/yellow]")


def _get_language_choice():
    """Get language filter selection."""
    print_language_menu()
    while True:
        lang_choice = Prompt.ask("Language", default="1").strip()
        if lang_choice in MENU_LANGUAGES:
            _, language = MENU_LANGUAGES[lang_choice]
            return language
        console.print("[yellow]Please enter a number 1-6[/yellow]")


def _get_severity_choice():
    """Get severity filter selection."""
    print_severity_menu()
    while True:
        sev_choice = Prompt.ask("Severity", default="1").strip()
        if sev_choice in MENU_SEVERITY:
            _, severity = MENU_SEVERITY[sev_choice]
            return severity
        console.print("[yellow]Please enter a number 1-4[/yellow]")


def _show_config():
    """Show configuration status."""
    try:
        from utils.config_validator import ConfigValidator
        from config import get_settings
        settings = get_settings()
        validator = ConfigValidator(settings)
        validator.validate()
        summary = validator.get_summary()
        if "✅" in summary:
            console.print(f"[green]{summary}[/green]")
        else:
            console.print(f"[red]{summary}[/red]")
    except ImportError:
        console.print("[yellow]Configuration module unavailable[/yellow]")


def _run_review(repo_path, action_key, fmt_json, fmt_md, fmt_html, save_html, language, severity, max_files=20):
    """Execute the core review/scan/fix logic."""
    logger = get_logger()
    logger.setLevel("INFO")

    action_name = MENU_ACTIONS.get(action_key, ("Review", ""))[0]

    # Detect project type and changes
    repo_is_git = is_git_repo(repo_path)
    if repo_is_git and action_key in ("1", "3"):
        from core.git_ops import get_changes, get_current_branch, get_commit_message
        branch = get_current_branch(repo_path)
        commit_msg = get_commit_message(repo_path)
        changes = get_changes(repo_path)
        if not changes:
            console.print("[yellow]No code changes detected, switching to full scan mode...[/yellow]")
            changes = scan_source_files(repo_path, max_files=max_files)
        mode = "Review Changes"
    else:
        branch = "scan mode"
        commit_msg = ""
        changes = scan_source_files(repo_path, max_files=max_files)
        mode = "Scan Files"

    if not changes:
        console.print("[yellow]No reviewable source files found.[/yellow]")
        return

    # Language filter
    if language:
        changes = [c for c in changes if c.language not in ("unknown", "") and c.language.lower() == language.lower()]

    if not changes:
        console.print("[yellow]No files remaining after filter.[/yellow]")
        return

    # Show file list
    console.print(f"\n[green]Found {len(changes)} files:[/green]")
    for c in changes[:10]:
        console.print(f"  - {c.file_path} ({c.language})")
    if len(changes) > 10:
        console.print(f"  ... and {len(changes) - 10} more")

    # Execute
    console.print(f"\n[cyan]Starting {mode}...[/cyan]\n")
    pipeline = ReviewPipeline()
    from core.git_ops import ReviewContext
    context = ReviewContext(
        repo_path=repo_path, branch=branch, changes=changes, commit_message=commit_msg
    )
    results = pipeline.process_context(context)

    # Severity filter
    if severity:
        for r in results:
            issues = r.review_result.get("issues", [])
            r.review_result["issues"] = filter_issues_by_severity(issues, severity)

    # Output
    if save_html:
        output_dir = os.path.join(repo_path, "tzpect-results")
        save_results(results, output_dir, repo_path, branch, commit_msg)
        console.print(f"\n[bold green]HTML report saved: {output_dir}/[/bold green]")
        console.print(f"[dim]Double-click review_*.html to view[/dim]")
    elif fmt_html:
        output_html(results, repo_path, branch, commit_msg)
    elif fmt_json:
        output_json(results)
    elif fmt_md:
        output_markdown(results, repo_path, branch, commit_msg)
    else:
        output_human(results)

    # Log
    if get_log_path():
        console.print(f"\n[dim]Detailed log: {get_log_path()}[/dim]")


# ── Main Loop ─────────────────────────────────────────────────────────────────

def interactive():
    """Interactive menu mode."""
    print_banner()

    while True:
        try:
            # Step 1: Select action
            action_key = _get_action_choice()

            # Step 2: Enter project path
            repo_path = _get_repo_path()

            # Step 3: Select output format
            fmt_json, fmt_md, fmt_html, save_html = _get_output_choice()

            # Step 4: Select language filter
            language = _get_language_choice()

            # Step 5: Select severity filter
            severity = _get_severity_choice()

            # Step 6: Execute
            _run_review(
                repo_path=repo_path,
                action_key=action_key,
                fmt_json=fmt_json,
                fmt_md=fmt_md,
                fmt_html=fmt_html,
                save_html=save_html,
                language=language,
                severity=severity,
            )

        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Bye![/dim]")
            break
