import json
import statistics
import time

from okf_testlib import concept, git, hook, okf, run


def ctx(r):
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def test_session_start_injects_the_digest_and_rebuilds_the_index(repo):
    concept(repo, "pnpm-peer-trap")
    r = hook(repo, "hook-session-start", {"session_id": "s1", "cwd": str(repo)})
    assert r.returncode == 0, r.stderr
    text = ctx(r)
    assert text.startswith("okf-wiki:digest v1 · .wiki/ · 1 concepts")
    assert "pnpm-peer-trap" in text
    assert (repo / ".wiki/index.md").exists()


def test_session_start_is_silent_without_a_bundle_or_in_a_subagent(repo, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    git(plain, "init", "-q")
    assert hook(plain, "hook-session-start", {"cwd": str(plain)}).stdout == ""
    concept(repo, "a")
    assert hook(repo, "hook-session-start", {"cwd": str(repo), "agent_id": "sub"}).stdout == ""


def test_session_start_fails_open_and_loud(repo):
    (repo / ".wiki" / "index.md").mkdir()  # write_indexes will hit a directory
    concept(repo, "a")
    r = hook(repo, "hook-session-start", {"cwd": str(repo)})
    assert r.returncode == 0 and r.stdout == ""
    assert r.stderr.startswith("okf-wiki: hook_session_start failed:")


def test_reflect_becomes_due_after_twenty_sessions(repo):
    concept(repo, "a")
    for _ in range(19):
        assert "reflect due" not in ctx(hook(repo, "hook-session-start", {"cwd": str(repo)})).splitlines()[0]
    assert "reflect due" in ctx(hook(repo, "hook-session-start", {"cwd": str(repo)})).splitlines()[0]
    run(repo, "stats", "--mark")
    assert "reflect due" not in ctx(hook(repo, "hook-session-start", {"cwd": str(repo)})).splitlines()[0]


def stop(repo, sid="s1", **extra):
    r = hook(repo, "hook-stop", {"session_id": sid, "cwd": str(repo), **extra})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def test_stop_nudges_once_when_the_tree_gets_dirty(repo):
    concept(repo, "a")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "wiki")
    assert stop(repo) is None                       # clean tree: nothing to capture
    (repo / "src/app.py").write_text("changed\n")
    out = stop(repo)
    assert out["decision"] == "block" and out["reason"] == okf.NUDGE
    assert stop(repo) is None                       # already nudged for this dirt


def test_stop_nudges_again_after_a_commit(repo):
    concept(repo, "a")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "wiki")
    stop(repo)
    (repo / "src/app.py").write_text("changed\n")
    git(repo, "commit", "-qam", "fix")
    assert stop(repo)["decision"] == "block"
    assert stop(repo) is None


def test_stop_ignores_wiki_only_changes_loops_and_subagents(repo):
    concept(repo, "a")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "wiki")
    stop(repo)
    concept(repo, "b")                              # the capture itself
    assert stop(repo) is None
    (repo / "src/app.py").write_text("changed\n")
    assert stop(repo, stop_hook_active=True) is None
    assert stop(repo, agent_id="sub") is None


def test_stop_state_is_per_session(repo):
    concept(repo, "a")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "wiki")
    (repo / "src/app.py").write_text("changed\n")
    assert stop(repo, sid="one")["decision"] == "block"
    assert stop(repo, sid="two")["decision"] == "block"


def test_stop_keeps_state_out_of_the_repo(repo, tmp_path):
    concept(repo, "a")
    (repo / "src/app.py").write_text("changed\n")
    stop(repo)
    assert list((tmp_path / "state" / "okf-wiki").rglob("session-s1.json"))
    assert not list(repo.rglob("session-*.json"))


def median_seconds(fn, n=5):
    samples = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t)
    return statistics.median(samples)


def test_hooks_are_fast(repo, tmp_path):
    # Spec budgets: <50 ms without a bundle, <500 ms at 250 concepts. Thresholds here carry
    # CI headroom (interpreter start dominates); a regression past them is a real defect.
    plain = tmp_path / "plain"
    plain.mkdir()
    git(plain, "init", "-q")
    assert median_seconds(lambda: hook(plain, "hook-session-start", {"cwd": str(plain)})) < 0.25
    for i in range(250):
        concept(repo, f"c{i:03d}", meta=f"type: gotcha\ntitle: T{i}\ndescription: claim {i}\n"
                "verified:\n  - {by: okf-wiki/haiku, at: 2026-01-01T00:00:00Z, commit: "
                + okf.head_commit(repo) + "}\n")
    assert median_seconds(lambda: hook(repo, "hook-session-start", {"cwd": str(repo)}), n=3) < 1.5


def test_hooks_work_in_a_repo_with_no_commits(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    r = tmp_path / "fresh"
    r.mkdir()
    git(r, "init", "-q")
    (r / ".wiki").mkdir()
    (r / "src").mkdir()
    (r / "src" / "app.py").write_text("def resolve_peers():\n    return 1\n")
    concept(r, "a")
    out = hook(r, "hook-session-start", {"cwd": str(r)})
    assert out.returncode == 0 and ctx(out).startswith("okf-wiki:digest v1")
    assert hook(r, "hook-stop", {"session_id": "s", "cwd": str(r)}).returncode == 0
    assert "git rev-parse HEAD failed" in run(r, "stamp", "a", "--by", "okf-wiki/haiku", "--verified").stdout


def test_hooks_find_the_bundle_from_a_subdirectory(repo):
    concept(repo, "a")
    r = hook(repo, "hook-session-start", {"cwd": str(repo / "src")})
    assert ctx(r).startswith("okf-wiki:digest v1 · .wiki/ · 1 concepts")


def test_stop_sees_untracked_files_with_spaces(repo):
    concept(repo, "a")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "wiki")
    stop(repo)
    (repo / "my notes.txt").write_text("x")
    assert stop(repo)["decision"] == "block"
