"""Hook execution and template merging logic."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from gitmux.models import GitmuxConfig, HookConfig, RepoConfig
from gitmux.output import console


@dataclass
class HookResult:
    success: bool
    failed_command: str | None = None
    output: str = ""


def resolve_hooks(repo: RepoConfig, config: GitmuxConfig) -> HookConfig:
    """Merge template hooks with repo-level hooks. Repo-level overrides template."""
    if not repo.template:
        return repo.hooks

    template = config.templates.get(repo.template)
    if not template:
        return repo.hooks

    # For each hook type, use repo's if non-empty, else template's
    merged = HookConfig()
    for field in ("pre_clone", "post_clone", "pre_pull", "post_pull", "pre_push", "post_push"):
        repo_val = getattr(repo.hooks, field)
        template_val = getattr(template, field)
        setattr(merged, field, repo_val if repo_val else template_val)
    return merged


def run_hooks(commands: list[str], cwd: Path, label: str = "") -> HookResult:
    """Execute a list of hook commands sequentially in the given directory."""
    if not commands:
        return HookResult(success=True)

    for cmd in commands:
        if label:
            console.print(f"    [dim]hook ({label}):[/] {cmd}")
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                output = (result.stdout + result.stderr).strip()
                return HookResult(success=False, failed_command=cmd, output=output)
        except subprocess.TimeoutExpired:
            return HookResult(success=False, failed_command=cmd, output="Timed out (120s)")

    return HookResult(success=True)
