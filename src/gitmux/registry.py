"""Local workspace registry.

Maps a config file's absolute path to the local workspace directory on THIS
machine. This is machine-local state (like ~/.gitconfig), not part of the
shareable repo manifest — so a manifest can omit 'workspace' entirely and each
environment binds its own local path once via `gitmux workspace set`.

File: ~/.config/gitmux/workspaces.yaml

    mappings:
      /abs/path/to/mastercard.yaml: /home/ryan/project/CIL/MasterCard/ReadOnly
      /abs/path/to/projectx.yaml:   /home/ryan/project/CIL/ProjectX/ReadOnly

Keyed by the config file's resolved absolute path.
"""

from pathlib import Path

import yaml


def registry_path() -> Path:
    """Location of the registry file: ~/.config/gitmux/workspaces.yaml.

    Uses Path.home() (honours $HOME, falls back to the password database) rather
    than a literal '~' so it behaves under services / non-login shells.
    """
    return Path.home() / ".config" / "gitmux" / "workspaces.yaml"


def _config_key(config_path: str | Path) -> str:
    """Normalise a config path to its absolute-path registry key."""
    return str(Path(config_path).expanduser().resolve())


def _load_raw() -> dict:
    path = registry_path()
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_mappings() -> dict[str, str]:
    """Return the full {config_abs_path: workspace} mapping."""
    data = _load_raw()
    return dict(data.get("mappings") or {})


def get(config_path: str | Path) -> str | None:
    """Look up the workspace bound to a config path, or None."""
    return load_mappings().get(_config_key(config_path))


def set_mapping(config_path: str | Path, workspace: str) -> str:
    """Bind a config path to a workspace directory. Returns the key used."""
    key = _config_key(config_path)
    mappings = load_mappings()
    mappings[key] = str(Path(workspace).expanduser())
    _write(mappings)
    return key


def unset_mapping(config_path: str | Path) -> bool:
    """Remove a binding. Returns True if something was removed."""
    key = _config_key(config_path)
    mappings = load_mappings()
    if key in mappings:
        del mappings[key]
        _write(mappings)
        return True
    return False


def _write(mappings: dict[str, str]) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump({"mappings": mappings}, f, default_flow_style=False, allow_unicode=True, sort_keys=True)
