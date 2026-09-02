"""gitmux MCP server (stdio transport, no authentication).

Exposes gitmux repository management as MCP tools for local AI agents. Because
the transport is stdio and the server runs as a child process of the agent on
the same machine, the security boundary is the OS/process — no token auth is
needed or used.

The tool set is the capability boundary: only the operations defined here are
possible. Notably, there is NO generic shell/exec tool — that would reintroduce
an arbitrary-command escape hatch and defeat the least-privilege model.

Run:
    gitmux-mcp                 # uses config lookup (./.gitmux.yaml → ~/.gitmux.yaml)
    gitmux-mcp --config PATH   # pin a specific config file

Requires the optional dependency:  pip install "gitmux[mcp]"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gitmux import service

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # pragma: no cover - surfaced only when extra not installed
    sys.stderr.write("The 'mcp' package (>=2) is required. Install with:  pip install 'gitmux[mcp]'\n")
    raise

# Default config path and workspace override, set by main() from CLI args.
# None → use config lookup / config's own workspace value.
_CONFIG_PATH: str | None = None
_WORKSPACE: str | None = None

mcp = MCPServer("gitmux")


def _load():
    """Load config, raising a clear message on failure."""
    return service.load(_CONFIG_PATH, workspace=_WORKSPACE)


def _results(results: list) -> list[dict]:
    return [{"repo": r.repo_name, "success": r.success, "message": r.message} for r in results]


# --- Read tools -----------------------------------------------------------


@mcp.tool()
def list_repos(group: str | None = None, market: str | None = None) -> list[dict]:
    """List configured repositories, optionally filtered by group and/or market.

    Returns one entry per repo with market, group, name, url, resolved local path,
    template, and branch aliases.
    """
    cfg = _load()
    out = []
    for grp in cfg.groups:
        if group and grp.name != group:
            continue
        if market and grp.market != market:
            continue
        for repo in grp.repos:
            out.append(
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
    return out


@mcp.tool()
def list_groups(market: str | None = None) -> list[dict]:
    """List configured groups (optionally within a market) and their repo counts."""
    cfg = _load()
    return [
        {"market": g.market, "name": g.name, "repo_count": len(g.repos)}
        for g in cfg.groups
        if not market or g.market == market
    ]


@mcp.tool()
def list_markets() -> list[dict]:
    """List configured markets and their group counts.

    Returns [] for legacy configs that don't use the markets layer.
    """
    cfg = _load()
    return [{"name": m.name, "group_count": len(m.groups)} for m in cfg.markets if m.name]


@mcp.tool()
def status(target: str | None = None, group: str | None = None, market: str | None = None) -> list[dict]:
    """Show git status for repositories.

    Target selection:
    - target = "market/group/repo" (with markets) or "group/repo"/"repo" (legacy)
    - market = "<m>"  → all repos in a market
    - group  = "<g>"  → all repos in a group (optionally within `market`)
    - none            → all repos

    Each entry: market, group, name, cloned, branch, clean, ahead, behind, last_commit.
    """
    cfg = _load()
    repos = service.get_repos(
        cfg, target=target, all_=(not target and not group and not market), group=group, market=market
    )
    return service.status_report(cfg, repos)


@mcp.tool()
def fetch(
    target: str | None = None,
    group: str | None = None,
    market: str | None = None,
    all_repos: bool = False,
    show_branches: bool = False,
) -> list[dict]:
    """Fetch remote data for repositories. Optionally list remote branches.

    Specify one of: target, market, group, or all_repos=True.
    """
    cfg = _load()
    repos = service.get_repos(cfg, target=target, all_=all_repos, group=group, market=market)
    op = service.make_fetch_op(show_branches=show_branches)
    return _results(service.run_operation(cfg, repos, op, "Fetch"))


# --- Git action tools -----------------------------------------------------


@mcp.tool()
def clone(
    target: str | None = None, group: str | None = None, market: str | None = None, all_repos: bool = False
) -> list[dict]:
    """Clone repositories that are not yet cloned (idempotent).

    Specify one of: target, market, group, or all_repos=True.
    """
    cfg = _load()
    repos = service.get_repos(cfg, target=target, all_=all_repos, group=group, market=market)
    return _results(service.run_operation(cfg, repos, service._op_clone, "Clone"))


@mcp.tool()
def pull(
    target: str | None = None,
    group: str | None = None,
    market: str | None = None,
    all_repos: bool = False,
    branch: str | None = None,
) -> list[dict]:
    """Pull latest changes for repositories.

    Specify one of: target, market, group, or all_repos=True.
    Target with markets is "market/group/repo" (e.g. "mastercard/rebate/bonus").

    Optional branch alias resolution (aliases come from each repo's config):
    - branch = "<alias>"          → fixed branch (alias must not contain '*')
    - branch = "<alias>:latest"   → newest branch matching the pattern alias
    - branch = "<alias>:~<date>"  → newest matching branch with date <= <date> (YYMMDD or YYYYMMDD)
    - branch = "<alias>:<value>"  → replace '*' in the pattern with <value>
    """
    cfg = _load()
    repos = service.get_repos(cfg, target=target, all_=all_repos, group=group, market=market)
    op = service.make_pull_op(branch=branch)
    return _results(service.run_operation(cfg, repos, op, "Pull"))


@mcp.tool()
def push(
    target: str | None = None, group: str | None = None, market: str | None = None, all_repos: bool = False
) -> list[dict]:
    """Push local commits for repositories.

    Specify one of: target, market, group, or all_repos=True.
    """
    cfg = _load()
    repos = service.get_repos(cfg, target=target, all_=all_repos, group=group, market=market)
    return _results(service.run_operation(cfg, repos, service._op_push, "Push"))


# --- Config mutation tools ------------------------------------------------


@mcp.tool()
def add_repo(
    url: str,
    group: str = "default",
    name: str | None = None,
    template: str | None = None,
    market: str | None = None,
) -> dict:
    """Add a repository declaration to the config file.

    This only edits the YAML config (creates the group/market if needed); it does
    not clone anything. For configs using the markets layer, `market` selects the
    owning market (defaults to the first market). Returns the added repo's name,
    group, and market.
    """
    cfg = _load()
    repo = service.add_repo(cfg, url, group=group, name=name, template=template, market=market)
    service.save_config(cfg, service.resolve_config_path(_CONFIG_PATH))
    grp = cfg.find_repo(repo.name)[1]
    return {"added": repo.name, "group": group, "market": grp.market}


@mcp.tool()
def remove_repo(name: str) -> dict:
    """Remove a repository declaration from the config file.

    This only edits the YAML config; it does NOT delete any cloned directory on
    disk. Returns the removed repo's name and its former group.
    """
    cfg = _load()
    group_name = service.remove_repo(cfg, name)
    service.save_config(cfg, service.resolve_config_path(_CONFIG_PATH))
    return {"removed": name, "group": group_name}


@mcp.tool()
def init_config(path: str, workspace: str = "~/projects", overwrite: bool = False) -> dict:
    """Create a new gitmux config file at `path` (non-interactive).

    Fails if the file exists unless overwrite=True.
    """
    created = service.init_config(path, workspace=workspace, overwrite=overwrite)
    return {"created": str(created), "workspace": workspace}


# --- Workspace registry tools ---------------------------------------------


@mcp.tool()
def workspace_set(workspace: str, config: str | None = None) -> dict:
    """Bind a config file to a local workspace directory in the registry
    (~/.config/gitmux/workspaces.yaml).

    Afterwards, loading that config resolves this workspace automatically — no
    environment variable or --workspace needed. `config` defaults to the server's
    --config if omitted.
    """
    from gitmux import registry

    cfg = config or _CONFIG_PATH
    if not cfg:
        raise ValueError("No config specified (pass 'config' or start the server with --config).")
    key = registry.set_mapping(cfg, workspace)
    return {"config": key, "workspace": str(Path(workspace).expanduser())}


@mcp.tool()
def workspace_show(config: str | None = None) -> dict:
    """Show workspace registry bindings.

    With `config`, returns the effective binding for that config; otherwise
    returns all bindings plus the registry file location.
    """
    from gitmux import registry

    cfg = config or _CONFIG_PATH
    if cfg:
        return {
            "registry": str(registry.registry_path()),
            "config": str(Path(cfg).expanduser().resolve()),
            "workspace": registry.get(cfg),
        }
    return {"registry": str(registry.registry_path()), "mappings": registry.load_mappings()}


@mcp.tool()
def workspace_unset(config: str | None = None) -> dict:
    """Remove a config→workspace binding from the registry."""
    from gitmux import registry

    cfg = config or _CONFIG_PATH
    if not cfg:
        raise ValueError("No config specified (pass 'config' or start the server with --config).")
    removed = registry.unset_mapping(cfg)
    return {"config": str(Path(cfg).expanduser().resolve()), "removed": removed}


def main() -> None:
    """Console entry point: parse args, then serve over stdio."""
    global _CONFIG_PATH, _WORKSPACE
    parser = argparse.ArgumentParser(description="gitmux MCP server (stdio).")
    parser.add_argument("--config", "-c", default=None, help="Path to a .gitmux.yaml config file.")
    parser.add_argument(
        "--workspace",
        "-w",
        default=None,
        help="Override the workspace directory (highest precedence). "
        "Also settable via the config's ${ENV_VAR} placeholder.",
    )
    args = parser.parse_args()
    _CONFIG_PATH = args.config
    _WORKSPACE = args.workspace
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
