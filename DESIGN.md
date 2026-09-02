# gitmux - Design Document

## Overview

gitmux 是一个 Python CLI 工具，通过 YAML 配置文件管理多个 git 仓库，支持批量 git 操作、分组管理、前后置 hook、并行/串行执行模式。

## Architecture

```
src/gitmux/
├── cli.py          # Typer CLI 入口，子命令定义（Rich 输出 + --json）
├── mcp_server.py   # MCP server（stdio，无 token）— 给 AI agent 用的工具集
├── service.py      # Rich-free 核心逻辑（target/branch 解析、运行操作、配置增删）
├── registry.py     # 本地 config→workspace 映射（~/.config/gitmux/workspaces.yaml）
├── config.py       # YAML 配置加载/验证/保存
├── models.py       # 数据模型（Repo, Group, Hook, Template）
├── executor.py     # 命令执行引擎（串行/并行）
├── git_ops.py      # Git 操作封装
├── hooks.py        # Hook 执行逻辑
└── output.py       # 输出格式化（Rich 表格、进度条）
```

### 分层说明

- `service.py` 是**不含终端输出**的核心层：解析 target、解析 branch 别名、运行操作
  （复用 `executor._execute_one`，含 hook）、状态汇总、配置增删/初始化。返回结构化数据。
- `cli.py`（给人用）在 service 之上叠加 Rich 输出；`--json` 直接吐 service 的结构化结果。
- `mcp_server.py`（给 agent 用）在 service 之上暴露 MCP 工具，返回结构化 JSON。
- 分支别名解析逻辑只在 `service.resolve_branch` 一处，CLI 与 MCP 共用，避免重复。

## Configuration Format

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
        path: ~/custom/path/auth
        hooks:
          post_pull:
            - pip install -r requirements.txt
        branches:
          prod: "auth-plan-*"
          dev: "auth-dev-main"
  frontend:
    repos:
      - name: web-app
        url: git@github.com:user/web-app.git
        template: node-app
```

## CLI Commands

```
gitmux init                          # 初始化配置文件
gitmux add <url> --group=<group>     # 添加仓库
gitmux remove <name>                 # 移除仓库
gitmux list                          # 列出所有仓库
gitmux status [--group=<group>]      # 状态总览
gitmux clone [--group=<group>]       # 克隆未克隆的仓库
gitmux fetch [--group=<group>] [--branches] [--parallel]
gitmux pull [--group=<group>] [--branch=<alias|alias:latest|alias:value>] [--parallel]
gitmux push [--group=<group>] [--parallel]
gitmux exec <command> [--group=<group>] [--parallel]
gitmux group list
gitmux group create <name>
gitmux group remove <name>
```

## Execution Flow

1. 用户执行命令
2. 查找配置文件：`--config` 指定 → 当前目录 `.gitmux.yaml` → `~/.gitmux.yaml`
3. 加载配置，解析目标仓库列表（按 --group 过滤）
3. 判断串行/并行模式
4. 对每个仓库执行：pre-hook → git 操作 → post-hook
5. 输出结果

### Hook 错误处理
- pre-hook 失败 → 中断该仓库的 git 操作
- post-hook 失败 → 标记仓库失败

### 输出模式
- 串行：实时输出，显示当前仓库名和执行步骤
- 并行：Rich 进度条，完成后汇总（成功/失败/详情）

## Technical Stack
- CLI: Typer
- Terminal UI: Rich
- Config: PyYAML
- Parallelism: concurrent.futures.ThreadPoolExecutor
- Git: subprocess
- MCP: `mcp` SDK (>=2, `MCPServer`) — optional extra `gitmux[mcp]`
- Testing: pytest
- Build: hatchling

## Workspace 解析设计

`workspace`（仓库本地根目录）与"仓库清单"分离,让配置文件能当作可共享文档(不含机器路径)。

**解析优先级(高→低):**
1. `--workspace` flag（CLI）/ `--workspace`（MCP）—— 一次性覆盖
2. 配置文件 `workspace:` 字段 —— 支持 `${ENV_VAR}` / `${ENV_VAR:-/default}` 占位符
3. **registry 绑定** —— `~/.config/gitmux/workspaces.yaml`,按配置文件**绝对路径**为 key 映射到本地 workspace
4. 都无 → `WorkspaceError`

**registry(`registry.py`):**
- 机器本地状态(类比 `~/.gitconfig`),不入库;位置用 `Path.home()` 解析,不用字符串 `~`。
- key = 配置文件 `Path(...).expanduser().resolve()` 绝对路径。
- CLI `gitmux workspace set/show/unset` 与 MCP `workspace_set/show/unset` 维护它。

**设计动机:** 配置文件可省略 `workspace` 成为纯仓库清单文档(跨机器/容器共享),每个环境用
`workspace set` 绑定一次本地路径。这样 `gitmux -c xxx.yaml`（含 MCP `gitmux-mcp --config xxx`）
**无需环境变量、无需 `--workspace`** 即可自动解析 workspace——尤其适合容器内 agent(不依赖
环境变量传导)。`config_path` 在 load 时写入 `GitmuxConfig`,供 `resolve_workspace` 查 registry。

## Markets 层设计

为在**单一配置文件**中管理多个市场/项目(让一个 MCP server 就能服务全部),在 group 之上
增加可选的 `markets` 层:`markets → groups → repos`。

- **数据模型**:`MarketConfig(name, groups)`;`GroupConfig` 带 `market` 反向引用;
  `GitmuxConfig.markets` 为真实存储,`groups` 属性为跨市场的扁平视图(向后兼容读取)。
- **路径布局**:有 market → `{workspace}/{market}/{group}/{repo}`;无 market(旧配置)→
  `{workspace}/{group}/{repo}`。`get_repo_path` 依据 `group.market` 自动选择,**无需改任何
  op 签名**(市场信息随 group 携带)。
- **target 语法**:有 markets 时三段 `market/group/repo`;旧配置仍支持 `group/repo` / `repo`。
  另有 `--market` / `-m` 选择器(CLI)与 `market` 参数(MCP 工具)。
- **向后兼容**:顶层 `groups:`(无 `markets:`)加载为一个隐式 `NO_MARKET` 市场,行为与
  改造前完全一致(两段 target、三段路径)。`save_config` 按是否含真实市场决定写 `markets:`
  还是 `groups:`。
- **MCP**:新增 `list_markets` 工具;`status/fetch/clone/pull/push/list_repos/add_repo`
  均支持 `market` 参数。**一个 config + 一个 server 管所有市场**——不需要多 server、不需要
  给工具传 config 路径。

## MCP Server 设计

面向 AI agent 的接入。核心原则是**最小权限 / 能力即边界**：agent 不需要 shell
权限，只能调用显式定义的工具，因此**不暴露通用 `exec`**。

- **传输**：stdio，无 token。server 作为 agent 的子进程在同一机器运行，安全边界是
  OS/进程；无网络监听，无需鉴权。（远程/跨机才需要 HTTP + 鉴权，本项目不提供。）
- **无状态**：每次工具调用读 YAML → 跑 git → 返回结构化结果，不保留 per-session 状态。
- **实现**：`mcp_server.py` 用 `mcp.server.mcpserver.MCPServer`，工具直接调用
  `service.py` 的纯逻辑并返回 JSON。入口 `gitmux-mcp`（`--config` 可指定配置）。
- **工具集**：list_repos / list_groups / status / fetch / clone / pull / push /
  add_repo / remove_repo / init_config。git 类工具用 `target` | `group` | `all_repos`
  三选一选择仓库。
- **扩展**：将来若需 HTTP 传输，只需在 `main()` 加分支切换 `transport` 并叠加 Bearer
  鉴权，工具逻辑不变。
