"""bin/pi-run against a fake `pi` on PATH that records how it was called."""

import fcntl
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

PI_RUN = Path(__file__).resolve().parent.parent / "bin" / "pi-run"

# Records argv, cwd, stdin, the hook exclusion and any inherited lock fd; writes a session file into
# --session-dir like pi does.
FAKE_PI = r"""#!/usr/bin/env python3
import json, os, sys, time
argv = sys.argv[1:]
stdin = sys.stdin.read()
with open(os.environ["FAKE_PI_LOG"], "a") as f:
    f.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "stdin": stdin,
                        "exclude": os.environ.get("PI_HOOK_EXCLUDE_MODULES"),
                        "lock_fds": [fd for fd in (8, 9) if os.path.exists(f"/proc/self/fd/{fd}")]}) + "\n")
d = argv[argv.index("--session-dir") + 1]
if not any(n.endswith(".jsonl") for n in os.listdir(d)):
    open(os.path.join(d, "s.jsonl"), "w").close()
time.sleep(float(os.environ.get("FAKE_PI_SLEEP", "0")))
print("the answer")
sys.exit(int(os.environ.get("FAKE_PI_EXIT", "0")))
"""


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "pi").write_text(FAKE_PI)
    (bindir / "pi").chmod(0o755)
    return {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "XDG_STATE_HOME": str(tmp_path / "state"),
            "FAKE_PI_LOG": str(tmp_path / "log.jsonl"), "PI_HOOK_EXCLUDE_MODULES": ""}


def run(env, *args, cwd, stdin=None, **extra):
    return subprocess.run([str(PI_RUN), *args], cwd=cwd, env={**env, **extra}, input=stdin,
                          capture_output=True, text=True, timeout=30)


def calls(env):
    return [json.loads(line) for line in Path(env["FAKE_PI_LOG"]).read_text().splitlines()]


def session_of(result):
    return result.stderr.split("pi-run: session ")[1].split()[0]


def test_new_run_passes_brief_on_stdin_and_saves_a_session(env, tmp_path):
    out = run(env, "summarize", "this", cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    assert out.stdout == "the answer\n"
    sid = session_of(out)
    [call] = calls(env)
    state = tmp_path / "state" / "pi-run" / sid
    assert call["argv"] == ["-p", "--session-dir", str(state), "--model", "llama-swap/large-default", "--"]
    assert call["stdin"] == "summarize this\n" and call["cwd"] == str(tmp_path)
    assert call["exclude"] == "switchboard"
    assert (state / "cwd").read_text() == f"{tmp_path}\n"


def test_brief_from_stdin_and_options_reach_pi(env, tmp_path):
    (tmp_path / "a.txt").write_text("x")
    out = run(env, "--model", "p/m:high", "--thinking", "low", "--read-only", "--file", "a.txt",
              cwd=tmp_path, stdin="from stdin", PI_HOOK_EXCLUDE_MODULES="okf-wiki")
    assert out.returncode == 0, out.stderr
    [call] = calls(env)
    assert call["stdin"] == "from stdin\n" and call["exclude"] == "okf-wiki,switchboard"
    assert call["argv"][3:] == ["--model", "p/m:high", "--thinking", "low", "--tools", "read,grep,find,ls",
                                "--no-mcp", "--", f"@{tmp_path / 'a.txt'}"]


def test_session_resumes_in_its_own_directory(env, tmp_path):
    first = run(env, "one", cwd=tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    again = run(env, "--session", session_of(first), "two", cwd=elsewhere)
    assert again.returncode == 0, again.stderr
    assert session_of(again) == session_of(first)
    a, b = calls(env)
    assert b["cwd"] == str(tmp_path) and "--continue" in b["argv"]
    assert b["argv"][b["argv"].index("--session-dir") + 1] == a["argv"][a["argv"].index("--session-dir") + 1]


def test_fork_starts_a_new_session_from_the_parent_history(env, tmp_path):
    parent = run(env, "one", cwd=tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    child = run(env, "--fork", session_of(parent), "two", cwd=elsewhere)
    assert child.returncode == 0, child.stderr
    assert session_of(child) != session_of(parent)
    fork_call = calls(env)[1]
    parent_file = tmp_path / "state" / "pi-run" / session_of(parent) / "s.jsonl"
    assert fork_call["argv"][fork_call["argv"].index("--fork") + 1] == str(parent_file)
    assert fork_call["cwd"] == str(tmp_path)


@pytest.mark.parametrize("flag", ["--session", "--fork"])
def test_busy_session_refuses_a_second_run(env, tmp_path, flag):
    sid = session_of(run(env, "one", cwd=tmp_path))
    with open(tmp_path / "state" / "pi-run" / sid / "cwd") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        out = run(env, flag, sid, "two", cwd=tmp_path)
    assert out.returncode == 2 and "is busy" in out.stderr


@pytest.mark.parametrize(("args", "stdin", "message"), [
    (["--session", "nope", "x"], None, "no session nope"),
    (["--session", "../x", "x"], None, "no session ../x"),
    (["--session", "a", "--fork", "b", "x"], None, "exclusive"),
    (["--timeout", "0", "x"], None, "whole seconds"),
    (["--bogus"], None, "unknown option"),
    (["--file", "missing.txt", "x"], None, "cannot read"),
    ([], "  \n", "the brief is empty"),
])
def test_usage_errors_exit_2(env, tmp_path, args, stdin, message):
    out = run(env, *args, cwd=tmp_path, stdin=stdin)
    assert out.returncode == 2 and message in out.stderr


def test_pi_failure_is_the_exit_status(env, tmp_path):
    assert run(env, "x", cwd=tmp_path, FAKE_PI_EXIT="1").returncode == 1


def test_timeout_exits_124(env, tmp_path):
    assert run(env, "--timeout", "1", "x", cwd=tmp_path, FAKE_PI_SLEEP="5").returncode == 124


def age(path, days):
    then = time.time() - days * 86400
    os.utime(path, (then, then))


def test_pi_does_not_inherit_the_session_locks(env, tmp_path):
    first = run(env, "one", cwd=tmp_path)
    run(env, "--fork", session_of(first), "two", cwd=tmp_path)
    assert [c["lock_fds"] for c in calls(env)] == [[], []]


def test_a_run_marks_its_session_used(env, tmp_path):
    sid = session_of(run(env, "one", cwd=tmp_path))
    state = tmp_path / "state" / "pi-run" / sid
    age(state, 10)
    run(env, "--session", sid, "two", cwd=tmp_path)
    assert time.time() - state.stat().st_mtime < 60


def test_sessions_unused_for_14_days_are_pruned(env, tmp_path):
    old = tmp_path / "state" / "pi-run" / session_of(run(env, "one", cwd=tmp_path))
    age(old, 15)
    run(env, "two", cwd=tmp_path)
    assert not old.exists()


def test_prune_skips_a_session_in_use(env, tmp_path):
    old = tmp_path / "state" / "pi-run" / session_of(run(env, "one", cwd=tmp_path))
    age(old, 15)
    with open(old / "cwd") as held:
        fcntl.flock(held, fcntl.LOCK_SH)
        run(env, "two", cwd=tmp_path)
    assert old.exists()


def test_fork_of_a_session_without_history_exits_2(env, tmp_path):
    sid = session_of(run(env, "one", cwd=tmp_path))
    (tmp_path / "state" / "pi-run" / sid / "s.jsonl").unlink()
    out = run(env, "--fork", sid, "two", cwd=tmp_path)
    assert out.returncode == 2 and "no history to fork" in out.stderr
