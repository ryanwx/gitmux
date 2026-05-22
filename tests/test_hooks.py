"""Tests for hook execution and template merging."""

from pathlib import Path

from gitmux.hooks import resolve_hooks, run_hooks
from gitmux.models import GitmuxConfig, HookConfig, RepoConfig


def test_run_hooks_success(tmp_path: Path):
    result = run_hooks(["echo hello"], tmp_path)
    assert result.success


def test_run_hooks_failure(tmp_path: Path):
    result = run_hooks(["exit 1"], tmp_path)
    assert not result.success
    assert result.failed_command == "exit 1"


def test_run_hooks_empty(tmp_path: Path):
    result = run_hooks([], tmp_path)
    assert result.success


def test_run_hooks_stops_on_first_failure(tmp_path: Path):
    marker = tmp_path / "marker.txt"
    # Second command should not run if first fails
    result = run_hooks(["exit 1", f"echo done > {marker}"], tmp_path)
    assert not result.success
    assert not marker.exists()


def test_resolve_hooks_no_template():
    repo = RepoConfig(name="r", url="u", hooks=HookConfig(post_pull=["cmd1"]))
    config = GitmuxConfig()
    hooks = resolve_hooks(repo, config)
    assert hooks.post_pull == ["cmd1"]


def test_resolve_hooks_template_only():
    repo = RepoConfig(name="r", url="u", template="t")
    config = GitmuxConfig(templates={"t": HookConfig(post_pull=["tpl_cmd"])})
    hooks = resolve_hooks(repo, config)
    assert hooks.post_pull == ["tpl_cmd"]


def test_resolve_hooks_repo_overrides_template():
    repo = RepoConfig(name="r", url="u", template="t", hooks=HookConfig(post_pull=["repo_cmd"]))
    config = GitmuxConfig(templates={"t": HookConfig(post_pull=["tpl_cmd"])})
    hooks = resolve_hooks(repo, config)
    assert hooks.post_pull == ["repo_cmd"]


def test_resolve_hooks_template_fills_gaps():
    repo = RepoConfig(name="r", url="u", template="t", hooks=HookConfig(post_pull=["repo_cmd"]))
    config = GitmuxConfig(templates={"t": HookConfig(post_pull=["tpl_pull"], pre_push=["tpl_push"])})
    hooks = resolve_hooks(repo, config)
    assert hooks.post_pull == ["repo_cmd"]  # repo overrides
    assert hooks.pre_push == ["tpl_push"]  # template fills gap
