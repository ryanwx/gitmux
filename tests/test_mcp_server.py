"""Smoke tests for the MCP server module.

These verify the server imports, registers the expected tools, and that tool
callables produce structured output against a temp config. They do not spin up
a real stdio transport.
"""

import pytest

from gitmux import mcp_server


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    cfg_path = tmp_path / ".gitmux.yaml"
    cfg_path.write_text(
        "workspace: /tmp/ws\n"
        "groups:\n"
        "  base:\n"
        "    repos:\n"
        "      - name: map\n"
        "        url: https://example.com/base/map.git\n"
        "        branches:\n"
        "          prod: 'app-plan-*'\n"
        "          dev: 'app-dev-main'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mcp_server, "_CONFIG_PATH", str(cfg_path))
    return cfg_path


def test_expected_tools_registered():
    import asyncio

    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {t.name for t in tools}
    expected = {
        "list_repos",
        "list_groups",
        "list_markets",
        "status",
        "fetch",
        "clone",
        "pull",
        "push",
        "add_repo",
        "remove_repo",
        "init_config",
        "workspace_set",
        "workspace_show",
        "workspace_unset",
    }
    assert expected.issubset(names)
    # Critically, no generic shell/exec tool is exposed.
    assert "exec" not in names
    assert "exec_command" not in names


def test_list_repos_tool(temp_config):
    out = mcp_server.list_repos()
    assert len(out) == 1
    assert out[0]["name"] == "map"
    assert out[0]["group"] == "base"
    assert out[0]["branches"]["prod"] == "app-plan-*"


def test_list_groups_tool(temp_config):
    out = mcp_server.list_groups()
    assert out == [{"market": "", "name": "base", "repo_count": 1}]


def test_status_tool_not_cloned(temp_config):
    out = mcp_server.status()
    assert out[0]["name"] == "map"
    assert out[0]["cloned"] is False


def test_add_and_remove_repo_tools(temp_config):
    added = mcp_server.add_repo("https://example.com/base/extra.git", group="base")
    assert added == {"added": "extra", "group": "base", "market": ""}
    # verify persisted
    assert any(r["name"] == "extra" for r in mcp_server.list_repos())

    removed = mcp_server.remove_repo("extra")
    assert removed == {"removed": "extra", "group": "base"}
    assert all(r["name"] != "extra" for r in mcp_server.list_repos())


def test_init_config_tool(tmp_path):
    p = tmp_path / "new.yaml"
    out = mcp_server.init_config(str(p), workspace="~/w")
    assert out["created"] == str(p)
    assert p.exists()


def test_workspace_tools(temp_config, tmp_path, monkeypatch):
    from gitmux import registry

    reg = tmp_path / "workspaces.yaml"
    monkeypatch.setattr(registry, "registry_path", lambda: reg)

    # set binding for the temp_config path
    out = mcp_server.workspace_set("/repos/mc", config=str(temp_config))
    assert out["workspace"] == "/repos/mc"
    assert out["config"] == str(temp_config.resolve())

    shown = mcp_server.workspace_show(config=str(temp_config))
    assert shown["workspace"] == "/repos/mc"

    # after binding, status resolves paths via the registry (no --workspace / env)
    monkeypatch.setattr(mcp_server, "_CONFIG_PATH", str(temp_config))
    monkeypatch.setattr(mcp_server, "_WORKSPACE", None)
    rep = mcp_server.status()
    assert rep[0]["name"] == "map"

    removed = mcp_server.workspace_unset(config=str(temp_config))
    assert removed["removed"] is True
