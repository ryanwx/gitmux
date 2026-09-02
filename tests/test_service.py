"""Tests for the service layer (target resolution, branch resolution, config ops)."""

import subprocess
from pathlib import Path

import pytest

from gitmux import git_ops, service
from gitmux.models import GitmuxConfig, GroupConfig, RepoConfig
from gitmux.service import ServiceError


def _cfg():
    return GitmuxConfig.of_groups(
        workspace="/tmp/ws",
        groups=[
            GroupConfig(
                name="base",
                repos=[
                    RepoConfig(
                        name="map",
                        url="u",
                        branches={"prod": "app-plan-*", "dev": "app-dev-main"},
                    )
                ],
            ),
            GroupConfig(name="default", repos=[RepoConfig(name="solo", url="u2")]),
        ],
    )


# --- get_repos ------------------------------------------------------------


def test_get_repos_by_group_qualified_target():
    cfg = _cfg()
    repos = service.get_repos(cfg, target="base/map")
    assert len(repos) == 1
    assert repos[0][0].name == "map"


def test_get_repos_default_group_bare_target():
    cfg = _cfg()
    repos = service.get_repos(cfg, target="solo")
    assert repos[0][0].name == "solo"
    assert repos[0][1].name == "default"


def test_get_repos_group():
    cfg = _cfg()
    repos = service.get_repos(cfg, group="base")
    assert [r.name for r, _ in repos] == ["map"]


def test_get_repos_all():
    cfg = _cfg()
    repos = service.get_repos(cfg, all_=True)
    assert len(repos) == 2


def test_get_repos_no_selector_errors():
    with pytest.raises(ServiceError):
        service.get_repos(_cfg())


def test_get_repos_unknown_group():
    with pytest.raises(ServiceError):
        service.get_repos(_cfg(), group="nope")


def test_get_repos_unknown_repo():
    with pytest.raises(ServiceError):
        service.get_repos(_cfg(), target="base/ghost")


# --- resolve_branch -------------------------------------------------------


def test_resolve_branch_none():
    repo = _cfg().groups[0].repos[0]
    target, err = service.resolve_branch(repo, None, Path("/tmp"))
    assert target is None and err is None


def test_resolve_branch_fixed_alias():
    repo = _cfg().groups[0].repos[0]
    target, err = service.resolve_branch(repo, "dev", Path("/tmp"))
    assert target == "app-dev-main"
    assert err is None


def test_resolve_branch_fixed_alias_used_as_pattern_errors():
    repo = _cfg().groups[0].repos[0]
    # 'dev' is fixed; using ':latest' should fail
    target, err = service.resolve_branch(repo, "dev:latest", Path("/tmp"))
    assert target is None
    assert err is not None and not err.success


def test_resolve_branch_pattern_without_value_errors():
    repo = _cfg().groups[0].repos[0]
    # 'prod' is a pattern; must be used with :latest / :value
    target, err = service.resolve_branch(repo, "prod", Path("/tmp"))
    assert target is None
    assert err is not None and not err.success


def test_resolve_branch_replace_value():
    repo = _cfg().groups[0].repos[0]
    target, err = service.resolve_branch(repo, "prod:260524", Path("/tmp"))
    assert target == "app-plan-260524"
    assert err is None


def test_resolve_branch_unknown_alias():
    repo = _cfg().groups[0].repos[0]
    target, err = service.resolve_branch(repo, "stage", Path("/tmp"))
    assert target is None
    assert err is not None and "not configured" in err.output


def test_resolve_branch_latest(tmp_path: Path):
    """':latest' picks the newest matching remote branch (fetches internally)."""
    bare = tmp_path / "bare.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", str(bare), str(work)], capture_output=True)
    (work / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=work, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=T", "commit", "-m", "c"],
        cwd=work,
        capture_output=True,
    )
    subprocess.run(["git", "push", "origin", "HEAD:app-plan-260501"], cwd=work, capture_output=True)
    subprocess.run(["git", "push", "origin", "HEAD:app-plan-260515"], cwd=work, capture_output=True)

    dest = tmp_path / "dest"
    git_ops.clone(str(bare), dest)

    repo = RepoConfig(name="map", url=str(bare), branches={"prod": "app-plan-*"})
    target, err = service.resolve_branch(repo, "prod:latest", dest)
    assert err is None
    assert target in ("app-plan-260501", "app-plan-260515")


def test_resolve_branch_date_bound(tmp_path: Path):
    """':~date' picks the newest matching branch with date <= given date."""
    bare = tmp_path / "bare.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", str(bare), str(work)], capture_output=True)
    (work / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=work, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=T", "commit", "-m", "c"],
        cwd=work,
        capture_output=True,
    )
    subprocess.run(["git", "push", "origin", "HEAD:app-plan-260501"], cwd=work, capture_output=True)
    subprocess.run(["git", "push", "origin", "HEAD:app-plan-260601"], cwd=work, capture_output=True)

    dest = tmp_path / "dest"
    git_ops.clone(str(bare), dest)
    repo = RepoConfig(name="map", url=str(bare), branches={"prod": "app-plan-*"})

    target, err = service.resolve_branch(repo, "prod:~260515", dest)
    assert err is None
    assert target == "app-plan-260501"  # only branch with date <= 260515


# --- config mutations -----------------------------------------------------


def test_add_repo_and_conflict():
    cfg = _cfg()
    repo = service.add_repo(cfg, "git@x:y/newrepo.git", group="base")
    assert repo.name == "newrepo"
    assert cfg.find_repo("newrepo") is not None
    with pytest.raises(ServiceError):
        service.add_repo(cfg, "git@x:y/newrepo.git", group="base")


def test_add_repo_creates_group():
    cfg = _cfg()
    service.add_repo(cfg, "u", group="fresh", name="r")
    assert cfg.find_group("fresh") is not None


def test_add_repo_unknown_template():
    with pytest.raises(ServiceError):
        service.add_repo(_cfg(), "u", name="r", template="ghost")


def test_remove_repo():
    cfg = _cfg()
    grp = service.remove_repo(cfg, "map")
    assert grp == "base"
    assert cfg.find_repo("map") is None


def test_remove_repo_missing():
    with pytest.raises(ServiceError):
        service.remove_repo(_cfg(), "ghost")


def test_repo_name_from_url():
    assert service.repo_name_from_url("git@github.com:u/api-server.git") == "api-server"
    assert service.repo_name_from_url("https://x/y/web/") == "web"


def test_init_config(tmp_path: Path):
    p = tmp_path / ".gitmux.yaml"
    created = service.init_config(p, workspace="~/w")
    assert created.exists()
    with pytest.raises(ServiceError):
        service.init_config(p)  # exists, no overwrite
    service.init_config(p, overwrite=True)  # ok


# --- status_report --------------------------------------------------------


def test_status_report_not_cloned():
    cfg = _cfg()
    repos = service.get_repos(cfg, all_=True)
    report = service.status_report(cfg, repos)
    assert all(entry["cloned"] is False for entry in report)
    assert {e["name"] for e in report} == {"map", "solo"}


# --- workspace resolution -------------------------------------------------


def test_workspace_literal_path():
    from gitmux.models import GitmuxConfig, GroupConfig, RepoConfig

    cfg = GitmuxConfig.of_groups(
        workspace="/abs/ws", groups=[GroupConfig(name="g", repos=[RepoConfig(name="r", url="u")])]
    )
    repo, grp = cfg.groups[0].repos[0], cfg.groups[0]
    assert str(cfg.get_repo_path(repo, grp)) == "/abs/ws/g/r"


def test_workspace_env_placeholder(monkeypatch):
    from gitmux.models import GitmuxConfig, GroupConfig, RepoConfig

    monkeypatch.setenv("MC_WS", "/env/ws")
    cfg = GitmuxConfig.of_groups(
        workspace="${MC_WS}", groups=[GroupConfig(name="g", repos=[RepoConfig(name="r", url="u")])]
    )
    assert str(cfg.resolve_workspace()) == "/env/ws"
    assert str(cfg.get_repo_path(cfg.groups[0].repos[0], cfg.groups[0])) == "/env/ws/g/r"


def test_workspace_placeholder_default(monkeypatch):
    from gitmux.models import GitmuxConfig

    monkeypatch.delenv("MISSING_WS", raising=False)
    cfg = GitmuxConfig(workspace="${MISSING_WS:-/fallback}")
    assert str(cfg.resolve_workspace()) == "/fallback"


def test_workspace_placeholder_unset_raises(monkeypatch):
    from gitmux.models import GitmuxConfig, WorkspaceError

    monkeypatch.delenv("NOPE_WS", raising=False)
    cfg = GitmuxConfig(workspace="${NOPE_WS}")
    with pytest.raises(WorkspaceError):
        cfg.resolve_workspace()


def test_workspace_override_wins(monkeypatch):
    from gitmux.models import GitmuxConfig

    monkeypatch.setenv("MC_WS", "/env/ws")
    cfg = GitmuxConfig(workspace="${MC_WS}")
    cfg.workspace_override = "/override/ws"
    assert str(cfg.resolve_workspace()) == "/override/ws"


def test_service_load_workspace_override(tmp_path, monkeypatch):
    cfg_file = tmp_path / ".gitmux.yaml"
    cfg_file.write_text(
        "workspace: ${SOME_WS}\ngroups:\n  g:\n    repos:\n      - name: r\n        url: u\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("SOME_WS", raising=False)
    # No env, no override → resolving workspace raises
    cfg = service.load(cfg_file)
    from gitmux.models import WorkspaceError

    with pytest.raises(WorkspaceError):
        cfg.resolve_workspace()
    # With override → resolves
    cfg2 = service.load(cfg_file, workspace="/ovr")
    assert str(cfg2.resolve_workspace()) == "/ovr"


def test_repo_path_placeholder(monkeypatch):
    from gitmux.models import GitmuxConfig, GroupConfig, RepoConfig

    monkeypatch.setenv("CUSTOM", "/custom/loc")
    cfg = GitmuxConfig.of_groups(
        workspace="/ws",
        groups=[GroupConfig(name="g", repos=[RepoConfig(name="r", url="u", path="${CUSTOM}/r")])],
    )
    assert str(cfg.get_repo_path(cfg.groups[0].repos[0], cfg.groups[0])) == "/custom/loc/r"


# --- markets layer --------------------------------------------------------


def _market_cfg():
    from gitmux.models import GitmuxConfig, GroupConfig, MarketConfig, RepoConfig

    return GitmuxConfig(
        workspace="/ws",
        markets=[
            MarketConfig(
                name="mastercard",
                groups=[
                    GroupConfig(name="base", market="mastercard", repos=[RepoConfig(name="map", url="u1")]),
                    GroupConfig(name="rebate", market="mastercard", repos=[RepoConfig(name="bonus", url="u2")]),
                ],
            ),
            MarketConfig(
                name="projectx",
                groups=[GroupConfig(name="core", market="projectx", repos=[RepoConfig(name="svc", url="u3")])],
            ),
        ],
    )


def test_has_markets():
    assert _market_cfg().has_markets is True


def test_market_path_layout():
    cfg = _market_cfg()
    repo, grp = service.get_repos(cfg, target="mastercard/rebate/bonus")[0]
    assert str(cfg.get_repo_path(repo, grp)) == "/ws/mastercard/rebate/bonus"


def test_market_target_three_segment():
    cfg = _market_cfg()
    repos = service.get_repos(cfg, target="mastercard/base/map")
    assert len(repos) == 1 and repos[0][0].name == "map"


def test_market_target_unknown_market():
    cfg = _market_cfg()
    with pytest.raises(ServiceError):
        service.get_repos(cfg, target="nope/base/map")


def test_market_selector_all_in_market():
    cfg = _market_cfg()
    repos = service.get_repos(cfg, market="mastercard")
    assert {r.name for r, _ in repos} == {"map", "bonus"}


def test_market_selector_group_in_market():
    cfg = _market_cfg()
    repos = service.get_repos(cfg, market="mastercard", group="rebate")
    assert [r.name for r, _ in repos] == ["bonus"]


def test_market_all_repos():
    cfg = _market_cfg()
    repos = service.get_repos(cfg, all_=True)
    assert {r.name for r, _ in repos} == {"map", "bonus", "svc"}


def test_market_add_repo_into_market():
    cfg = _market_cfg()
    repo = service.add_repo(cfg, "https://x/y/newsvc.git", group="core", market="projectx")
    assert repo.name == "newsvc"
    _, grp = cfg.find_repo("newsvc")
    assert grp.market == "projectx"


def test_legacy_config_no_market_path():
    # legacy (no markets) keeps {workspace}/{group}/{repo}
    cfg = _cfg()
    cfg.workspace = "/ws"
    assert cfg.has_markets is False
    repo, grp = service.get_repos(cfg, target="base/map")[0]
    assert str(cfg.get_repo_path(repo, grp)) == "/ws/base/map"
