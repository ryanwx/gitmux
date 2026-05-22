"""Data models for gitmux configuration."""

from dataclasses import dataclass, field
from pathlib import Path


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


@dataclass
class GitmuxConfig:
    workspace: str = "~/projects"
    templates: dict[str, HookConfig] = field(default_factory=dict)
    groups: list[GroupConfig] = field(default_factory=list)

    def get_repo_path(self, repo: RepoConfig, group: GroupConfig) -> Path:
        """Resolve the local path for a repo."""
        if repo.path:
            return Path(repo.path).expanduser()
        return Path(self.workspace).expanduser() / group.name / repo.name

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
