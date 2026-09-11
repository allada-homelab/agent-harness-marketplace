import os
from conftest import git, run


def test_start_creates_branch_worktree_and_symlink(repo):
    root, _ = repo
    r = run("start", "widget", cwd=root)
    assert r.returncode == 0, r.stderr
    wt = root / ".claude" / "worktrees" / "feat-widget"
    assert wt.is_dir()
    assert r.stdout.strip().splitlines()[-1] == f"pr-flow: start ok {wt}"
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt) == "feat/widget"
    link = root / ".agents" / "worktrees"
    assert link.is_symlink() and os.readlink(link) == "../.claude/worktrees"
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=root) == "main"


def test_start_keeps_explicit_prefix(repo):
    root, _ = repo
    r = run("start", "fix/typo", cwd=root)
    assert r.returncode == 0, r.stderr
    assert (root / ".claude" / "worktrees" / "fix-typo").is_dir()


def test_start_is_idempotent(repo):
    root, _ = repo
    assert run("start", "widget", cwd=root).returncode == 0
    r = run("start", "widget", cwd=root)
    assert r.returncode == 0, r.stderr
    assert "already" in r.stderr


def test_start_carries_uncommitted_edits_by_tagged_stash(repo):
    root, _ = repo
    (root / "README.md").write_text("edited\n")
    (root / "new.txt").write_text("new\n")
    r = run("start", "carry", cwd=root)
    assert r.returncode == 0, r.stderr
    wt = root / ".claude" / "worktrees" / "feat-carry"
    assert (wt / "README.md").read_text() == "edited\n"
    assert (wt / "new.txt").read_text() == "new\n"
    assert git("status", "--porcelain", cwd=root) == ""
    assert git("stash", "list", cwd=root) == ""


def test_start_refuses_real_agents_worktrees_dir(repo):
    root, _ = repo
    (root / ".agents" / "worktrees").mkdir(parents=True)
    r = run("start", "widget", cwd=root)
    assert r.returncode == 2
    assert ".agents/worktrees" in r.stderr


def test_start_honors_worktreeinclude(repo):
    root, _ = repo
    (root / ".env").write_text("X=1\n")
    (root / ".worktreeinclude").write_text(".env\n")
    git("add", ".worktreeinclude", cwd=root)
    git("commit", "-q", "-m", "wti", cwd=root)
    git("push", "-q", cwd=root)
    r = run("start", "inc", cwd=root)
    assert r.returncode == 0, r.stderr
    assert (root / ".claude" / "worktrees" / "feat-inc" / ".env").read_text() == "X=1\n"
    # .env is untracked (never committed), so it also makes root dirty and triggers the
    # carry-over stash — it must be COPIED to the worktree, not moved out of root by it.
    assert (root / ".env").read_text() == "X=1\n"
    assert git("stash", "list", cwd=root) == ""
    # The exclude pathspec left nothing to actually stash here (.env was the only dirty
    # content); that must not be mistaken for a failed stash apply.
    assert "conflicted" not in r.stderr


def test_start_worktreeinclude_rejects_parent_traversal(repo):
    root, _ = repo
    (root.parent / "outside.txt").write_text("secret\n")
    (root / ".worktreeinclude").write_text("../outside.txt\n")
    git("add", ".worktreeinclude", cwd=root)
    git("commit", "-q", "-m", "wti-traversal", cwd=root)
    git("push", "-q", cwd=root)
    r = run("start", "esc", cwd=root)
    assert r.returncode == 2
    assert "outside.txt" in r.stderr
    assert not (root / ".claude" / "worktrees" / "feat-esc").exists()


def test_start_worktreeinclude_rejects_absolute_pattern(repo):
    root, _ = repo
    (root / ".worktreeinclude").write_text("/etc/hostname\n")
    git("add", ".worktreeinclude", cwd=root)
    git("commit", "-q", "-m", "wti-abs", cwd=root)
    git("push", "-q", cwd=root)
    r = run("start", "abs", cwd=root)
    assert r.returncode == 2
    assert "/etc/hostname" in r.stderr
    assert not (root / ".claude" / "worktrees" / "feat-abs").exists()


def test_start_preserves_exclude_file_missing_trailing_newline(repo):
    root, _ = repo
    (root / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (root / ".git" / "info" / "exclude").write_text("node_modules")
    assert run("start", "one", cwd=root).returncode == 0
    r = run("start", "two", cwd=root)
    assert r.returncode == 0, r.stderr
    lines = (root / ".git" / "info" / "exclude").read_text().splitlines()
    assert lines.count("node_modules") == 1
    assert lines.count("/.claude/worktrees/") == 1
    assert lines.count("/.agents/worktrees") == 1
