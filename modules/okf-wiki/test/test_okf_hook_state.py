import json
import os

from okf_testlib import GOOD_META, concept, git, hook, okf, run


def stop(repo, ev):
    r = hook(repo, "hook-stop", {"cwd": str(repo), **ev})
    assert (r.returncode, r.stderr) == (0, ""), r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def committed(repo, *ids):
    for cid in ids:
        concept(repo, cid)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "wiki")


def test_a_pins_only_edit_does_not_silence_a_later_real_edit(repo):
    (repo / "package.json").write_text('{"version": "0.1.12"}\n')
    committed(repo, "a")
    assert hook(repo, "hook-session-start", {"session_id": "s1", "cwd": str(repo)}).returncode == 0
    (repo / "package.json").write_text('{"version": "0.1.13"}\n')
    assert stop(repo, {"session_id": "s1"}) is None           # a pin bump is not work
    (repo / "src/app.py").write_text("def resolve_peers():\n    return 9\n")
    assert stop(repo, {"session_id": "s1"})["reason"] == okf.NUDGE  # real work, same HEAD


def test_no_session_id_fails_quiet_and_persists_no_session_state(repo, tmp_path):
    committed(repo, "a")
    assert hook(repo, "hook-session-start", {"cwd": str(repo)}).returncode == 0
    (repo / "src/app.py").write_text("changed\n")
    for _ in range(2):  # nothing could dedupe an id-less nudge, so it would block every Stop
        assert stop(repo, {}) is None
    concept(repo, "b")                                         # nor the wiki-commit reminder
    assert stop(repo, {}) is None
    assert not list((tmp_path / "state").rglob("session-*.json"))
    assert stop(repo, {"session_id": "s1"})["decision"] == "block"  # with an id it still nudges


def test_a_freshness_logic_bump_invalidates_the_cache(repo, monkeypatch):
    concept(repo, "x")
    assert run(repo, "stamp", "x", "--by", "okf-wiki/haiku", "--verified").returncode == 0
    calls = []
    real = okf.freshness
    monkeypatch.setattr(okf, "freshness", lambda *a, **k: calls.append(1) or real(*a, **k))
    ev = {"session_id": "s1", "cwd": str(repo)}
    okf.hook_session_start(ev)
    okf.hook_session_start(ev)
    assert len(calls) == 1
    monkeypatch.setattr(okf, "FRESH_LOGIC_VERSION", okf.FRESH_LOGIC_VERSION + 1)
    okf.hook_session_start(ev)
    assert len(calls) == 2


def test_stop_sweep_tolerates_a_session_file_vanishing_mid_sweep(repo):
    committed(repo, "a")
    d = okf.state_dir(repo)
    d.mkdir(parents=True, exist_ok=True)
    # A dangling entry: glob lists it, stat() raises FileNotFoundError, as when a concurrent
    # Stop hook unlinks the file between this hook's glob and its stat.
    os.symlink(d / "gone.json", d / "session-racing.json")
    (repo / "src/app.py").write_text("changed\n")
    assert stop(repo, {"session_id": "s1"})["decision"] == "block"


def test_session_start_caches_freshness_by_head_tree_and_stamps(repo, monkeypatch):
    concept(repo, "x")
    assert run(repo, "stamp", "x", "--by", "okf-wiki/haiku", "--verified").returncode == 0
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "wiki")
    calls = []
    real = okf.freshness

    def counted(*a, **k):
        calls.append(k.get("timeout"))
        return real(*a, **k)

    monkeypatch.setattr(okf, "freshness", counted)
    ev = {"session_id": "s1", "cwd": str(repo)}
    okf.hook_session_start(ev)
    okf.hook_session_start(ev)
    assert calls == [1.5]                                     # the repeat start was a cache hit
    assert json.loads((okf.state_dir(repo) / "fresh.json").read_text())["res"]["x"][0] == "FRESH"
    (repo / "src/app.py").write_text("def resolve_peers():\n    return 7\n")
    okf.hook_session_start(ev)                                # an uncommitted edit moves the tree
    git(repo, "commit", "-qam", "edit")
    okf.hook_session_start(ev)                                # HEAD moved
    meta = GOOD_META + "verified:\n  - {by: okf-wiki/haiku, at: 2026-01-01T00:00:00Z, commit: deadbeef1234}\n"
    concept(repo, "x", meta=meta)
    git(repo, "commit", "-qam", "restamp")
    okf.hook_session_start(ev)                                # a stamp changed (and HEAD)
    assert len(calls) == 4
    okf.hook_session_start(ev)
    assert len(calls) == 4
