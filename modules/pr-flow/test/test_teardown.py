import json
from conftest import git, run
from test_watch import pr, check, last


def merged_branch(repo, name="w"):
    """Start, commit, push, merge into origin/main the way GitHub would (merge commit on origin)."""
    root, origin = repo
    assert run("start", name, cwd=root).returncode == 0
    wt = root / ".claude" / "worktrees" / f"feat-{name}"
    (wt / f"{name}.txt").write_text("x\n")
    git("add", f"{name}.txt", cwd=wt)
    git("commit", "-q", "-m", name, cwd=wt)
    git("push", "-q", "-u", "origin", f"feat/{name}", cwd=wt)
    git("fetch", "-q", "origin", cwd=root)
    git("merge", "-q", "--no-ff", "-m", "merge", f"origin/feat/{name}", cwd=root)
    git("push", "-q", "origin", "main", cwd=root)
    return root, wt


def test_teardown_removes_worktree_branch_and_state(repo):
    root, wt = merged_branch(repo)
    (root / ".git" / "pr-flow").mkdir(exist_ok=True)
    (root / ".git" / "pr-flow" / "feat%2Fw.json").write_text("{}")
    r = run("teardown", "feat/w", cwd=root)
    assert r.returncode == 0, r.stderr
    assert not wt.exists()
    assert "feat/w" not in git("branch", "--list", cwd=root)
    assert not (root / ".git" / "pr-flow" / "feat%2Fw.json").exists()
    assert last(r) == "pr-flow: teardown ok feat/w"


def test_teardown_from_inside_the_worktree_reexecs(repo):
    _, wt = merged_branch(repo)
    r = run("teardown", cwd=wt)
    assert r.returncode == 0, r.stderr
    assert not wt.exists()


def test_teardown_refuses_dirty_worktree(repo):
    root, wt = merged_branch(repo)
    (wt / "dirty.txt").write_text("d\n")
    r = run("teardown", "feat/w", cwd=root)
    assert r.returncode == 2
    assert "dirty.txt" in r.stderr and wt.exists()


def test_teardown_refuses_unmerged_branch(repo):
    root, _ = repo
    assert run("start", "u", cwd=root).returncode == 0
    wt = root / ".claude" / "worktrees" / "feat-u"
    (wt / "u.txt").write_text("u\n")
    git("add", "u.txt", cwd=wt)
    git("commit", "-q", "-m", "u", cwd=wt)
    r = run("teardown", "feat/u", cwd=root)
    assert r.returncode == 2
    assert "not merged" in r.stderr and wt.exists()


def test_watch_merge_merges_then_tears_down(repo):
    root, _ = repo
    assert run("start", "m", cwd=root).returncode == 0
    wt = root / ".claude" / "worktrees" / "feat-m"
    (wt / "m.txt").write_text("m\n")
    git("add", "m.txt", cwd=wt)
    git("commit", "-q", "-m", "m", cwd=wt)
    git("push", "-q", "-u", "origin", "feat/m", cwd=wt)
    # Simulate GitHub's merge landing on origin/main before the post-merge poll.
    git("fetch", "-q", "origin", cwd=root)
    git("merge", "-q", "--no-ff", "-m", "merge", "origin/feat/m", cwd=root)
    git("push", "-q", "origin", "main", cwd=root)
    r = run("watch", "--merge", cwd=wt, replay={"pr_view": [pr(checks=[check("SUCCESS")])]})
    assert r.returncode == 0, r.stderr
    assert last(r).startswith("pr-flow: watch merged")
    assert not wt.exists()


def test_watch_without_merge_never_calls_merge(repo):
    root, _ = repo
    assert run("start", "n", cwd=root).returncode == 0
    wt = root / ".claude" / "worktrees" / "feat-n"
    r = run("watch", cwd=wt, replay={"pr_view": [pr(checks=[check("SUCCESS")])]})
    assert r.returncode == 0
    calls = [json.loads(l) for l in (wt / ".gh-log").read_text().splitlines()]
    assert not any(c[:2] == ["pr", "merge"] for c in calls)


def test_gc_sweeps_only_merged(repo):
    root, wt_w = merged_branch(repo, "w")
    assert run("start", "keep", cwd=root).returncode == 0
    wt_keep = root / ".claude" / "worktrees" / "feat-keep"
    r = run("gc", cwd=root, replay={"merged_branches": ["feat/w"]})
    assert r.returncode == 0, r.stderr
    assert not wt_w.exists() and wt_keep.exists()
    assert "feat/keep" in r.stdout


def test_gc_dry_run_reports_without_removing(repo):
    root, wt_w = merged_branch(repo, "w")
    r = run("gc", "--dry-run", cwd=root, replay={"merged_branches": ["feat/w"]})
    assert r.returncode == 0, r.stderr
    assert "would remove" in r.stdout
    assert wt_w.exists()
