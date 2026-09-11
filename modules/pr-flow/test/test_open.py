import json
from conftest import git, run


def gh_calls(root):
    return [json.loads(l) for l in (root / ".gh-log").read_text().splitlines()]


def test_open_pushes_and_creates_pr(repo):
    root, origin = repo
    assert run("start", "widget", cwd=root).returncode == 0
    wt = root / ".claude" / "worktrees" / "feat-widget"
    (wt / "a.txt").write_text("a\n")
    git("add", "a.txt", cwd=wt)
    git("commit", "-q", "-m", "a", cwd=wt)
    r = run("open", cwd=wt, replay={"pr_url": ""})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "pr-flow: open ok https://github.com/o/r/pull/7"
    assert git("rev-parse", "feat/widget", cwd=origin)  # pushed
    assert any(c[:2] == ["pr", "create"] for c in gh_calls(wt))


def test_open_reuses_existing_pr(repo):
    root, _ = repo
    assert run("start", "widget", cwd=root).returncode == 0
    wt = root / ".claude" / "worktrees" / "feat-widget"
    (wt / "a.txt").write_text("a\n")
    git("add", "a.txt", cwd=wt)
    git("commit", "-q", "-m", "a", cwd=wt)
    r = run("open", cwd=wt, replay={"pr_url": "https://github.com/o/r/pull/3"})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().endswith("pull/3")
    assert not any(c[:2] == ["pr", "create"] for c in gh_calls(wt))


def test_open_refuses_protected_branch(repo):
    root, _ = repo
    r = run("open", cwd=root, replay={})
    assert r.returncode == 2
    assert "protected" in r.stderr
