"""gitmux CLI entry point."""

import json as _json
from pathlib import Path

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from gitmux import __version__
from gitmux.config import DEFAULT_CONFIG_PATH, find_config, load_config, save_config, validate_config
from gitmux.models import GitmuxConfig

app = typer.Typer(name="gitmux", help="Manage multiple git repositories with ease.", no_args_is_help=True)
group_app = typer.Typer(name="group", help="Manage repository groups.")
app.add_typer(group_app, name="group")
workspace_app = typer.Typer(name="workspace", help="Manage local config→workspace bindings.")
app.add_typer(workspace_app, name="workspace")

console = Console()

CONFIG_OPT = typer.Option(None, "--config", "-c", help="Path to config file.")
JSON_OPT = typer.Option(False, "--json", help="Output structured JSON instead of formatted tables.")
WORKSPACE_OPT = typer.Option(None, "--workspace", "-w", help="Override the workspace directory (highest precedence).")
MARKET_OPT = typer.Option(None, "--market", "-m", help="Scope to a market (for configs using the markets layer).")


def _emit_json(payload: object) -> None:
    """Print a JSON payload (for agent/script consumption)."""
    print(_json.dumps(payload, ensure_ascii=False, indent=2))


def _results_to_json(results: list) -> list[dict]:
    return [{"repo": r.repo_name, "success": r.success, "message": r.message} for r in results]


def _load(config_path: Path | None, workspace: str | None = None, require_workspace: bool = False) -> GitmuxConfig:
    path = Path(config_path) if config_path else find_config()
    if not path.exists():
        rprint(f"[red]Config not found: {path}[/]\nRun [bold]gitmux init[/] first.")
        raise typer.Exit(1)
    cfg = load_config(path)
    cfg.config_path = path.resolve()
    if workspace:
        cfg.workspace_override = workspace
    errors = validate_config(cfg)
    if errors:
        for e in errors:
            rprint(f"[red]Config error:[/] {e}")
        raise typer.Exit(1)
    # For path-using commands, surface workspace/placeholder problems early.
    if require_workspace:
        from gitmux.models import WorkspaceError

        try:
            cfg.resolve_workspace()
        except WorkspaceError as e:
            rprint(f"[red]{e}[/]")
            raise typer.Exit(1) from None
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
    from gitmux import service

    cfg = _load(config)
    try:
        repo = service.add_repo(cfg, url, group=group, name=name, template=template)
    except service.ServiceError as e:
        rprint(f"[red]{e}[/]")
        raise typer.Exit(1) from None
    _save(cfg, config)
    rprint(f"[green]Added[/] {repo.name} to group '{group}'")


@app.command()
def remove(
    name: str = typer.Argument(..., help="Repository name to remove."),
    config: Path | None = CONFIG_OPT,
) -> None:
    """Remove a repository from the configuration."""
    from gitmux import service

    cfg = _load(config)
    try:
        group_name = service.remove_repo(cfg, name)
    except service.ServiceError as e:
        rprint(f"[red]{e}[/]")
        raise typer.Exit(1) from None
    _save(cfg, config)
    rprint(f"[green]Removed[/] {name} from group '{group_name}'")


@app.command(name="list")
def list_repos(
    group: str | None = typer.Option(None, "--group", "-g", help="Filter by group."),
    json_out: bool = JSON_OPT,
    workspace_opt: str | None = WORKSPACE_OPT,
    config: Path | None = CONFIG_OPT,
) -> None:
    """List all configured repositories."""
    cfg = _load(config, workspace_opt, require_workspace=True)

    if json_out:
        payload = []
        for grp in cfg.groups:
            if group and grp.name != group:
                continue
            for repo in grp.repos:
                payload.append(
                    {
                        "market": grp.market,
                        "group": grp.name,
                        "name": repo.name,
                        "url": repo.url,
                        "path": str(cfg.get_repo_path(repo, grp)),
                        "template": repo.template,
                        "branches": repo.branches,
                    }
                )
        _emit_json(payload)
        return

    table = Table(title="Repositories")
    if cfg.has_markets:
        table.add_column("Market", style="magenta")
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
            row = [grp.name, repo.name, repo.url, path, repo.template or ""]
            if cfg.has_markets:
                row.insert(0, grp.market)
            table.add_row(*row)

    console.print(table)


def _get_repos(
    cfg: GitmuxConfig, target: str | None, all_: bool, group: str | None = None, market: str | None = None
) -> list[tuple]:
    """Resolve target repos via the service layer, mapping errors to CLI exits."""
    from gitmux import service

    try:
        return service.get_repos(cfg, target=target, all_=all_, group=group, market=market)
    except service.ServiceError as e:
        rprint(f"[red]{e}[/]")
        raise typer.Exit(1) from None


@app.command()
def clone(
    target: str | None = typer.Argument(None, help="Repo name or group/repo."),
    group: str | None = typer.Option(None, "--group", "-g", help="Operate on entire group."),
    all_: bool = typer.Option(False, "--all", "-a", help="Operate on all repositories."),
    market_opt: str | None = MARKET_OPT,
    parallel: bool = typer.Option(False, "--parallel", "-p", help="Run in parallel."),
    json_out: bool = JSON_OPT,
    workspace_opt: str | None = WORKSPACE_OPT,
    config: Path | None = CONFIG_OPT,
) -> None:
    """Clone repositories that haven't been cloned yet."""
    from gitmux import service
    from gitmux.executor import run_parallel, run_serial

    cfg = _load(config, workspace_opt, require_workspace=True)
    repos = _get_repos(cfg, target, all_, group, market=market_opt)

    if json_out:
        results = service.run_operation(cfg, repos, service._op_clone, "Clone")
        _emit_json(_results_to_json(results))
        return
    (run_parallel if parallel else run_serial)(cfg, repos, service._op_clone, "Clone")


@app.command()
def fetch(
    target: str | None = typer.Argument(None, help="Repo name or group/repo."),
    group: str | None = typer.Option(None, "--group", "-g", help="Operate on entire group."),
    all_: bool = typer.Option(False, "--all", "-a", help="Operate on all repositories."),
    market_opt: str | None = MARKET_OPT,
    parallel: bool = typer.Option(False, "--parallel", "-p", help="Run in parallel."),
    show_branches: bool = typer.Option(False, "--branches", help="Show remote branches after fetch."),
    json_out: bool = JSON_OPT,
    workspace_opt: str | None = WORKSPACE_OPT,
    config: Path | None = CONFIG_OPT,
) -> None:
    """Fetch latest remote data for repositories."""
    from gitmux import service
    from gitmux.executor import run_parallel as run_par
    from gitmux.executor import run_serial

    cfg = _load(config, workspace_opt, require_workspace=True)
    repos = _get_repos(cfg, target, all_, group, market=market_opt)
    op = service.make_fetch_op(show_branches=show_branches)

    if json_out:
        results = service.run_operation(cfg, repos, op, "Fetch")
        _emit_json(_results_to_json(results))
        return
    (run_par if parallel else run_serial)(cfg, repos, op, "Fetch")


@app.command()
def pull(
    target: str | None = typer.Argument(None, help="Repo name or group/repo."),
    group: str | None = typer.Option(None, "--group", "-g", help="Operate on entire group."),
    all_: bool = typer.Option(False, "--all", "-a", help="Operate on all repositories."),
    market_opt: str | None = MARKET_OPT,
    branch: str | None = typer.Option(
        None, "--branch", "-b", help="Branch alias, e.g. 'dev', 'prod:latest', 'prod:~20260520', 'prod:20260524'."
    ),
    parallel: bool = typer.Option(False, "--parallel", "-p", help="Run in parallel."),
    json_out: bool = JSON_OPT,
    workspace_opt: str | None = WORKSPACE_OPT,
    config: Path | None = CONFIG_OPT,
) -> None:
    """Pull latest changes for repositories."""
    from gitmux import service
    from gitmux.executor import run_parallel as run_par
    from gitmux.executor import run_serial

    cfg = _load(config, workspace_opt, require_workspace=True)
    repos = _get_repos(cfg, target, all_, group, market=market_opt)
    op = service.make_pull_op(branch=branch)

    if json_out:
        results = service.run_operation(cfg, repos, op, "Pull")
        _emit_json(_results_to_json(results))
        return
    (run_par if parallel else run_serial)(cfg, repos, op, "Pull")


@app.command()
def push(
    target: str | None = typer.Argument(None, help="Repo name or group/repo."),
    group: str | None = typer.Option(None, "--group", "-g", help="Operate on entire group."),
    all_: bool = typer.Option(False, "--all", "-a", help="Operate on all repositories."),
    market_opt: str | None = MARKET_OPT,
    parallel: bool = typer.Option(False, "--parallel", "-p", help="Run in parallel."),
    json_out: bool = JSON_OPT,
    workspace_opt: str | None = WORKSPACE_OPT,
    config: Path | None = CONFIG_OPT,
) -> None:
    """Push local commits for repositories."""
    from gitmux import service
    from gitmux.executor import run_parallel, run_serial

    cfg = _load(config, workspace_opt, require_workspace=True)
    repos = _get_repos(cfg, target, all_, group, market=market_opt)

    if json_out:
        results = service.run_operation(cfg, repos, service._op_push, "Push")
        _emit_json(_results_to_json(results))
        return
    (run_parallel if parallel else run_serial)(cfg, repos, service._op_push, "Push")


@app.command(name="exec")
def exec_cmd(
    command: str = typer.Argument(..., help="Shell command to execute in each repo."),
    target: str | None = typer.Option(None, "--target", "-t", help="Repo name or group/repo."),
    group: str | None = typer.Option(None, "--group", "-g", help="Operate on entire group."),
    all_: bool = typer.Option(False, "--all", "-a", help="Operate on all repositories."),
    market_opt: str | None = MARKET_OPT,
    parallel: bool = typer.Option(False, "--parallel", "-p", help="Run in parallel."),
    json_out: bool = JSON_OPT,
    workspace_opt: str | None = WORKSPACE_OPT,
    config: Path | None = CONFIG_OPT,
) -> None:
    """Execute an arbitrary command in each repository directory."""
    from gitmux import service
    from gitmux.executor import run_parallel, run_serial

    cfg = _load(config, workspace_opt, require_workspace=True)
    repos = _get_repos(cfg, target, all_, group, market=market_opt)
    op = service.make_exec_op(command)

    if json_out:
        results = service.run_operation(cfg, repos, op, "Exec")
        _emit_json(_results_to_json(results))
        return
    (run_parallel if parallel else run_serial)(cfg, repos, op, "Exec")


@app.command()
def status(
    target: str | None = typer.Argument(None, help="Repo name or group/repo. Shows all if omitted."),
    group: str | None = typer.Option(None, "--group", "-g", help="Filter by group."),
    market: str | None = MARKET_OPT,
    json_out: bool = JSON_OPT,
    workspace_opt: str | None = WORKSPACE_OPT,
    config: Path | None = CONFIG_OPT,
) -> None:
    """Show status overview of all repositories."""
    from gitmux import git_ops, service

    cfg = _load(config, workspace_opt, require_workspace=True)
    repos = _get_repos(cfg, target, all_=not target and not group and not market, group=group, market=market)

    if json_out:
        _emit_json(service.status_report(cfg, repos))
        return

    show_market = cfg.has_markets
    table = Table(title="Repository Status")
    if show_market:
        table.add_column("Market", style="magenta")
    table.add_column("Group", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Branch")
    table.add_column("Status")
    table.add_column("Ahead/Behind")
    table.add_column("Last Commit", style="dim", max_width=40)

    for repo, grp in repos:
        path = cfg.get_repo_path(repo, grp)
        if not path.exists():
            row = [grp.name, repo.name, "-", "[red]Not cloned[/]", "-", "-"]
            if show_market:
                row.insert(0, grp.market)
            table.add_row(*row)
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
        row = [grp.name, repo.name, branch, state, ab, commit]
        if show_market:
            row.insert(0, grp.market)
        table.add_row(*row)

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
    cfg.add_group(name)
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
    cfg.remove_group(grp)
    _save(cfg, config)
    rprint(f"[green]Removed group:[/] {name}")


# --- Workspace registry subcommands ---


@workspace_app.command(name="set")
def workspace_set(
    workspace: str = typer.Argument(..., help="Local workspace directory to bind this config to."),
    config: Path | None = CONFIG_OPT,
) -> None:
    """Bind a config file to a local workspace directory (stored in the registry)."""
    from gitmux import registry

    cfg_path = Path(config) if config else find_config()
    key = registry.set_mapping(cfg_path, workspace)
    rprint(f"[green]Bound[/] {key}\n   -> workspace: {Path(workspace).expanduser()}")


@workspace_app.command(name="show")
def workspace_show(config: Path | None = CONFIG_OPT) -> None:
    """Show workspace bindings. With -c, show the effective workspace for that config."""
    from gitmux import registry

    rprint(f"[dim]Registry:[/] {registry.registry_path()}")
    if config:
        cfg_path = Path(config)
        bound = registry.get(cfg_path)
        rprint(f"[cyan]{cfg_path.expanduser().resolve()}[/]")
        rprint(f"   -> {bound if bound else '[dim](not bound)[/]'}")
        return
    mappings = registry.load_mappings()
    if not mappings:
        rprint("[dim]No workspace bindings.[/]")
        return
    table = Table(title="Workspace Bindings")
    table.add_column("Config", style="cyan")
    table.add_column("Workspace")
    for k, v in mappings.items():
        table.add_row(k, v)
    console.print(table)


@workspace_app.command(name="unset")
def workspace_unset(config: Path | None = CONFIG_OPT) -> None:
    """Remove a config→workspace binding from the registry."""
    from gitmux import registry

    cfg_path = Path(config) if config else find_config()
    if registry.unset_mapping(cfg_path):
        rprint(f"[green]Unbound[/] {cfg_path.expanduser().resolve()}")
    else:
        rprint(f"[yellow]No binding for[/] {cfg_path.expanduser().resolve()}")
