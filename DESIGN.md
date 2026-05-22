# gitmux - Design Document

## Overview

gitmux 是一个 Python CLI 工具，通过 YAML 配置文件管理多个 git 仓库，支持批量 git 操作、分组管理、前后置 hook、并行/串行执行模式。

## Architecture

```
src/gitmux/
├── cli.py          # Typer CLI 入口，子命令定义
├── config.py       # YAML 配置加载/验证/保存
├── models.py       # 数据模型（Repo, Group, Hook, Template）
├── executor.py     # 命令执行引擎（串行/并行）
├── git_ops.py      # Git 操作封装
├── hooks.py        # Hook 执行逻辑
└── output.py       # 输出格式化（Rich 表格、进度条）
```

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
- Testing: pytest
- Build: hatchling
