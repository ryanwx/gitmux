"""Tests for config loading, saving, and validation."""

from pathlib import Path

from gitmux.config import find_config, load_config, save_config, validate_config
from gitmux.models import GitmuxConfig, GroupConfig, HookConfig, RepoConfig

SAMPLE_YAML = """\
workspace: ~/projects

templates:
  node-app:
    post_pull:
      - npm install
    pre_push:
      - npm test

groups:
  backend:
    repos:
      - name: api-server
        url: git@github.com:user/api-server.git
        template: node-app
      - name: auth-service
        url: git@github.com:user/auth-service.git
        path: ~/custom/path/auth
        hooks:
          post_pull:
            - pip install -r requirements.txt
  frontend:
    repos:
      - name: web-app
        url: git@github.com:user/web-app.git
        template: node-app
"""


def test_load_config(tmp_path: Path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(SAMPLE_YAML)

    config = load_config(cfg_file)
    assert config.workspace == "~/projects"
    assert "node-app" in config.templates
    assert config.templates["node-app"].post_pull == ["npm install"]
    assert len(config.groups) == 2
    assert config.groups[0].name == "backend"
    assert config.groups[0].repos[0].name == "api-server"
    assert config.groups[0].repos[1].path == "~/custom/path/auth"
    assert config.groups[0].repos[1].hooks.post_pull == ["pip install -r requirements.txt"]


def test_load_missing_file(tmp_path: Path):
    config = load_config(tmp_path / "nonexistent.yaml")
    # workspace is None when unset → resolution falls back to registry / --workspace
    assert config.workspace is None
    assert config.groups == []


def test_save_and_reload(tmp_path: Path):
    config = GitmuxConfig.of_groups(
        workspace="~/work",
        templates={"py-app": HookConfig(post_pull=["pip install -e ."])},
        groups=[
            GroupConfig(
                name="libs",
                repos=[
                    RepoConfig(name="core", url="git@github.com:u/core.git", template="py-app"),
                ],
            ),
        ],
    )
    cfg_file = tmp_path / "out.yaml"
    save_config(config, cfg_file)

    loaded = load_config(cfg_file)
    assert loaded.workspace == "~/work"
    assert loaded.templates["py-app"].post_pull == ["pip install -e ."]
    assert loaded.groups[0].repos[0].name == "core"
    assert loaded.groups[0].repos[0].template == "py-app"


def test_validate_duplicate_repo():
    config = GitmuxConfig.of_groups(
        groups=[
            GroupConfig(name="a", repos=[RepoConfig(name="x", url="u1")]),
            GroupConfig(name="b", repos=[RepoConfig(name="x", url="u2")]),
        ]
    )
    errors = validate_config(config)
    assert any("Duplicate repo name" in e for e in errors)


def test_validate_duplicate_group():
    config = GitmuxConfig.of_groups(
        groups=[
            GroupConfig(name="a", repos=[]),
            GroupConfig(name="a", repos=[]),
        ]
    )
    errors = validate_config(config)
    assert any("Duplicate group name" in e for e in errors)


def test_validate_unknown_template():
    config = GitmuxConfig.of_groups(
        groups=[
            GroupConfig(
                name="g",
                repos=[
                    RepoConfig(name="r", url="u", template="nonexistent"),
                ],
            ),
        ]
    )
    errors = validate_config(config)
    assert any("unknown template" in e for e in errors)


def test_validate_valid_config():
    config = GitmuxConfig.of_groups(
        templates={"t": HookConfig()},
        groups=[
            GroupConfig(
                name="g",
                repos=[
                    RepoConfig(name="r", url="u", template="t"),
                ],
            )
        ],
    )
    assert validate_config(config) == []


def test_find_config_local(tmp_path: Path, monkeypatch):
    """find_config returns local .gitmux.yaml if it exists."""
    local_cfg = tmp_path / ".gitmux.yaml"
    local_cfg.write_text("workspace: .")
    monkeypatch.chdir(tmp_path)
    assert find_config() == local_cfg


def test_find_config_fallback_home(tmp_path: Path, monkeypatch):
    """find_config falls back to ~/.gitmux.yaml when no local config."""
    monkeypatch.chdir(tmp_path)  # no .gitmux.yaml here
    result = find_config()
    assert result == Path.home() / ".gitmux.yaml"


def test_save_and_load_branches(tmp_path: Path):
    """Test branches field is saved and loaded correctly."""
    config = GitmuxConfig.of_groups(
        groups=[
            GroupConfig(
                name="g",
                repos=[
                    RepoConfig(name="r", url="u", branches={"prod": "app-plan-*", "dev": "app-dev-main"}),
                ],
            ),
        ],
    )
    cfg_file = tmp_path / "cfg.yaml"
    save_config(config, cfg_file)
    loaded = load_config(cfg_file)
    assert loaded.groups[0].repos[0].branches == {"prod": "app-plan-*", "dev": "app-dev-main"}


def test_get_repos_default_group(tmp_path: Path):
    """Test that bare repo name resolves to default group."""
    from gitmux.models import GitmuxConfig, GroupConfig, RepoConfig

    cfg = GitmuxConfig.of_groups(
        groups=[
            GroupConfig(name="default", repos=[RepoConfig(name="myrepo", url="u")]),
            GroupConfig(name="other", repos=[RepoConfig(name="other-repo", url="u2")]),
        ]
    )
    cfg_file = tmp_path / ".gitmux.yaml"
    save_config(cfg, cfg_file)
    loaded = load_config(cfg_file)

    # Bare name looks in default group
    assert loaded.find_group("default") is not None
    assert loaded.find_group("default").repos[0].name == "myrepo"


def test_config_with_default_group_roundtrip(tmp_path: Path):
    """Test that default group is preserved through save/load."""
    cfg = GitmuxConfig.of_groups(
        groups=[
            GroupConfig(
                name="default",
                repos=[
                    RepoConfig(name="app", url="https://example.com/app.git"),
                ],
            ),
        ]
    )
    cfg_file = tmp_path / "cfg.yaml"
    save_config(cfg, cfg_file)
    loaded = load_config(cfg_file)
    assert loaded.groups[0].name == "default"
    assert loaded.groups[0].repos[0].name == "app"


def test_markets_config_load_and_layout(tmp_path: Path):
    """A config using the markets layer loads and resolves the 4-segment path."""
    cfg_file = tmp_path / "m.yaml"
    cfg_file.write_text(
        "workspace: /ws\n"
        "markets:\n"
        "  mastercard:\n"
        "    groups:\n"
        "      rebate:\n"
        "        repos:\n"
        "          - name: bonus\n"
        "            url: https://x/mastercard/rebate/bonus.git\n"
        "            branches: { prod: 'bonus-plan-*' }\n",
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.has_markets is True
    grp = cfg.groups[0]
    assert grp.market == "mastercard"
    repo = grp.repos[0]
    assert str(cfg.get_repo_path(repo, grp)) == "/ws/mastercard/rebate/bonus"


def test_markets_config_roundtrip(tmp_path: Path):
    """Load a markets config, save it, reload — structure preserved."""
    src = tmp_path / "m.yaml"
    src.write_text(
        "workspace: /ws\n"
        "markets:\n"
        "  mc:\n"
        "    groups:\n"
        "      base:\n"
        "        repos:\n"
        "          - name: map\n"
        "            url: u\n",
        encoding="utf-8",
    )
    cfg = load_config(src)
    out = tmp_path / "out.yaml"
    save_config(cfg, out)
    reloaded = load_config(out)
    assert reloaded.has_markets is True
    assert reloaded.groups[0].market == "mc"
    assert reloaded.groups[0].name == "base"
    assert reloaded.groups[0].repos[0].name == "map"
