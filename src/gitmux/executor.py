"""Execution engine for git operations (serial and parallel)."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from gitmux.git_ops import GitResult
from gitmux.hooks import resolve_hooks, run_hooks
from gitmux.models import GitmuxConfig, GroupConfig, RepoConfig
from gitmux.output import console, print_error, print_header, print_step, print_success


@dataclass
class RepoResult:
    repo_name: str
    success: bool
    message: str


def _execute_one(
    repo: RepoConfig,
    group: GroupConfig,
    config: GitmuxConfig,
    operation: Callable[[RepoConfig, GroupConfig, GitmuxConfig], GitResult],
    op_name: str,
) -> RepoResult:
    """Execute pre-hook → operation → post-hook for a single repo."""
    path = config.get_repo_path(repo, group)
    hooks = resolve_hooks(repo, config)
    pre_cmds = getattr(hooks, f"pre_{op_name.lower()}", [])
    post_cmds = getattr(hooks, f"post_{op_name.lower()}", [])

    # Pre-hook
    if pre_cmds and path.exists():
        hook_result = run_hooks(pre_cmds, path, label=f"pre-{op_name.lower()}")
        if not hook_result.success:
            return RepoResult(repo.name, False, f"Pre-hook failed: {hook_result.failed_command}\n{hook_result.output}")

    # Git operation
    git_result = operation(repo, group, config)
    if not git_result.success:
        return RepoResult(repo.name, False, git_result.output)

    # Post-hook
    if post_cmds and path.exists():
        hook_result = run_hooks(post_cmds, path, label=f"post-{op_name.lower()}")
        if not hook_result.success:
            return RepoResult(repo.name, False, f"Post-hook failed: {hook_result.failed_command}\n{hook_result.output}")

    return RepoResult(repo.name, True, git_result.output)


def run_serial(
    config: GitmuxConfig,
    repos: list[tuple[RepoConfig, GroupConfig]],
    operation: Callable[[RepoConfig, GroupConfig, GitmuxConfig], GitResult],
    op_name: str,
) -> list[RepoResult]:
    """Execute an operation on repos serially with real-time output."""
    print_header(op_name)
    results: list[RepoResult] = []

    for repo, group in repos:
        print_step(repo.name, op_name.lower())
        result = _execute_one(repo, group, config, operation, op_name)
        if result.success:
            print_success(repo.name, result.message)
        else:
            print_error(repo.name, result.message)
        results.append(result)

    _print_summary(results)
    return results


def run_parallel(
    config: GitmuxConfig,
    repos: list[tuple[RepoConfig, GroupConfig]],
    operation: Callable[[RepoConfig, GroupConfig, GitmuxConfig], GitResult],
    op_name: str,
    max_workers: int = 4,
) -> list[RepoResult]:
    """Execute an operation on repos in parallel with progress bar."""
    results: list[RepoResult] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task(f"{op_name}...", total=len(repos))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_execute_one, repo, group, config, operation, op_name): repo.name
                for repo, group in repos
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                progress.advance(task)

    # Print detailed results
    console.print()
    for r in results:
        if r.success:
            console.print(f"  [bold cyan]{r.repo_name}[/] [green]✓[/]")
        else:
            console.print(f"  [bold cyan]{r.repo_name}[/] [red]✗[/] {r.message}")

    _print_summary(results)
    return results


def _print_summary(results: list[RepoResult]) -> None:
    success_count = sum(1 for r in results if r.success)
    fail_count = len(results) - success_count
    summary = f"\n[green]{success_count} succeeded[/]"
    if fail_count:
        summary += f", [red]{fail_count} failed[/]"
    console.print(summary)
