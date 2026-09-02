"""Data models for gitmux configuration."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

_ENV_PLACEHOLDER = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")


class WorkspaceError(Exception):
    """Raised when the workspace cannot be resolved (missing env var, unset, etc.)."""


def resolve_placeholders(value: str) -> str:
    """Resolve ${VAR} and ${VAR:-default} placeholders from the environment.

    Raises WorkspaceError if a referenced variable is unset and no default is given.
    Strings without placeholders are returned unchanged.
    """

    def _sub(match: re.Match) -> str:
        var, default = match.group(1), match.group(2)
        env_val = os.environ.get(var)
        if env_val is not None and env_val != "":
            return env_val
        if default is not None:
            return default
        raise WorkspaceError(
            f"Environment variable '{var}' referenced in config is not set "
            f"(use ${{{var}:-/default}} to provide a fallback, set the variable, or pass --workspace)."
        )

    return _ENV_PLACEHOLDER.sub(_sub, value)


@dataclass
class HookConfig:
    pre_clone: list[str] = field(default_factory=list)
    post_clone: list[str] = field(default_factory=list)
    pre_pull: list[str] = field(default_factory=list)
    post_pull: list[str] = field(default_factory=list)
    pre_push: list[str] = field(default_factory=list)
    post_push: list[str] = field(default_factory=list)


@dataclass
class RepoConfig:
    name: str
    url: str
    path: str | None = None
    template: str | None = None
    hooks: HookConfig = field(default_factory=HookConfig)
    branches: dict[str, str] = field(default_factory=dict)  # e.g. {"prod": "a-plan-*", "dev": "a-dev-main"}


@dataclass
class GroupConfig:
    name: str
    repos: list[RepoConfig] = field(default_factory=list)
    market: str = ""  # owning market name; "" = legacy/no-market config


@dataclass
class MarketConfig:
    name: str
    groups: list[GroupConfig] = field(default_factory=list)


# Sentinel market name for legacy top-level `groups:` (no markets layer).
NO_MARKET = ""


@dataclass
class GitmuxConfig:
    # None means "not set in the config file" → fall back to the registry.
    workspace: str | None = None
    templates: dict[str, HookConfig] = field(default_factory=dict)
    markets: list[MarketConfig] = field(default_factory=list)
    # Not persisted. Set at load time.
    workspace_override: str | None = field(default=None, compare=False)  # from --workspace (highest)
    config_path: Path | None = field(default=None, compare=False)  # source file, for registry lookup

    @property
    def groups(self) -> list[GroupConfig]:
        """Flattened view of all groups across markets (backward-compatible)."""
        result: list[GroupConfig] = []
        for m in self.markets:
            result.extend(m.groups)
        return result

    @classmethod
    def of_groups(cls, groups: list[GroupConfig], **kwargs) -> "GitmuxConfig":
        """Build a legacy (no-market) config from a flat list of groups."""
        for g in groups:
            if not g.market:
                g.market = NO_MARKET
        return cls(markets=[MarketConfig(name=NO_MARKET, groups=list(groups))], **kwargs)

    @property
    def has_markets(self) -> bool:
        """True if any real (named) market exists — i.e. not a legacy config."""
        return any(m.name != NO_MARKET for m in self.markets)

    def resolve_workspace(self) -> Path:
        """Resolve the effective workspace directory.

        Precedence (highest first):
          1. workspace_override        (--workspace / MCP --workspace)
          2. config 'workspace' field  (literal or ${ENV_VAR})
          3. registry binding          (~/.config/gitmux/workspaces.yaml, keyed by config path)
        Raises WorkspaceError if none resolves.
        """
        if self.workspace_override:
            return Path(resolve_placeholders(self.workspace_override)).expanduser()

        if self.workspace:
            return Path(resolve_placeholders(self.workspace)).expanduser()

        # Registry fallback (lazy import to keep models dependency-light).
        if self.config_path is not None:
            from gitmux import registry

            bound = registry.get(self.config_path)
            if bound:
                return Path(resolve_placeholders(bound)).expanduser()

        raise WorkspaceError(
            "No workspace resolved. Set 'workspace' in the config, pass --workspace, "
            "or bind one with 'gitmux workspace set -c <config> <path>'."
        )

    def get_repo_path(self, repo: RepoConfig, group: GroupConfig) -> Path:
        """Resolve the local path for a repo.

        Layout:
          - with market:  {workspace}/{market}/{group}/{repo}
          - legacy:       {workspace}/{group}/{repo}
        Per-repo `path` (if set) overrides everything.
        """
        if repo.path:
            return Path(resolve_placeholders(repo.path)).expanduser()
        base = self.resolve_workspace()
        if group.market and group.market != NO_MARKET:
            return base / group.market / group.name / repo.name
        return base / group.name / repo.name

    def find_market(self, name: str) -> MarketConfig | None:
        for m in self.markets:
            if m.name == name:
                return m
        return None

    def find_repo(self, name: str) -> tuple[RepoConfig, GroupConfig] | None:
        for group in self.groups:
            for repo in group.repos:
                if repo.name == name:
                    return repo, group
        return None

    def find_group(self, name: str) -> GroupConfig | None:
        for group in self.groups:
            if group.name == name:
                return group
        return None

    def all_repos(self) -> list[tuple[RepoConfig, GroupConfig]]:
        result = []
        for group in self.groups:
            for repo in group.repos:
                result.append((repo, group))
        return result

    def _default_market(self) -> "MarketConfig":
        """Return a market to hold new groups: first existing, else a NO_MARKET bucket."""
        if self.markets:
            return self.markets[0]
        m = MarketConfig(name=NO_MARKET)
        self.markets.append(m)
        return m

    def add_group(self, name: str, market: str | None = None) -> GroupConfig:
        """Add an empty group (into the given/first market). Caller checks duplicates."""
        if market is not None:
            mkt = self.find_market(market)
            if mkt is None:
                mkt = MarketConfig(name=market)
                self.markets.append(mkt)
        else:
            mkt = self._default_market()
        grp = GroupConfig(name=name, market=mkt.name)
        mkt.groups.append(grp)
        return grp

    def remove_group(self, group: GroupConfig) -> None:
        for m in self.markets:
            if group in m.groups:
                m.groups.remove(group)
                return
