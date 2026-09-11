import json
from conftest import git, run


def pr(state="OPEN", checks=(), mergeable="MERGEABLE", review="", head="h1", number=7,
       isDraft=None, mergeStateStatus="CLEAN"):
    d = {"state": state, "mergeable": mergeable, "mergeStateStatus": mergeStateStatus, "reviewDecision": review,
         "statusCheckRollup": list(checks), "url": "https://github.com/o/r/pull/7", "headRefOid": head,
         "number": number}
    if isDraft is not None:
        d["isDraft"] = isDraft
    return d


def check(conclusion, status="COMPLETED", url="https://github.com/o/r/actions/runs/123/job/456"):
    return {"__typename": "CheckRun", "name": "ci", "status": status, "conclusion": conclusion, "detailsUrl": url}


def pending(head):
    return pr(checks=[check("", "IN_PROGRESS")], head=head)


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


def test_conflict_message_uses_recorded_base(repo):
    root, _ = repo
    git("branch", "dev", cwd=root)
    git("push", "-q", "origin", "dev", cwd=root)
    assert run("start", "cb", "--base", "dev", cwd=root).returncode == 0
    wt = root / ".claude" / "worktrees" / "feat-cb"
    r = run("watch", cwd=wt, replay={"pr_view": [pr(checks=[check("SUCCESS")], mergeable="CONFLICTING")]})
    assert r.returncode == 11
    assert "merge origin/dev" in r.stdout


def test_review_threads_and_changes_requested(repo):
    _, wt = opened(repo)
    r = run("watch", cwd=wt, replay={"pr_view": [pr(checks=[check("SUCCESS")])], "threads_unresolved": 2})
    assert r.returncode == 12
    assert "2 unresolved" in r.stdout
    r = run("watch", cwd=wt, replay={"pr_view": [pr(checks=[check("SUCCESS")], review="CHANGES_REQUESTED")]})
    assert r.returncode == 12


def test_draft_pr_is_review(repo):
    _, wt = opened(repo)
    r = run("watch", cwd=wt, replay={"pr_view": [pr(checks=[check("SUCCESS")], isDraft=True)]})
    assert r.returncode == 12
    assert "draft" in r.stdout


def test_blocked_merge_state_is_review(repo):
    _, wt = opened(repo)
    r = run("watch", cwd=wt, replay={"pr_view": [pr(checks=[check("SUCCESS")], mergeStateStatus="BLOCKED")]})
    assert r.returncode == 12
    assert "branch protection" in r.stdout


def test_no_checks_polls_within_grace_then_green_when_check_arrives(repo):
    _, wt = opened(repo)
    r = run("watch", "--interval", "1", "--no-checks-grace", "60", cwd=wt,
            replay={"pr_view": [pr(checks=[]), pr(checks=[]), pr(checks=[check("SUCCESS")])]})
    assert r.returncode == 0, r.stderr
    assert last(r) == "pr-flow: watch green https://github.com/o/r/pull/7"
    calls = [json.loads(l) for l in (wt / ".gh-log").read_text().splitlines()]
    assert sum(1 for c in calls if c[:2] == ["pr", "view"]) >= 3


def test_no_checks_with_zero_grace_is_immediately_green(repo):
    _, wt = opened(repo)
    r = run("watch", "--no-checks-grace", "0", cwd=wt, replay={"pr_view": [pr(checks=[])]})
    assert r.returncode == 0, r.stderr
    assert "no checks reported" in r.stdout
    assert last(r) == "pr-flow: watch green https://github.com/o/r/pull/7"


def test_no_checks_then_failure_surfaces_during_grace(repo):
    _, wt = opened(repo)
    r = run("watch", cwd=wt, replay={"pr_view": [pr(checks=[]), pr(checks=[check("FAILURE")])]})
    assert r.returncode == 10


def test_merge_refuses_on_grace_expired_green(repo):
    _, wt = opened(repo)
    r = run("watch", "--merge", "--no-checks-grace", "0", cwd=wt, replay={"pr_view": [pr(checks=[])]})
    assert r.returncode == 0, r.stderr
    assert "refusing --merge" in r.stdout
    calls = [json.loads(l) for l in (wt / ".gh-log").read_text().splitlines()]
    assert not any(c[:2] == ["pr", "merge"] for c in calls)


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


def test_transient_poll_failures_retry_then_succeed(repo):
    _, wt = opened(repo)
    r = run("watch", cwd=wt,
            replay={"pr_view": [{"__fail__": True}, {"__fail__": True}, pr(checks=[check("SUCCESS")])]})
    assert r.returncode == 0, r.stderr
    assert "poll failed (2 consecutive)" in r.stderr


def test_ten_consecutive_poll_failures_gives_up(repo):
    _, wt = opened(repo)
    r = run("watch", cwd=wt, replay={"pr_view": [{"__fail__": True}]})
    assert r.returncode == 2
    assert "10 polls in a row" in r.stderr


def test_backoff_grows_caps_and_resets_on_head_change(repo):
    _, wt = opened(repo)
    replay = {"pr_view": [pending("h1"), pending("h1"), pending("h1"), pending("h2"),
                           pr(checks=[check("SUCCESS")], head="h2")]}
    r = run("watch", "--interval", "4", "--interval-max", "9", cwd=wt, replay=replay)
    assert r.returncode == 0, r.stderr
    waits = [line.split("next poll in ")[1].rstrip("s") for line in r.stderr.splitlines() if "next poll in" in line]
    assert waits == ["4", "6", "9", "4"]
