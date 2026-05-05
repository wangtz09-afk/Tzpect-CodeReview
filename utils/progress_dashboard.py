"""Real-time progress dashboard for reviews.

Uses Rich to display live progress bars, token usage, and estimated completion time.
"""
import time
from dataclasses import dataclass, field
from typing import Optional

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table
from rich.live import Live


@dataclass
class FileProgress:
    """Progress tracking for a single file."""
    file_path: str
    language: str
    status: str = "pending"  # pending, reviewing, fixing, testing, verifying, complete, error
    current_stage: str = ""
    issues_found: int = 0
    tokens_used: int = 0
    elapsed: float = 0.0
    error: str = ""


class ProgressDashboard:
    """Real-time progress dashboard for code reviews."""

    STAGE_ICONS = {
        "pending": "[dim]#[/dim]",
        "reviewing": "[cyan]>[/cyan]",
        "fixing": "[yellow]~[/yellow]",
        "testing": "[magenta]*[/magenta]",
        "verifying": "[blue]>>[/blue]",
        "complete": "[green]+[/green]",
        "error": "[red]![/red]",
    }

    def __init__(self, total_files: int, console: Optional[Console] = None):
        self.total_files = total_files
        self.console = console or Console()
        self.files: dict[str, FileProgress] = {}
        self.start_time = time.time()
        self.completed_count = 0
        self.error_count = 0
        self.total_tokens = 0
        self.total_issues = 0
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self.console,
            transient=True,
        )

    def start_file(self, file_path: str, language: str, index: int) -> None:
        """Mark a file as starting review."""
        self.files[file_path] = FileProgress(
            file_path=file_path,
            language=language,
            status="reviewing",
            current_stage="Review",
        )
        self._update_progress(index)

    def update_stage(self, file_path: str, stage: str, status: str = "") -> None:
        """Update the current stage for a file."""
        if file_path in self.files:
            self.files[file_path].current_stage = stage
            if status:
                self.files[file_path].status = status

    def complete_file(self, file_path: str, issues: int = 0, tokens: int = 0, elapsed: float = 0.0) -> None:
        """Mark a file as complete."""
        if file_path in self.files:
            fp = self.files[file_path]
            fp.status = "complete"
            fp.issues_found = issues
            fp.tokens_used = tokens
            fp.elapsed = elapsed
            fp.current_stage = "Done"
        self.completed_count += 1
        self.total_tokens += tokens
        self.total_issues += issues
        self._update_progress(self.completed_count + self.error_count)

    def error_file(self, file_path: str, error: str = "") -> None:
        """Mark a file as errored."""
        if file_path in self.files:
            self.files[file_path].status = "error"
            self.files[file_path].error = error
            self.files[file_path].current_stage = "Error"
        self.error_count += 1
        self._update_progress(self.completed_count + self.error_count)

    def _update_progress(self, completed: int) -> None:
        """Update the progress bar."""
        # This is called internally; the live display is handled by show()
        pass

    def render(self) -> Layout:
        """Render the current dashboard state."""
        layout = Layout()

        # Split into header, progress, and files
        layout.split_column(
            Layout(self._render_header(), name="header", size=3),
            Layout(self._render_progress(), name="progress", size=3),
            Layout(self._render_files(), name="files"),
        )

        return layout

    def _render_header(self) -> Panel:
        """Render header with summary."""
        elapsed = time.time() - self.start_time
        remaining = self._estimate_remaining()

        header = Table.grid()
        header.add_column(justify="left")
        header.add_column(justify="right")
        header.add_row("[bold]Files[/bold]", f"[green]{self.completed_count}[/green]/[bold]{self.total_files}[/bold] ({self.error_count} errors)")
        header.add_row("[bold]Tokens[/bold]", f"[cyan]{self.total_tokens:,}[/cyan]")
        header.add_row("[bold]Issues[/bold]", f"[yellow]{self.total_issues}[/yellow]")
        header.add_row("[bold]Time[/bold]", f"[dim]elapsed {elapsed:.0f}s | est. remaining {remaining:.0f}s[/dim]")

        return Panel(header, title="[bold]Code Review Progress[/bold]", border_style="blue")

    def _render_progress(self) -> Panel:
        """Render progress bar."""
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=40),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self.console,
            transient=False,
        )
        task_id = progress.add_task(
            "Reviewing...",
            total=self.total_files,
            completed=self.completed_count + self.error_count,
        )

        return Panel(progress, border_style="blue")

    def _render_files(self) -> Panel:
        """Render file list with status."""
        table = Table()
        table.add_column("Status", width=4)
        table.add_column("File")
        table.add_column("Language", width=12)
        table.add_column("Stage", width=12)
        table.add_column("Issues", width=6, justify="right")
        table.add_column("Tokens", width=8, justify="right")
        table.add_column("Time", width=8, justify="right")

        # Sort: active files first, then complete, then errors
        def sort_key(item):
            status_order = {"reviewing": 0, "fixing": 1, "testing": 2, "verifying": 3, "complete": 4, "error": 5, "pending": 6}
            return status_order.get(item.status, 99)

        sorted_files = sorted(self.files.values(), key=sort_key)

        for fp in sorted_files[:20]:  # Show max 20 files
            icon = self.STAGE_ICONS.get(fp.status, "•")
            style = "green" if fp.status == "complete" else "red" if fp.status == "error" else "cyan"

            table.add_row(
                f"[{style}]{icon}[/{style}]",
                fp.file_path[:50],
                fp.language,
                fp.current_stage,
                str(fp.issues_found) if fp.issues_found else "0",
                f"{fp.tokens_used:,}" if fp.tokens_used else "",
                f"{fp.elapsed:.1f}s" if fp.elapsed else "",
            )

        if len(self.files) > 20:
            table.add_row("", f"... and {len(self.files) - 20} more files", "", "", "", "", "")

        return Panel(table, title="Files", border_style="blue")

    def _estimate_remaining(self) -> float:
        """Estimate remaining time based on completed files."""
        completed = self.completed_count
        if completed == 0:
            return 0.0
        elapsed = time.time() - self.start_time
        avg_time_per_file = elapsed / completed
        remaining_files = self.total_files - (completed + self.error_count)
        return avg_time_per_file * remaining_files

    def print_summary(self) -> None:
        """Print final summary after review completes."""
        elapsed = time.time() - self.start_time

        summary = Table()
        summary.add_column("Metric")
        summary.add_column("Value", justify="right")

        summary.add_row("Files reviewed", str(self.total_files))
        summary.add_row("Completed", f"[green]{self.completed_count}[/green]")
        summary.add_row("Errors", f"[red]{self.error_count}[/red]")
        summary.add_row("Total issues", f"[yellow]{self.total_issues}[/yellow]")
        summary.add_row("Total tokens", f"{self.total_tokens:,}")
        summary.add_row("Total time", f"{elapsed:.1f}s")
        summary.add_row("Avg time/file", f"{elapsed / max(1, self.total_files):.1f}s")
        summary.add_row("Avg tokens/file", f"{self.total_tokens / max(1, self.total_files):,.0f}")

        self.console.print(Panel(summary, title="[bold]Review Summary[/bold]", border_style="green"))

    def callback(self, file_path: str, language: str, event: str, **kwargs) -> None:
        """Callback method compatible with parallel/sequential progress hooks.

        Usage: dashboard.callback(file_path, "python", "reviewing", index=0, total=5)
        """
        if event == "reviewing":
            self.start_file(file_path, language, kwargs.get("index", 0))
        elif event == "complete":
            self.complete_file(
                file_path,
                issues=kwargs.get("issues", 0),
                tokens=kwargs.get("tokens", 0),
                elapsed=kwargs.get("elapsed", 0.0),
            )
        elif event == "error":
            self.error_file(file_path, error=kwargs.get("error", ""))
