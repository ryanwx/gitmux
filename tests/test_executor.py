"""Tests for executor (serial and parallel)."""

from gitmux.executor import run_parallel, run_serial
from gitmux.git_ops import GitResult
from gitmux.models import GitmuxConfig, GroupConfig, RepoConfig


def _make_config():
    return GitmuxConfig.of_groups(
        workspace="/tmp/test",
        groups=[
            GroupConfig(
                name="g",
                repos=[
                    RepoConfig(name="r1", url="u1"),
                    RepoConfig(name="r2", url="u2"),
                    RepoConfig(name="r3", url="u3"),
                ],
            )
        ],
    )


def _success_op(repo, group, config):
    return GitResult(success=True, output=f"ok:{repo.name}", command="test")


def _fail_op(repo, group, config):
    if repo.name == "r2":
        return GitResult(success=False, output="error", command="test")
    return GitResult(success=True, output="ok", command="test")


def test_run_parallel_all_success():
    cfg = _make_config()
    repos = cfg.all_repos()
    results = run_parallel(cfg, repos, _success_op, "Test")
    assert len(results) == 3
    assert all(r.success for r in results)


def test_run_parallel_with_failure():
    cfg = _make_config()
    repos = cfg.all_repos()
    results = run_parallel(cfg, repos, _fail_op, "Test")
    assert len(results) == 3
    failed = [r for r in results if not r.success]
    assert len(failed) == 1
    assert failed[0].repo_name == "r2"


def test_run_serial_all_success():
    cfg = _make_config()
    repos = cfg.all_repos()
    results = run_serial(cfg, repos, _success_op, "Test")
    assert len(results) == 3
    assert all(r.success for r in results)
