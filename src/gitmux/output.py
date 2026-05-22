"""Output formatting for serial and parallel execution."""

import sys

from rich.console import Console
from rich.panel import Panel

console = Console()

# Use ASCII-safe symbols on Windows with non-UTF-8 encoding
_OK = "[green]OK[/]" if sys.platform == "win32" else "[green]✓[/]"
_FAIL = "[red]FAIL[/]" if sys.platform == "win32" else "[red]✗[/]"


def print_step(repo_name: str, step: str) -> None:
    console.print(f"  [bold cyan]{repo_name}[/] -> [dim]{step}[/]")


def print_success(repo_name: str, output: str = "") -> None:
    console.print(f"  [bold cyan]{repo_name}[/] {_OK}")
    if output:
        for line in output.splitlines():
            console.print(f"    [dim]{line}[/]")


def print_error(repo_name: str, error: str) -> None:
    console.print(f"  [bold cyan]{repo_name}[/] {_FAIL} {error}")


def print_header(title: str) -> None:
    console.print(Panel(f"[bold]{title}[/]", expand=False))
