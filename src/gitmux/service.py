"""Rich-free service layer shared by the CLI and the MCP server.

This module contains the pure business logic: resolving targets, resolving
branch aliases, running git operations, and mutating configuration. It performs
no terminal output so it can be driven by both the interactive CLI (which adds
Rich formatting on top) and the MCP server (which returns structured data).
"""

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from gitmux import git_ops
from gitmux.config import load_config, save_config, validate_config
from gitmux.executor import RepoResult, _execute_one
from gitmux.git_ops import GitResult
from gitmux.models import GitmuxConfig, GroupConfig, RepoConfig

DEFAULT_GROUP = "default"


class ServiceError(Exception):
    """Raised for user-facing service errors (invalid target, group, etc.)."""


# --- Config helpers -------------------------------------------------------


def load(config_path: str | Path | None = None, workspace: str | None = None) -> GitmuxConfig:
    """Load and validate a config file. Raises ServiceError on problems.

    workspace: optional override (from --workspace / MCP arg) that takes
    precedence over the config file's workspace value.
    """
    path = Path(config_path).expanduser() if config_path else None
    from gitmux.config import find_config

    resolved = path or find_config()
    if not resolved.exists():
        raise ServiceError(f"Config not found: {resolved}. Run init first.")
    cfg = load_config(resolved)
    cfg.config_path = resolved.resolve()
    if workspace:
        cfg.workspace_override = workspace
    errors = validate_config(cfg)
    if errors:
        raise ServiceError("; ".join(errors))
    return cfg


def resolve_config_path(config_path: str | Path | None) -> Path:
    from gitmux.config import find_config

    return Path(config_path).expanduser() if config_path else find_config()


# --- Target resolution ----------------------------------------------------


def get_repos(
    cfg: GitmuxConfig,
    target: str | None = None,
    all_: bool = False,
    group: str | None = None,
    market: str | None = None,
) -> list[tuple[RepoConfig, GroupConfig]]:
    """Resolve target repos.

    Target syntax:
      - with markets:  "market/group/repo"  (fully qualified)
      - legacy:        "group/repo" or "repo" (repo → DEFAULT_GROUP)
    Selectors (when no target):
      - market="<m>"           → all repos in a market
      - group="<g>"            → all repos in a group (optionally scoped by market)
      - market + group         → that group in that market
      - all_=True              → all repos
      - nothing                → ServiceError
    """
    if target:
        parts = target.split("/")
        if cfg.has_markets and len(parts) == 3:
            market_name, group_name, repo_name = parts
            m = cfg.find_market(market_name)
            if not m:
                raise ServiceError(f"Market '{market_name}' not found.")
            for grp in m.groups:
                if grp.name == group_name:
                    for repo in grp.repos:
                        if repo.name == repo_name:
                            return [(repo, grp)]
                    raise ServiceError(f"Repo '{repo_name}' not found in '{market_name}/{group_name}'.")
            raise ServiceError(f"Group '{group_name}' not found in market '{market_name}'.")
        if len(parts) == 2:
            group_name, repo_name = parts
        elif len(parts) == 1:
            group_name, repo_name = DEFAULT_GROUP, parts[0]
        else:
            raise ServiceError(f"Invalid target '{target}'. Use 'market/group/repo' (with markets) or 'group/repo'.")
        grp = cfg.find_group(group_name)
        if not grp:
            raise ServiceError(f"Group '{group_name}' not found.")
        for repo in grp.repos:
            if repo.name == repo_name:
                return [(repo, grp)]
        raise ServiceError(f"Repo '{repo_name}' not found in group '{group_name}'.")

    if market:
        m = cfg.find_market(market)
        if not m:
            raise ServiceError(f"Market '{market}' not found.")
        if group:
            for grp in m.groups:
                if grp.name == group:
                    return [(r, grp) for r in grp.repos]
            raise ServiceError(f"Group '{group}' not found in market '{market}'.")
        return [(r, grp) for grp in m.groups for r in grp.repos]

    if group:
        grp = cfg.find_group(group)
        if not grp:
            raise ServiceError(f"Group '{group}' not found.")
        return [(r, grp) for r in grp.repos]

    if all_:
        return cfg.all_repos()
    raise ServiceError("Please specify a repo target, market, group, or all.")


# --- Branch alias resolution ----------------------------------------------


def resolve_branch(repo: RepoConfig, branch: str | None, path: Path) -> tuple[str | None, GitResult | None]:
    """Resolve a --branch expression to a concrete branch name.

    Returns (target_branch, error_result):
    - (None, None)            → no branch requested (caller does plain pull)
    - (branch_name, None)     → resolved branch to checkout
    - (None, GitResult(fail)) → resolution failed; caller should return the error

    Supported forms (mirrors CLI docs):
    - "<alias>"          → alias must be a fixed branch (no '*')
    - "<alias>:latest"   → alias must be a pattern; newest matching branch
    - "<alias>:~<date>"  → alias must be a pattern; newest matching branch with date <= <date>
    - "<alias>:<value>"  → alias must be a pattern; replace '*' with <value>

    Note: for ':latest' and ':~date' this fetches remote refs (network) to
    enumerate branches. The caller does NOT need to fetch again for those.
    """
    if not branch:
        return None, None

    if ":" in branch:
        alias, value = branch.split(":", 1)
    else:
        alias, value = branch, None

    if alias not in repo.branches:
        return None, GitResult(False, f"Branch alias '{alias}' not configured", "branch resolve")

    pattern = repo.branches[alias]
    is_pattern = "*" in pattern

    if value is None:
        if is_pattern:
            return None, GitResult(
                False,
                f"'{alias}' is a pattern ({pattern}), use {alias}:latest or {alias}:<value>",
                "branch resolve",
            )
        return pattern, None

    if value == "latest":
        if not is_pattern:
            return None, GitResult(
                False, f"'{alias}' is a fixed branch ({pattern}), use {alias} directly", "branch resolve"
            )
        fetch_result = git_ops.fetch(path)
        if not fetch_result.success:
            return None, fetch_result
        matches = git_ops.list_remote_branches(path, pattern)
        if not matches:
            return None, GitResult(False, f"No remote branch matching '{pattern}'", "branch resolve")
        return matches[0], None  # sorted by committerdate, newest first

    if value.startswith("~"):
        if not is_pattern:
            return None, GitResult(
                False, f"'{alias}' is a fixed branch ({pattern}), use {alias} directly", "branch resolve"
            )
        date_str = value[1:]
        if len(date_str) == 8:  # normalize YYYYMMDD → YYMMDD
            date_str = date_str[2:]
        fetch_result = git_ops.fetch(path)
        if not fetch_result.success:
            return None, fetch_result
        matches = git_ops.list_remote_branches(path, pattern)
        if not matches:
            return None, GitResult(False, f"No remote branch matching '{pattern}'", "branch resolve")
        candidates = []
        for m in matches:
            found = re.search(r"(\d{6})", m)
            if found and found.group(1) <= date_str:
                candidates.append(m)
        if not candidates:
            return None, GitResult(
                False,
                f"No branch matching '{pattern}' with date <= {date_str} (found: {matches[:5]})",
                "branch resolve",
            )
        return candidates[0], None  # already newest-first

    # replace '*' with value
    if not is_pattern:
        return None, GitResult(
            False, f"'{alias}' is a fixed branch ({pattern}), use {alias} directly", "branch resolve"
        )
    return pattern.replace("*", value), None


# --- Operation factories --------------------------------------------------


def _op_clone(repo: RepoConfig, grp: GroupConfig, c: GitmuxConfig) -> GitResult:
    path = c.get_repo_path(repo, grp)
    if path.exists():
        return GitResult(True, "Already cloned", "skip")
    return git_ops.clone(repo.url, path)


def _op_push(repo: RepoConfig, grp: GroupConfig, c: GitmuxConfig) -> GitResult:
    path = c.get_repo_path(repo, grp)
    if not path.exists():
        return GitResult(False, f"Not cloned: {path}", "git push")
    return git_ops.push(path)


def make_fetch_op(show_branches: bool = False) -> Callable[[RepoConfig, GroupConfig, GitmuxConfig], GitResult]:
    def _op(repo: RepoConfig, grp: GroupConfig, c: GitmuxConfig) -> GitResult:
        path = c.get_repo_path(repo, grp)
        if not path.exists():
            return GitResult(False, f"Not cloned: {path}", "git fetch")
        result = git_ops.fetch(path)
        if result.success and show_branches:
            branches = git_ops.list_remote_branches(path, "*")
            result = GitResult(True, "\n".join(branches) if branches else "(no remote branches)", result.command)
        return result

    return _op


def make_pull_op(branch: str | None = None) -> Callable[[RepoConfig, GroupConfig, GitmuxConfig], GitResult]:
    def _op(repo: RepoConfig, grp: GroupConfig, c: GitmuxConfig) -> GitResult:
        path = c.get_repo_path(repo, grp)
        if not path.exists():
            return GitResult(False, f"Not cloned: {path}", "git pull")

        if not branch:
            return git_ops.pull(path)

        # ':latest' and ':~date' fetch inside resolve_branch already.
        target, error = resolve_branch(repo, branch, path)
        if error is not None:
            return error
        if target is None:
            return git_ops.pull(path)

        # For the ':value' and fixed-alias forms, ensure refs are fresh.
        needs_fetch = not (
            ":" in branch and (branch.split(":", 1)[1] == "latest" or branch.split(":", 1)[1].startswith("~"))
        )
        if needs_fetch:
            fetch_result = git_ops.fetch(path)
            if not fetch_result.success:
                return fetch_result

        checkout_result = git_ops.checkout(path, target)
        if not checkout_result.success:
            return GitResult(False, f"Checkout failed: {checkout_result.output}", f"git checkout {target}")

        pull_result = git_ops.pull(path)
        return GitResult(pull_result.success, f"[{target}] {pull_result.output}", pull_result.command)

    return _op


def make_exec_op(command: str, timeout: int = 120) -> Callable[[RepoConfig, GroupConfig, GitmuxConfig], GitResult]:
    def _op(repo: RepoConfig, grp: GroupConfig, c: GitmuxConfig) -> GitResult:
        path = c.get_repo_path(repo, grp)
        if not path.exists():
            return GitResult(False, f"Directory not found: {path}", command)
        try:
            result = subprocess.run(command, shell=True, cwd=path, capture_output=True, text=True, timeout=timeout)
            output = (result.stdout + result.stderr).strip()
            return GitResult(result.returncode == 0, output, command)
        except subprocess.TimeoutExpired:
            return GitResult(False, f"Command timed out ({timeout}s)", command)

    return _op


# --- Runner (no terminal output) ------------------------------------------


def run_operation(
    cfg: GitmuxConfig,
    repos: list[tuple[RepoConfig, GroupConfig]],
    operation: Callable[[RepoConfig, GroupConfig, GitmuxConfig], GitResult],
    op_name: str,
) -> list[RepoResult]:
    """Run an operation over repos serially, returning structured results.

    Reuses executor._execute_one (which runs pre-hook → op → post-hook and does
    not print). This is the Rich-free path used by the MCP server.
    """
    return [_execute_one(repo, grp, cfg, operation, op_name) for repo, grp in repos]


def status_report(cfg: GitmuxConfig, repos: list[tuple[RepoConfig, GroupConfig]]) -> list[dict]:
    """Collect git status for each repo as plain dicts."""
    report = []
    for repo, grp in repos:
        path = cfg.get_repo_path(repo, grp)
        if not path.exists():
            report.append(
                {
                    "market": grp.market,
                    "group": grp.name,
                    "name": repo.name,
                    "cloned": False,
                    "branch": None,
                    "clean": None,
                    "ahead": 0,
                    "behind": 0,
                    "last_commit": None,
                }
            )
            continue
        branch_result = git_ops.current_branch(path)
        branch = branch_result.output if branch_result.success else "?"
        status_result = git_ops.status(path)
        clean = (status_result.output == "") if status_result.success else None
        ahead, behind = git_ops.ahead_behind(path)
        report.append(
            {
                "market": grp.market,
                "group": grp.name,
                "name": repo.name,
                "cloned": True,
                "branch": branch,
                "clean": clean,
                "ahead": ahead,
                "behind": behind,
                "last_commit": git_ops.last_commit(path),
            }
        )
    return report


# --- Config mutations -----------------------------------------------------


def repo_name_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1].removesuffix(".git")


def add_repo(
    cfg: GitmuxConfig,
    url: str,
    group: str = DEFAULT_GROUP,
    name: str | None = None,
    template: str | None = None,
    market: str | None = None,
) -> RepoConfig:
    """Add a repo to the config (in memory). Raises ServiceError on conflict.

    If the config uses markets, `market` selects/creates the owning market.
    When markets exist and no market is given, it defaults to the first market.
    """
    from gitmux.models import NO_MARKET, MarketConfig

    repo_name = name or repo_name_from_url(url)
    if cfg.find_repo(repo_name):
        raise ServiceError(f"Repo '{repo_name}' already exists.")
    if template and template not in cfg.templates:
        raise ServiceError(f"Template '{template}' not found.")

    # Resolve the owning market.
    if market is not None:
        mkt = cfg.find_market(market)
        if not mkt:
            mkt = MarketConfig(name=market)
            cfg.markets.append(mkt)
    elif cfg.markets:
        mkt = cfg.markets[0]  # default to first existing market
    else:
        mkt = MarketConfig(name=NO_MARKET)  # legacy: single implicit no-market bucket
        cfg.markets.append(mkt)

    grp = next((g for g in mkt.groups if g.name == group), None)
    if not grp:
        grp = GroupConfig(name=group, market=mkt.name)
        mkt.groups.append(grp)
    repo = RepoConfig(name=repo_name, url=url, template=template)
    grp.repos.append(repo)
    return repo


def remove_repo(cfg: GitmuxConfig, name: str) -> str:
    """Remove a repo from the config (in memory). Returns its group name."""
    result = cfg.find_repo(name)
    if not result:
        raise ServiceError(f"Repo '{name}' not found.")
    repo, grp = result
    grp.repos.remove(repo)
    return grp.name


def init_config(path: str | Path, workspace: str = "~/projects", overwrite: bool = False) -> Path:
    """Create a new config file non-interactively. Raises ServiceError if it exists
    and overwrite is False."""
    p = Path(path).expanduser()
    if p.exists() and not overwrite:
        raise ServiceError(f"{p} already exists (pass overwrite=True to replace).")
    save_config(GitmuxConfig(workspace=workspace), p)
    return p
