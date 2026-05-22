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

- Default: `{workspace}/{group}/{repo_name}`
- Override per-repo with the `path` field

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
gitmux pull --group base --branch dev  # checkout fixed branch for all repos in group
```

Rules:
- `--branch <alias>` — alias must be a fixed branch (no `*`), otherwise error
- `--branch <alias>:latest` — alias must be a pattern (has `*`), picks newest by commit date
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

### Target Syntax

```bash
gitmux pull map           # repo 'map' in default group
gitmux pull base/map      # repo 'map' in group 'base'
gitmux pull --group base  # all repos in group 'base'
gitmux pull --all         # all repos (explicit)
gitmux pull               # error: specify target, --group, or --all
```

Note: `gitmux add <url>` without `--group` places the repo in the `default` group.

### Common Options

- `--group, -g` — operate on entire group
- `--all, -a` — operate on all repositories (required for write operations without target)
- `--parallel, -p` — run in parallel (clone/fetch/pull/push/exec)
- `--config, -c` — custom config file path

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
