"""Tests for the workspace registry and its integration with workspace resolution."""

import pytest

from gitmux import registry
from gitmux.models import GitmuxConfig, GroupConfig, RepoConfig, WorkspaceError


@pytest.fixture
def temp_registry(tmp_path, monkeypatch):
    """Point the registry at a temp file so tests don't touch the real one."""
    reg = tmp_path / "workspaces.yaml"
    monkeypatch.setattr(registry, "registry_path", lambda: reg)
    return reg


def test_registry_set_get_unset(temp_registry, tmp_path):
    cfg = tmp_path / "mastercard.yaml"
    cfg.write_text("groups: {}\n")

    assert registry.get(cfg) is None
    key = registry.set_mapping(cfg, "/repos/mastercard")
    assert key == str(cfg.resolve())
    assert registry.get(cfg) == "/repos/mastercard"

    # persisted to disk
    assert temp_registry.exists()
    assert "/repos/mastercard" in temp_registry.read_text()

    assert registry.unset_mapping(cfg) is True
    assert registry.get(cfg) is None
    assert registry.unset_mapping(cfg) is False  # already gone


def test_registry_key_is_absolute(temp_registry, tmp_path, monkeypatch):
    cfg = tmp_path / "x.yaml"
    cfg.write_text("groups: {}\n")
    # set via relative path from within tmp_path
    monkeypatch.chdir(tmp_path)
    registry.set_mapping("x.yaml", "/ws/x")
    # get via absolute path resolves to the same key
    assert registry.get(cfg) == "/ws/x"


def test_resolve_workspace_registry_fallback(temp_registry, tmp_path):
    cfg_file = tmp_path / "m.yaml"
    cfg_file.write_text("groups: {}\n")
    registry.set_mapping(cfg_file, "/reg/ws")

    cfg = GitmuxConfig(workspace=None, config_path=cfg_file.resolve())
    assert str(cfg.resolve_workspace()) == "/reg/ws"


def test_precedence_override_beats_registry(temp_registry, tmp_path):
    cfg_file = tmp_path / "m.yaml"
    cfg_file.write_text("groups: {}\n")
    registry.set_mapping(cfg_file, "/reg/ws")

    cfg = GitmuxConfig(workspace=None, config_path=cfg_file.resolve())
    cfg.workspace_override = "/override"
    assert str(cfg.resolve_workspace()) == "/override"


def test_precedence_manifest_beats_registry(temp_registry, tmp_path):
    cfg_file = tmp_path / "m.yaml"
    cfg_file.write_text("groups: {}\n")
    registry.set_mapping(cfg_file, "/reg/ws")

    # manifest has explicit workspace → wins over registry
    cfg = GitmuxConfig(workspace="/manifest/ws", config_path=cfg_file.resolve())
    assert str(cfg.resolve_workspace()) == "/manifest/ws"


def test_resolve_workspace_none_no_registry_raises(temp_registry, tmp_path):
    cfg_file = tmp_path / "m.yaml"
    cfg = GitmuxConfig(workspace=None, config_path=cfg_file.resolve())
    with pytest.raises(WorkspaceError):
        cfg.resolve_workspace()


def test_get_repo_path_via_registry(temp_registry, tmp_path):
    cfg_file = tmp_path / "m.yaml"
    cfg_file.write_text("groups: {}\n")
    registry.set_mapping(cfg_file, "/reg/ws")

    cfg = GitmuxConfig.of_groups(
        workspace=None,
        config_path=cfg_file.resolve(),
        groups=[GroupConfig(name="g", repos=[RepoConfig(name="r", url="u")])],
    )
    path = cfg.get_repo_path(cfg.groups[0].repos[0], cfg.groups[0])
    assert str(path) == "/reg/ws/g/r"
