"""Configuration loading, saving, and validation."""

from pathlib import Path

import yaml

from gitmux.models import NO_MARKET, GitmuxConfig, GroupConfig, HookConfig, MarketConfig, RepoConfig

DEFAULT_CONFIG_PATH = Path.home() / ".gitmux.yaml"
LOCAL_CONFIG_NAME = ".gitmux.yaml"


def find_config() -> Path:
    """Find config file: current dir → home dir."""
    local = Path.cwd() / LOCAL_CONFIG_NAME
    if local.exists():
        return local
    return DEFAULT_CONFIG_PATH


def _parse_hooks(data: dict | None) -> HookConfig:
    if not data:
        return HookConfig()
    return HookConfig(
        pre_clone=data.get("pre_clone", []),
        post_clone=data.get("post_clone", []),
        pre_pull=data.get("pre_pull", []),
        post_pull=data.get("post_pull", []),
        pre_push=data.get("pre_push", []),
        post_push=data.get("post_push", []),
    )


def _parse_repo(data: dict) -> RepoConfig:
    return RepoConfig(
        name=data["name"],
        url=data["url"],
        path=data.get("path"),
        template=data.get("template"),
        hooks=_parse_hooks(data.get("hooks")),
        branches=data.get("branches") or {},
    )


def load_config(path: Path | None = None) -> GitmuxConfig:
    """Load and parse gitmux config from YAML file."""
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return GitmuxConfig()

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    templates = {}
    for name, hook_data in (data.get("templates") or {}).items():
        templates[name] = _parse_hooks(hook_data)

    markets = _parse_markets(data)

    return GitmuxConfig(
        workspace=data.get("workspace"),
        templates=templates,
        markets=markets,
    )


def _parse_groups(groups_data: dict | None, market_name: str) -> list[GroupConfig]:
    groups = []
    for group_name, group_data in (groups_data or {}).items():
        repos = [_parse_repo(r) for r in ((group_data or {}).get("repos") or [])]
        groups.append(GroupConfig(name=group_name, repos=repos, market=market_name))
    return groups


def _parse_markets(data: dict) -> list[MarketConfig]:
    """Parse the markets layer, or wrap a legacy top-level `groups:` as NO_MARKET."""
    markets: list[MarketConfig] = []
    if data.get("markets"):
        for market_name, market_data in data["markets"].items():
            groups = _parse_groups((market_data or {}).get("groups"), market_name)
            markets.append(MarketConfig(name=market_name, groups=groups))
    elif data.get("groups"):
        # Legacy: top-level groups → single implicit no-market bucket.
        groups = _parse_groups(data["groups"], NO_MARKET)
        markets.append(MarketConfig(name=NO_MARKET, groups=groups))
    return markets


def _hooks_to_dict(hooks: HookConfig) -> dict | None:
    d = {}
    for key in ("pre_clone", "post_clone", "pre_pull", "post_pull", "pre_push", "post_push"):
        val = getattr(hooks, key)
        if val:
            d[key] = val
    return d or None


def save_config(config: GitmuxConfig, path: Path | None = None) -> None:
    """Save gitmux config to YAML file."""
    path = path or DEFAULT_CONFIG_PATH
    data: dict = {}
    if config.workspace:
        data["workspace"] = config.workspace

    if config.templates:
        data["templates"] = {}
        for name, hooks in config.templates.items():
            data["templates"][name] = _hooks_to_dict(hooks) or {}

    def _group_dict(group) -> dict:
        repos = []
        for repo in group.repos:
            r: dict = {"name": repo.name, "url": repo.url}
            if repo.path:
                r["path"] = repo.path
            if repo.template:
                r["template"] = repo.template
            hooks_dict = _hooks_to_dict(repo.hooks)
            if hooks_dict:
                r["hooks"] = hooks_dict
            if repo.branches:
                r["branches"] = repo.branches
            repos.append(r)
        return {"repos": repos}

    if config.has_markets:
        # Emit the markets layer.
        data["markets"] = {}
        for market in config.markets:
            if market.name == NO_MARKET:
                continue
            data["markets"][market.name] = {"groups": {g.name: _group_dict(g) for g in market.groups}}
        # Any stray no-market groups fall back to top-level (rare, mixed configs).
        legacy = [g for m in config.markets if m.name == NO_MARKET for g in m.groups]
        if legacy:
            data["groups"] = {g.name: _group_dict(g) for g in legacy}
    elif config.groups:
        # Legacy: no markets → top-level groups.
        data["groups"] = {g.name: _group_dict(g) for g in config.groups}

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def validate_config(config: GitmuxConfig) -> list[str]:
    """Validate config, return list of error messages."""
    errors = []
    repo_names: set[str] = set()
    group_names: set[str] = set()

    for group in config.groups:
        if group.name in group_names:
            errors.append(f"Duplicate group name: {group.name}")
        group_names.add(group.name)

        for repo in group.repos:
            if repo.name in repo_names:
                errors.append(f"Duplicate repo name: {repo.name}")
            repo_names.add(repo.name)

            if repo.template and repo.template not in config.templates:
                errors.append(f"Repo '{repo.name}' references unknown template: {repo.template}")

    return errors
