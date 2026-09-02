"""Git operation wrappers using subprocess."""

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GitResult:
    success: bool
    output: str
    command: str


def _run(args: list[str], cwd: Path | None = None) -> GitResult:
    cmd_str = " ".join(args)
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        return GitResult(success=result.returncode == 0, output=output, command=cmd_str)
    except subprocess.TimeoutExpired:
        return GitResult(success=False, output="Command timed out (300s)", command=cmd_str)
    except FileNotFoundError:
        return GitResult(success=False, output="git not found in PATH", command=cmd_str)


def clone(url: str, dest: Path) -> GitResult:
    dest.parent.mkdir(parents=True, exist_ok=True)
    return _run(["git", "clone", url, str(dest)])


def init(repo_path: Path) -> GitResult:
    """Initialize a new empty git repository at repo_path."""
    repo_path.mkdir(parents=True, exist_ok=True)
    return _run(["git", "init", str(repo_path)])


def pull(repo_path: Path) -> GitResult:
    return _run(["git", "pull"], cwd=repo_path)


def push(repo_path: Path) -> GitResult:
    return _run(["git", "push"], cwd=repo_path)


def status(repo_path: Path) -> GitResult:
    return _run(["git", "status", "--porcelain"], cwd=repo_path)


def current_branch(repo_path: Path) -> GitResult:
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)


def ahead_behind(repo_path: Path) -> tuple[int, int]:
    """Return (ahead, behind) counts relative to upstream."""
    result = _run(["git", "rev-list", "--left-right", "--count", "HEAD...@{upstream}"], cwd=repo_path)
    if not result.success:
        return 0, 0
    parts = result.output.split()
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return 0, 0


def last_commit(repo_path: Path) -> str:
    result = _run(["git", "log", "-1", "--format=%s"], cwd=repo_path)
    return result.output if result.success else ""


def fetch(repo_path: Path) -> GitResult:
    return _run(["git", "fetch", "--prune"], cwd=repo_path)


def checkout(repo_path: Path, branch: str) -> GitResult:
    """Checkout a branch. Try local first, then track remote."""
    result = _run(["git", "checkout", branch], cwd=repo_path)
    if not result.success and "did not match" in result.output:
        # Try to create local branch tracking remote
        result = _run(["git", "checkout", "-b", branch, f"origin/{branch}"], cwd=repo_path)
    return result


def list_remote_branches(repo_path: Path, pattern: str) -> list[str]:
    """List remote branches matching a glob pattern, sorted by committerdate (newest first)."""
    import fnmatch

    result = _run(
        ["git", "branch", "-r", "--sort=-committerdate", "--format=%(refname:short)"],
        cwd=repo_path,
    )
    if not result.success:
        return []

    branches = []
    for line in result.output.splitlines():
        line = line.strip()
        # Remove origin/ prefix for matching
        branch_name = line.removeprefix("origin/")
        if fnmatch.fnmatch(branch_name, pattern):
            branches.append(branch_name)
    return branches
