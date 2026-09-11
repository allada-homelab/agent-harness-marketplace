import json
from conftest import git, run


def pr(state="OPEN", checks=(), mergeable="MERGEABLE", review="", head="h1", number=7):
    return {"state": state, "mergeable": mergeable, "mergeStateStatus": "CLEAN", "reviewDecision": review,
            "statusCheckRollup": list(checks), "url": "https://github.com/o/r/pull/7", "headRefOid": head,
            "number": number}


def check(conclusion, status="COMPLETED", url="https://github.com/o/r/actions/runs/123/job/456"):
    return {"__typename": "CheckRun", "name": "ci", "status": status, "conclusion": conclusion, "detailsUrl": url}


def opened(repo):
    root, _ = repo
    assert run("start", "w", cwd=root).returncode == 0
    wt = root / ".claude" / "worktrees" / "feat-w"
    return root, wt


def last(r):
    return r.stdout.strip().splitlines()[-1]


def test_green(repo):
    _, wt = opened(repo)
    r = run("watch", cwd=wt, replay={"pr_view": [pr(checks=[check("SUCCESS")])]})
    assert r.returncode == 0, r.stderr
    assert last(r) == "pr-flow: watch green https://github.com/o/r/pull/7"


def test_pending_then_green_polls_until_terminal(repo):
    _, wt = opened(repo)
    r = run("watch", "--interval", "0", cwd=wt,
            replay={"pr_view": [pr(checks=[check("", "IN_PROGRESS")]), pr(mergeable="UNKNOWN"), pr(checks=[check("SUCCESS")])]})
    assert r.returncode == 0, r.stderr
    assert len((wt / ".gh-log").read_text().splitlines()) >= 3


def test_checks_failed_prints_log_and_counts_attempt(repo):
    _, wt = opened(repo)
    r = run("watch", cwd=wt, replay={"pr_view": [pr(checks=[check("FAILURE")])]})
    assert r.returncode == 10
    assert "LOG-FOR-123" in r.stdout
    assert r.stdout.count("LOG-FOR-123") <= 200
    assert last(r) == "pr-flow: watch checks-failed https://github.com/o/r/pull/7"
    state = json.loads((wt.parent.parent.parent / ".git" / "pr-flow" / "feat%2Fw.json").read_text())
    assert state["attempts"] == 1 and state["pr"] == 7


def test_conflict(repo):
    _, wt = opened(repo)
    r = run("watch", cwd=wt, replay={"pr_view": [pr(checks=[check("SUCCESS")], mergeable="CONFLICTING")]})
    assert r.returncode == 11


def test_review_threads_and_changes_requested(repo):
    _, wt = opened(repo)
    r = run("watch", cwd=wt, replay={"pr_view": [pr(checks=[check("SUCCESS")])], "threads_unresolved": 2})
    assert r.returncode == 12
    assert "2 unresolved" in r.stdout
    r = run("watch", cwd=wt, replay={"pr_view": [pr(checks=[check("SUCCESS")], review="CHANGES_REQUESTED")]})
    assert r.returncode == 12


def test_closed_and_merged(repo):
    _, wt = opened(repo)
    assert run("watch", cwd=wt, replay={"pr_view": [pr(state="CLOSED")]}).returncode == 13
    r = run("watch", cwd=wt, replay={"pr_view": [pr(state="MERGED")]})
    assert r.returncode == 0 and last(r).startswith("pr-flow: watch merged")


def test_timeout(repo):
    _, wt = opened(repo)
    r = run("watch", "--timeout", "0", cwd=wt, replay={"pr_view": [pr(checks=[check("", "IN_PROGRESS")])]})
    assert r.returncode == 14


def test_attempts_exhausted_on_sixth_fix_verdict_and_reset_on_green(repo):
    _, wt = opened(repo)
    for i in range(5):
        assert run("watch", cwd=wt, replay={"pr_view": [pr(checks=[check("FAILURE")])]}).returncode == 10, i
    r = run("watch", cwd=wt, replay={"pr_view": [pr(checks=[check("FAILURE")])]})
    assert r.returncode == 15
    assert "checks-failed" in r.stdout
    assert run("watch", cwd=wt, replay={"pr_view": [pr(checks=[check("SUCCESS")])]}).returncode == 0
    assert run("watch", cwd=wt, replay={"pr_view": [pr(checks=[check("FAILURE")])]}).returncode == 10


def test_status_context_shape_counts_too(repo):
    _, wt = opened(repo)
    ctx_ok = {"__typename": "StatusContext", "context": "ext", "state": "SUCCESS", "targetUrl": "https://x"}
    ctx_bad = {"__typename": "StatusContext", "context": "ext", "state": "FAILURE", "targetUrl": "https://x"}
    assert run("watch", cwd=wt, replay={"pr_view": [pr(checks=[ctx_ok])]}).returncode == 0
    assert run("watch", cwd=wt, replay={"pr_view": [pr(checks=[ctx_bad])]}).returncode == 10
