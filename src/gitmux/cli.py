"""gitmux CLI entry point."""

from pathlib import Path

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from gitmux import __version__
from gitmux.config import DEFAULT_CONFIG_PATH, find_config, load_config, save_config, validate_config
from gitmux.models import GitmuxConfig, GroupConfig, RepoConfig

app = typer.Typer(name="gitmux", help="Manage multiple git repositories with ease.", no_args_is_help=True)
group_app = typer.Typer(name="group", help="Manage repository groups.")
app.add_typer(group_app, name="group")

console = Console()

CONFIG_OPT = typer.Option(None, "--config", "-c", help="Path to config file.")


def _load(config_path: Path | None) -> GitmuxConfig:
    path = Path(config_path) if config_path else find_config()
    if not path.exists():
        rprint(f"[red]Config not found: {path}[/]\nRun [bold]gitmux init[/] first.")
        raise typer.Exit(1)
    cfg = load_config(path)
    errors = validate_config(cfg)
    if errors:
        for e in errors:
            rprint(f"[red]Config error:[/] {e}")
        raise typer.Exit(1)
    return cfg


def _save(config: GitmuxConfig, config_path: Path | None) -> None:
    save_config(config, Path(config_path) if config_path else find_config())


def version_callback(value: bool) -> None:
    if value:
        rprint(f"gitmux [bold green]{__version__}[/]")
        raise typer.Exit()


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Manage multiple git repositories with ease."""


@app.command()
def init(
    workspace: str = typer.Option("~/projects", prompt="Workspace directory"),
    global_: bool = typer.Option(False, "--global", "-g", help="Create global config at ~/.gitmux.yaml"),
) -> None:
    """Initialize a new .gitmux.yaml configuration file."""
    path = DEFAULT_CONFIG_PATH if global_ else Path.cwd() / ".gitmux.yaml"
    if path.exists():
        overwrite = typer.confirm(f"{path} already exists. Overwrite?", default=False)
        if not overwrite:
            raise typer.Exit()
    cfg = GitmuxConfig(workspace=workspace)
    save_config(cfg, path)
    rprint(f"[green]Config created:[/] {path}")


@app.command()
def add(
    url: str = typer.Argument(..., help="Git repository URL."),
    group: str = typer.Option("default", "--group", "-g", help="Group to add the repo to."),
    name: str | None = typer.Option(None, "--name", "-n", help="Repo name (default: derived from URL)."),
    template: str | None = typer.Option(None, "--template", "-t", help="Hook template to use."),
    config: Path | None = CONFIG_OPT,
) -> None:
    """Add a repository to the configuration."""
    cfg = _load(config)
    repo_name = name or url.rstrip("/").split("/")[-1].removesuffix(".git")
    if cfg.find_repo(repo_name):
        rprint(f"[red]Repo '{repo_name}' already exists.[/]")
        raise typer.Exit(1)

    grp = cfg.find_group(group)
    if not grp:
        grp = GroupConfig(name=group)
        cfg.groups.append(grp)
        rprint(f"[dim]Created group:[/] {group}")

    if template and template not in cfg.templates:
        rprint(f"[red]Template '{template}' not found.[/]")
        raise typer.Exit(1)

    repo = RepoConfig(name=repo_name, url=url, template=template)
    grp.repos.append(repo)
    _save(cfg, config)
    rprint(f"[green]Added[/] {repo_name} to group '{group}'")


@app.command()
def remove(
    name: str = typer.Argument(..., help="Repository name to remove."),
    config: Path | None = CONFIG_OPT,
) -> None:
    """Remove a repository from the configuration."""
    cfg = _load(config)
    result = cfg.find_repo(name)
    if not result:
        rprint(f"[red]Repo '{name}' not found.[/]")
        raise typer.Exit(1)
    repo, grp = result
    grp.repos.remove(repo)
    _save(cfg, config)
    rprint(f"[green]Removed[/] {name} from group '{grp.name}'")


@app.command(name="list")
def list_repos(
    group: str | None = typer.Option(None, "--group", "-g", help="Filter by group."),
    config: Path | None = CONFIG_OPT,
) -> None:
    """List all configured repositories."""
    cfg = _load(config)
    table = Table(title="Repositories")
    table.add_column("Group", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("URL")
    table.add_column("Path")
    table.add_column("Template", style="dim")

    for grp in cfg.groups:
        if group and grp.name != group:
            continue
        for repo in grp.repos:
            path = str(cfg.get_repo_path(repo, grp))
            table.add_row(grp.name, repo.name, repo.url, path, repo.template or "")

    console.print(table)


# --- Group subcommands ---


DEFAULT_GROUP = "default"


def _get_repos(cfg: GitmuxConfig, target: str | None, all_: bool, group: str | None = None) -> list[tuple]:
    """Resolve target repos.

    - target = "name" → find repo in default group
    - target = "group/name" → find repo in specified group
    - --group = operate on entire group
    - --all = all repos
    - nothing = error
    """
    if target:
        if "/" in target:
            group_name, repo_name = target.split("/", 1)
        else:
            group_name, repo_name = DEFAULT_GROUP, target
        grp = cfg.find_group(group_name)
        if not grp:
            rprint(f"[red]Group '{group_name}' not found.[/]")
            raise typer.Exit(1)
        for repo in grp.repos:
            if repo.name == repo_name:
                return [(repo, grp)]
        rprint(f"[red]Repo '{repo_name}' not found in group '{group_name}'.[/]")
        raise typer.Exit(1)
    if group:
        grp = cfg.find_group(group)
        if not grp:
            rprint(f"[red]Group '{group}' not found.[/]")
            raise typer.Exit(1)
        return [(r, grp) for r in grp.repos]
    if all_:
        return cfg.all_repos()
    rprint("[red]Please specify a repo, --group, or --all.[/]")
    raise typer.Exit(1)


@app.command()
def clone(
    target: str | None = typer.Argument(None, help="Repo name or group/repo."),
    group: str | None = typer.Option(None, "--group", "-g", help="Operate on entire group."),
    all_: bool = typer.Option(False, "--all", "-a", help="Operate on all repositories."),
    parallel: bool = typer.Option(False, "--parallel", "-p", help="Run in parallel."),
    config: Path | None = CONFIG_OPT,
) -> None:
    """Clone repositories that haven't been cloned yet."""
    from gitmux import git_ops
    from gitmux.executor import run_parallel, run_serial

    cfg = _load(config)
    repos = _get_repos(cfg, target, all_, group)

    def do_clone(repo, grp, c):
        path = c.get_repo_path(repo, grp)
        if path.exists():
            return git_ops.GitResult(True, "Already cloned", "skip")
        return git_ops.clone(repo.url, path)

    (run_parallel if parallel else run_serial)(cfg, repos, do_clone, "Clone")


@app.command()
def fetch(
    target: str | None = typer.Argument(None, help="Repo name or group/repo."),
    group: str | None = typer.Option(None, "--group", "-g", help="Operate on entire group."),
    all_: bool = typer.Option(False, "--all", "-a", help="Operate on all repositories."),
    parallel: bool = typer.Option(False, "--parallel", "-p", help="Run in parallel."),
    show_branches: bool = typer.Option(False, "--branches", help="Show remote branches after fetch."),
    config: Path | None = CONFIG_OPT,
) -> None:
    """Fetch latest remote data for repositories."""
    from gitmux import git_ops
    from gitmux.executor import run_parallel as run_par
    from gitmux.executor import run_serial

    cfg = _load(config)
    repos = _get_repos(cfg, target, all_, group)

    def do_fetch(repo, grp, c):
        path = c.get_repo_path(repo, grp)
        if not path.exists():
            return git_ops.GitResult(False, f"Not cloned: {path}", "git fetch")
        result = git_ops.fetch(path)
        if result.success and show_branches:
            branches = git_ops.list_remote_branches(path, "*")
            result = git_ops.GitResult(True, "\n".join(branches) if branches else "(no remote branches)", result.command)
        return result

    (run_par if parallel else run_serial)(cfg, repos, do_fetch, "Fetch")


@app.command()
def pull(
    target: str | None = typer.Argument(None, help="Repo name or group/repo."),
    group: str | None = typer.Option(None, "--group", "-g", help="Operate on entire group."),
    all_: bool = typer.Option(False, "--all", "-a", help="Operate on all repositories."),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch alias, e.g. 'dev', 'prod:latest', 'prod:~20260520', 'prod:20260524'."),
    parallel: bool = typer.Option(False, "--parallel", "-p", help="Run in parallel."),
    config: Path | None = CONFIG_OPT,
) -> None:
    """Pull latest changes for repositories."""
    from gitmux import git_ops
    from gitmux.executor import run_parallel as run_par
    from gitmux.executor import run_serial

    cfg = _load(config)
    repos = _get_repos(cfg, target, all_, group)

    # Parse --branch flag: "name" or "name:value"
    branch_alias: str | None = None
    branch_value: str | None = None
    if branch:
        if ":" in branch:
            branch_alias, branch_value = branch.split(":", 1)
        else:
            branch_alias = branch

    def do_pull(repo, grp, c):
        path = c.get_repo_path(repo, grp)
        if not path.exists():
            return git_ops.GitResult(False, f"Not cloned: {path}", "git pull")

        if not branch_alias:
            return git_ops.pull(path)

        # Resolve branch from config
        if branch_alias not in repo.branches:
            return git_ops.GitResult(
                False, f"Branch alias '{branch_alias}' not configured", "branch resolve"
            )

        pattern = repo.branches[branch_alias]
        is_pattern = "*" in pattern

        if branch_value is None:
            # gitmux pull --branch dev → must be fixed
            if is_pattern:
                return git_ops.GitResult(
                    False,
                    f"'{branch_alias}' is a pattern ({pattern}), use --branch {branch_alias}:latest or --branch {branch_alias}:<value>",
                    "branch resolve",
                )
            target = pattern
        elif branch_value == "latest":
            # gitmux pull --branch prod:latest → must be pattern
            if not is_pattern:
                return git_ops.GitResult(
                    False,
                    f"'{branch_alias}' is a fixed branch ({pattern}), use --branch {branch_alias} directly",
                    "branch resolve",
                )
            fetch_result = git_ops.fetch(path)
            if not fetch_result.success:
                return fetch_result
            matches = git_ops.list_remote_branches(path, pattern)
            if not matches:
                return git_ops.GitResult(False, f"No remote branch matching '{pattern}'", "branch resolve")
            target = matches[0]  # sorted by committerdate, newest first
        elif branch_value.startswith("~"):
            # gitmux pull --branch prod:~20260520 → find latest branch with date <= 20260520
            if not is_pattern:
                return git_ops.GitResult(
                    False,
                    f"'{branch_alias}' is a fixed branch ({pattern}), use --branch {branch_alias} directly",
                    "branch resolve",
                )
            date_str = branch_value[1:]
            # Normalize to 6-digit date for comparison (YYMMDD)
            if len(date_str) == 8:
                date_str = date_str[2:]
            fetch_result = git_ops.fetch(path)
            if not fetch_result.success:
                return fetch_result
            matches = git_ops.list_remote_branches(path, pattern)
            if not matches:
                return git_ops.GitResult(False, f"No remote branch matching '{pattern}'", "branch resolve")
            # Extract date from branch names and find <= date_str
            import re as _re
            candidates = []
            for m in matches:
                found = _re.search(r"(\d{6})", m)
                if found and found.group(1) <= date_str:
                    candidates.append(m)
            if not candidates:
                return git_ops.GitResult(
                    False,
                    f"No branch matching '{pattern}' with date <= {date_str} (found: {matches[:5]})",
                    "branch resolve",
                )
            target = candidates[0]  # already sorted by committerdate newest first
        else:
            # gitmux pull --branch prod:20260524 → replace * with value
            if not is_pattern:
                return git_ops.GitResult(
                    False,
                    f"'{branch_alias}' is a fixed branch ({pattern}), use --branch {branch_alias} directly",
                    "branch resolve",
                )
            target = pattern.replace("*", branch_value)

        # Fetch if not already done
        if branch_value != "latest":
            fetch_result = git_ops.fetch(path)
            if not fetch_result.success:
                return fetch_result

        # Checkout and pull
        checkout_result = git_ops.checkout(path, target)
        if not checkout_result.success:
            return git_ops.GitResult(False, f"Checkout failed: {checkout_result.output}", f"git checkout {target}")

        pull_result = git_ops.pull(path)
        msg = f"[{target}] {pull_result.output}"
        return git_ops.GitResult(pull_result.success, msg, pull_result.command)

    (run_par if parallel else run_serial)(cfg, repos, do_pull, "Pull")



@app.command()
def push(
    target: str | None = typer.Argument(None, help="Repo name or group/repo."),
    group: str | None = typer.Option(None, "--group", "-g", help="Operate on entire group."),
    all_: bool = typer.Option(False, "--all", "-a", help="Operate on all repositories."),
    parallel: bool = typer.Option(False, "--parallel", "-p", help="Run in parallel."),
    config: Path | None = CONFIG_OPT,
) -> None:
    """Push local commits for repositories."""
    from gitmux import git_ops
    from gitmux.executor import run_parallel, run_serial

    cfg = _load(config)
    repos = _get_repos(cfg, target, all_, group)

    def do_push(repo, grp, c):
        path = c.get_repo_path(repo, grp)
        if not path.exists():
            return git_ops.GitResult(False, f"Not cloned: {path}", "git push")
        return git_ops.push(path)

    (run_parallel if parallel else run_serial)(cfg, repos, do_push, "Push")


@app.command(name="exec")
def exec_cmd(
    command: str = typer.Argument(..., help="Shell command to execute in each repo."),
    target: str | None = typer.Option(None, "--target", "-t", help="Repo name or group/repo."),
    group: str | None = typer.Option(None, "--group", "-g", help="Operate on entire group."),
    all_: bool = typer.Option(False, "--all", "-a", help="Operate on all repositories."),
    parallel: bool = typer.Option(False, "--parallel", "-p", help="Run in parallel."),
    config: Path | None = CONFIG_OPT,
) -> None:
    """Execute an arbitrary command in each repository directory."""
    import subprocess

    from gitmux.executor import run_parallel, run_serial
    from gitmux.git_ops import GitResult

    cfg = _load(config)
    repos = _get_repos(cfg, target, all_, group)

    def do_exec(repo, grp, c):
        path = c.get_repo_path(repo, grp)
        if not path.exists():
            return GitResult(False, f"Directory not found: {path}", command)
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = (result.stdout + result.stderr).strip()
            return GitResult(result.returncode == 0, output, command)
        except subprocess.TimeoutExpired:
            return GitResult(False, "Command timed out (120s)", command)

    (run_parallel if parallel else run_serial)(cfg, repos, do_exec, "Exec")


@app.command()
def status(
    target: str | None = typer.Argument(None, help="Repo name or group/repo. Shows all if omitted."),
    group: str | None = typer.Option(None, "--group", "-g", help="Filter by group."),
    config: Path | None = CONFIG_OPT,
) -> None:
    """Show status overview of all repositories."""
    from gitmux import git_ops

    cfg = _load(config)
    repos = _get_repos(cfg, target, all_=not target and not group, group=group)

    table = Table(title="Repository Status")
    table.add_column("Group", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Branch")
    table.add_column("Status")
    table.add_column("Ahead/Behind")
    table.add_column("Last Commit", style="dim", max_width=40)

    for repo, grp in repos:
        path = cfg.get_repo_path(repo, grp)
        if not path.exists():
            table.add_row(grp.name, repo.name, "-", "[red]Not cloned[/]", "-", "-")
            continue

        branch_result = git_ops.current_branch(path)
        branch = branch_result.output if branch_result.success else "?"

        status_result = git_ops.status(path)
        if status_result.success:
            state = "[green]Clean[/]" if not status_result.output else "[yellow]Dirty[/]"
        else:
            state = "[red]Error[/]"

        ahead, behind = git_ops.ahead_behind(path)
        ab = ""
        if ahead:
            ab += f"[green]↑{ahead}[/]"
        if behind:
            ab += f"[red]↓{behind}[/]"
        if not ab:
            ab = "[dim]—[/]"

        commit = git_ops.last_commit(path)
        table.add_row(grp.name, repo.name, branch, state, ab, commit)

    console.print(table)


# --- Group subcommands ---


@group_app.command(name="list")
def group_list(config: Path | None = CONFIG_OPT) -> None:
    """List all groups."""
    cfg = _load(config)
    if not cfg.groups:
        rprint("[dim]No groups configured.[/]")
        return
    table = Table(title="Groups")
    table.add_column("Name", style="cyan bold")
    table.add_column("Repos", justify="right")
    for grp in cfg.groups:
        table.add_row(grp.name, str(len(grp.repos)))
    console.print(table)


@group_app.command(name="create")
def group_create(
    name: str = typer.Argument(..., help="Group name."),
    config: Path | None = CONFIG_OPT,
) -> None:
    """Create a new group."""
    cfg = _load(config)
    if cfg.find_group(name):
        rprint(f"[red]Group '{name}' already exists.[/]")
        raise typer.Exit(1)
    cfg.groups.append(GroupConfig(name=name))
    _save(cfg, config)
    rprint(f"[green]Created group:[/] {name}")


@group_app.command(name="remove")
def group_remove(
    name: str = typer.Argument(..., help="Group name."),
    force: bool = typer.Option(False, "--force", "-f", help="Remove even if group has repos."),
    config: Path | None = CONFIG_OPT,
) -> None:
    """Remove a group."""
    cfg = _load(config)
    grp = cfg.find_group(name)
    if not grp:
        rprint(f"[red]Group '{name}' not found.[/]")
        raise typer.Exit(1)
    if grp.repos and not force:
        rprint(f"[red]Group '{name}' has {len(grp.repos)} repos.[/] Use --force to remove.")
        raise typer.Exit(1)
    cfg.groups.remove(grp)
    _save(cfg, config)
    rprint(f"[green]Removed group:[/] {name}")
