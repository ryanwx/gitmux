"""Tests for git operations."""

from pathlib import Path

from gitmux import git_ops


def test_clone_and_pull(tmp_path: Path):
    """Test clone creates a repo and pull works on it."""
    # Create a bare repo to clone from
    bare = tmp_path / "bare.git"
    bare.mkdir()
    import subprocess

    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True)

    # Clone it
    dest = tmp_path / "cloned"
    result = git_ops.clone(str(bare), dest)
    assert result.success
    assert (dest / ".git").exists()

    # Pull on cloned repo
    result = git_ops.pull(dest)
    # May warn about no upstream, but shouldn't error fatally
    assert result.command == "git pull"


def test_status_clean(tmp_path: Path):
    """Test status on a clean repo."""
    import subprocess

    subprocess.run(["git", "init", str(tmp_path / "repo")], capture_output=True)
    repo = tmp_path / "repo"
    result = git_ops.status(repo)
    assert result.success
    assert result.output == ""  # clean repo


def test_current_branch(tmp_path: Path):
    """Test getting current branch."""
    import subprocess

    repo = tmp_path / "repo"
    subprocess.run(["git", "init", str(repo)], capture_output=True)
    # Need at least one commit for branch to exist
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=T", "commit", "-m", "init"], cwd=repo, capture_output=True
    )

    result = git_ops.current_branch(repo)
    assert result.success
    assert result.output in ("main", "master")


def test_fetch(tmp_path: Path):
    """Test fetch on a cloned repo."""
    import subprocess

    bare = tmp_path / "bare.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True)
    dest = tmp_path / "cloned"
    git_ops.clone(str(bare), dest)

    result = git_ops.fetch(dest)
    assert result.success


def test_list_remote_branches(tmp_path: Path):
    """Test listing remote branches with pattern matching."""
    import subprocess

    # Create a bare repo with multiple branches
    bare = tmp_path / "bare.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True)

    # Create a working repo, add commits on different branches
    work = tmp_path / "work"
    subprocess.run(["git", "clone", str(bare), str(work)], capture_output=True)
    (work / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=work, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=T", "commit", "-m", "init"],
        cwd=work,
        capture_output=True,
    )
    subprocess.run(["git", "push", "origin", "HEAD:app-plan-260501"], cwd=work, capture_output=True)
    subprocess.run(["git", "push", "origin", "HEAD:app-plan-260515"], cwd=work, capture_output=True)
    subprocess.run(["git", "push", "origin", "HEAD:app-dev-main"], cwd=work, capture_output=True)

    # Clone fresh and test
    dest = tmp_path / "test"
    git_ops.clone(str(bare), dest)
    git_ops.fetch(dest)

    matches = git_ops.list_remote_branches(dest, "app-plan-*")
    assert len(matches) == 2
    assert all("plan" in m for m in matches)

    matches_dev = git_ops.list_remote_branches(dest, "app-dev-*")
    assert matches_dev == ["app-dev-main"]
