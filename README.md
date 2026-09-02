# gitmux

Manage multiple git repositories with ease. Clone, pull, push, and run commands across repos with a single command.

## Features

- **YAML configuration** — declarative repo management
- **Group management** — organize repos into groups
- **Batch git operations** — clone/pull/push across repos
- **Pre/post hooks** — run commands before/after git operations (e.g., `npm install` after pull)
- **Template system** — share hook configs across similar repos
- **Parallel execution** — speed up operations with `--parallel` flag
- **Status overview** — see all repos' git status at a glance
- **Arbitrary command execution** — run any shell command across repos

## Install

```bash
pip install gitmux
```

## Quick Start

```bash
# Initialize config in current directory
gitmux init

# Add repos (default group if --group omitted)
gitmux add git@github.com:user/api-server.git --group backend
gitmux add git@github.com:user/auth-service.git --group backend

# Clone all repos
gitmux clone --all

# Pull a single repo
gitmux pull backend/api-server

# Pull entire group (parallel)
gitmux pull --group backend --parallel

# Check status of all repos
gitmux status

# Run command on a specific repo
gitmux exec "git checkout main" --target backend/api-server
```

## Configuration

Config file lookup order (used for both reading and writing):
1. `--config / -c` flag (explicit path)
2. `.gitmux.yaml` in current directory
3. `~/.gitmux.yaml` (global fallback)

```yaml
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
        path: ~/custom/path/auth  # override default path
        hooks:
          post_pull:
            - pip install -r requirements.txt
  frontend:
    repos:
      - name: web-app
        url: git@github.com:user/web-app.git
        template: node-app
```

### Path Resolution

- With markets: `{workspace}/{market}/{group}/{repo_name}`
- Legacy (no markets): `{workspace}/{group}/{repo_name}`
- Override per-repo with the `path` field

### Markets (optional top layer)

For managing multiple markets/projects in **one config file** (so a single MCP server can
serve them all), wrap groups under a `markets:` layer:

```yaml
workspace: /home/ryan/project/CIL/ReadOnly    # or bind via registry / --workspace
markets:
  mastercard:
    groups:
      base:
        repos:
          - name: map
            url: https://code.example.net/mastercard/base/map.git
            branches: { prod: "icbcMap-plan-*" }
      rebate:
        repos:
          - name: bonus
            branches: { prod: "bonus-plan-*", cmbProd: "cmbRebate-plan-*" }
  projectx:
    groups:
      core:
        repos: [ { name: svc, url: https://code.example.net/projectx/core/svc.git } ]
```

- **Target becomes three-segment**: `market/group/repo`
  ```bash
  gitmux pull mastercard/rebate/bonus -b prod:~20260902
  gitmux status --market mastercard          # scope to a market
  gitmux status -m mastercard -g rebate      # a group within a market
  ```
- **Path layout**: `{workspace}/{market}/{group}/{repo}`
- **Backward compatible**: a config with a top-level `groups:` (no `markets:`) keeps the
  old two-segment targets (`group/repo`) and `{workspace}/{group}/{repo}` layout.



#### Workspace resolution (env placeholders & overrides)

The `workspace` value (and per-repo `path`) supports `${ENV_VAR}` placeholders, so a
config file can be a shareable "repo manifest" that contains **no machine-specific
path** — each environment supplies the real location:

```yaml
# mastercard.yaml — a portable document; the real path comes from the environment
workspace: ${MASTERCARD_WORKSPACE}
groups:
  rebate:
    repos:
      - name: bonus
        url: https://code.example.net/mastercard/rebate/bonus.git
        branches:
          prod: "bonus-plan-*"
```

Resolution precedence (highest first):

1. `--workspace / -w` flag (CLI) or `--workspace` (MCP server)
2. `workspace:` field in the config, with `${VAR}` / `${VAR:-/default}` expanded from the environment
3. **Registry binding** — a local `config → workspace` map (see below)
4. Otherwise → clear error (unset variable, no default, no flag, no binding)

```bash
# supply the path via environment
export MASTERCARD_WORKSPACE=/home/ryan/project/CIL/MasterCard/ReadOnly
gitmux pull rebate/bonus -b prod:~20260902 -c mastercard.yaml

# or override for one invocation
gitmux status -c mastercard.yaml --workspace /tmp/scratch
```

A literal path (`workspace: /abs/path`) still works unchanged. This lets one manifest
map to different local workspaces per machine/container (e.g. your dev box vs. an agent
container), and lets multiple manifests each declare their own `${..._WORKSPACE}` var.

#### Workspace registry (bind once, no env vars)

For the cleanest setup, **omit `workspace` from the manifest entirely** (making it a pure,
shareable repo document) and bind the local path once per machine. The binding lives in a
machine-local registry — `~/.config/gitmux/workspaces.yaml` — keyed by the config's
absolute path. No environment variables involved.

```bash
# bind once on this machine
gitmux workspace set -c mastercard.yaml /home/ryan/project/CIL/MasterCard/ReadOnly

# from then on, --config alone resolves the workspace
gitmux pull rebate/bonus -b prod:~20260902 -c mastercard.yaml

gitmux workspace show                    # list all bindings + registry location
gitmux workspace show  -c mastercard.yaml   # effective workspace for one config
gitmux workspace unset -c mastercard.yaml   # remove a binding
```

Registry file:

```yaml
# ~/.config/gitmux/workspaces.yaml  (machine-local; do not commit)
mappings:
  /home/ryan/gitmux/mastercard.yaml: /home/ryan/project/CIL/MasterCard/ReadOnly
  /home/ryan/gitmux/projectx.yaml:   /home/ryan/project/CIL/ProjectX/ReadOnly
```

Because the manifest carries no path, the same file works on your dev box and inside an
agent container — each environment binds its own local path once (in the container, run
`gitmux workspace set` / the `workspace_set` MCP tool with the container's mount path).

### Branch Management

Configure named branch aliases per repo:

```yaml
repos:
  - name: map
    url: https://code.example.com/base/map.git
    branches:
      prod: "bInfinite-plan-*"    # pattern (contains *)
      dev: "bInfinite-dev-main"   # fixed branch name
```

Usage:

```bash
gitmux pull map --branch dev           # checkout fixed branch → pull
gitmux pull map --branch prod:latest   # fetch → find newest matching branch → checkout → pull
gitmux pull map --branch prod:260515   # replace * → checkout bInfinite-plan-260515 → pull
gitmux pull map --branch prod:~260520  # fetch → find latest branch with date <= 260520 → checkout → pull
gitmux pull --group base --branch dev  # checkout fixed branch for all repos in group
```

Rules:
- `--branch <alias>` — alias must be a fixed branch (no `*`), otherwise error
- `--branch <alias>:latest` — alias must be a pattern (has `*`), picks newest by commit date
- `--branch <alias>:~<date>` — alias must be a pattern, picks newest matching branch with date ≤ `<date>`
- `--branch <alias>:<value>` — alias must be a pattern, replaces `*` with `<value>`

### Hook System

Hooks run shell commands before/after git operations:

- `pre_clone`, `post_clone`
- `pre_pull`, `post_pull`
- `pre_push`, `post_push`

**Error handling:**
- Pre-hook failure → git operation is skipped
- Post-hook failure → repo marked as failed

**Template merging:** Repo-level hooks override template hooks per hook type.

## Commands

| Command | Description |
|---------|-------------|
| `gitmux init` | Create `.gitmux.yaml` in current dir (`--global` for `~/.gitmux.yaml`) |
| `gitmux add <url> --group <g>` | Add a repository (group auto-created) |
| `gitmux remove <name>` | Remove a repository |
| `gitmux list` | List all repositories |
| `gitmux status [target]` | Show git status overview (defaults to all) |
| `gitmux clone <target>` | Clone unclosed repositories |
| `gitmux fetch <target>` | Fetch remote data (`--branches` to list branches) |
| `gitmux pull <target>` | Pull latest changes |
| `gitmux push <target>` | Push local commits |
| `gitmux exec <cmd>` | Run command in repos (`--target` to specify) |
| `gitmux group list` | List groups |
| `gitmux group create <name>` | Create a group |
| `gitmux group remove <name>` | Remove a group |
| `gitmux workspace set <path> -c <cfg>` | Bind a config to a local workspace (registry) |
| `gitmux workspace show [-c <cfg>]` | Show workspace bindings |
| `gitmux workspace unset -c <cfg>` | Remove a config→workspace binding |

### Target Syntax

```bash
gitmux pull map           # repo 'map' in default group
gitmux pull base/map      # repo 'map' in group 'base'
gitmux pull --group base  # all repos in group 'base'
gitmux pull --all         # all repos (explicit)
gitmux pull               # error: specify target, --group, or --all
```

With a **markets** config, targets are three-segment and `--market` scopes operations:

```bash
gitmux pull mastercard/base/map      # repo 'map' in market/group
gitmux pull --market mastercard      # all repos in a market
gitmux pull -m mastercard -g rebate  # a group within a market
```

Note: `gitmux add <url>` without `--group` places the repo in the `default` group.

### Common Options

- `--group, -g` — operate on entire group
- `--market, -m` — scope to a market (configs using the markets layer)
- `--all, -a` — operate on all repositories (required for write operations without target)
- `--parallel, -p` — run in parallel (clone/fetch/pull/push/exec)
- `--json` — emit structured JSON instead of formatted tables (for scripts/CI; `list`, `status`, `clone`, `fetch`, `pull`, `push`, `exec`)
- `--workspace, -w` — override the workspace directory (highest precedence; also settable via `${ENV_VAR}` in the config)
- `--config, -c` — custom config file path

## MCP Server (for AI agents)

gitmux ships an [MCP](https://modelcontextprotocol.io) server so AI agents can manage
repositories through a **fixed set of tools** instead of being granted shell access.
The tool set *is* the capability boundary — there is deliberately **no generic
`exec`/shell tool**, so an agent literally cannot run arbitrary commands.

### Install

```bash
pip install "gitmux[mcp]"
```

### Transport & security

- **stdio only, no authentication.** The server runs as a child process of the
  agent on the same machine; the security boundary is the OS/process. There is no
  network listener, so no token is needed or used.
- For remote/cross-machine use you would need an HTTP transport with auth — not
  provided here by design (keeps the local least-privilege model simple).

### Run

```bash
gitmux-mcp                    # config lookup: ./.gitmux.yaml → ~/.gitmux.yaml
gitmux-mcp --config /path/to/.gitmux.yaml
gitmux-mcp --config /path/to/mastercard.yaml --workspace /repos/mastercard
```

The `--workspace` flag (or a `${ENV_VAR}` placeholder in the config) lets one shared
manifest resolve to the correct local path inside the agent's environment — e.g. a
different path in a Crew container than on your dev machine.

### Agent configuration (example)

Kiro / Claude Desktop style `mcpServers` entry:

```json
{
  "mcpServers": {
    "gitmux": {
      "command": "gitmux-mcp",
      "args": ["--config", "/home/you/.gitmux.yaml"],
      "env": { "MASTERCARD_WORKSPACE": "/home/you/repos/mastercard" }
    }
  }
}
```

The config's `workspace: ${MASTERCARD_WORKSPACE}` is then resolved from `env` above
(or pass `--workspace /path` in `args` instead). One MCP server per manifest keeps each
market/project isolated — the agent only sees what that config exposes.

### Exposed tools

| Tool | Kind | Description |
|------|------|-------------|
| `list_repos` | read | List repos (optional `group` filter) |
| `list_groups` | read | List groups and repo counts |
| `list_markets` | read | List markets and group counts (empty for legacy configs) |
| `status` | read | Git status per repo (branch/clean/ahead/behind/last commit) |
| `fetch` | read | Fetch remotes (optional `show_branches`) |
| `clone` | action | Clone repos not yet cloned (idempotent) |
| `pull` | action | Pull; supports branch aliases (`dev`, `prod:latest`, `prod:~260520`, `prod:260524`) |
| `push` | action | Push local commits |
| `add_repo` | config | Add a repo declaration to the YAML (does not clone) |
| `remove_repo` | config | Remove a repo declaration (does not delete cloned dir) |
| `init_config` | config | Create a new config file (non-interactive) |
| `workspace_set` | config | Bind this config to a local workspace (registry) |
| `workspace_show` | read | Show workspace registry bindings |
| `workspace_unset` | config | Remove a config→workspace binding |

Selection args on the git tools: pass one of `target` (`"market/group/repo"` with markets,
or `"group/repo"` / `"repo"` legacy), `market`, `group`, or `all_repos=True`. Every tool
returns structured JSON.

**Not exposed:** arbitrary shell/`exec`. If a specific command is ever needed, add a
purpose-built, parameter-constrained tool rather than a generic shell escape hatch.

## Development

```bash
git clone https://github.com/ryan/gitmux.git
cd gitmux
pip install -e ".[dev]"
pytest
```

### Code Quality

Uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
ruff check .          # lint
ruff check --fix .    # auto-fix
ruff format .         # format
```

Rules: `E`, `F`, `W`, `I` (isort), `N`, `UP` (modern Python), `B` (bugbear), `SIM`.

## License

MIT
