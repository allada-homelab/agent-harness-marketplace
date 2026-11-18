import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

CLI = Path(__file__).resolve().parents[1] / "skills" / "repo-sweep" / "repo_sweep.py"
BUG = {"file": "src/calc.py", "quote": "return a - b  # sum", "lens": "bugs", "severity": "high",
       "title": "add subtracts", "detail": "add(1, 2) returns -1"}


@pytest.fixture
def repo(tmp_path):
    return tmp_path / "repo"


@pytest.fixture
def sweep(tmp_path, repo):
    """A git repo with two source files, and a runner for the CLI inside it."""
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "calc.py").write_text("def add(a, b):\n    return a - b  # sum\n\n\ndef div(a, b):\n    return a / b\n")
    (repo / "src" / "util.py").write_text("def read(path):\n    return open(path).read()\n")
    (repo / "logo.bin").write_bytes(b"\x00\x01\x02")
    (repo / "uv.lock").write_text("version = 1\n")
    env = dict(os.environ, REPO_SWEEP_HOME=str(tmp_path / "state"), GIT_CONFIG_GLOBAL=os.devnull)
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
        subprocess.run(["git", *args], cwd=repo, env=env, check=True)

    def run(*args, stdin=None, gh=None):
        e = dict(env, REPO_SWEEP_GH=str(gh)) if gh else env
        data = json.dumps(stdin) if stdin is not None else None
        p = subprocess.run([sys.executable, str(CLI), *map(str, args)], cwd=repo, env=e, input=data, text=True,
                           capture_output=True)
        return p.returncode, p.stdout

    return run


def confirm(sweep):
    """Plan, record BUG through the finder unit, confirm it through the validator unit. Returns its id."""
    sweep("plan")
    sweep("next")
    assert sweep("record", 1, stdin={"findings": [BUG]})[0] == 0
    sweep("next")
    rc, out = sweep("record", 2, stdin={"verdicts": [
        {"id": 1, "verdict": "confirmed", "proof": "ran it", "command": "python -c ...", "output": "-1"}]})
    assert rc == 0, out
    return 1


def fake_gh(tmp_path, state):
    gh = tmp_path / f"gh-{state}"
    gh.write_text(f"#!/bin/sh\necho {state}\n")
    gh.chmod(0o755)
    return gh


def test_plan_splits_by_budget_and_skips_binary_and_lockfiles(sweep):
    rc, out = sweep("plan", "--chars", 80)
    assert rc == 0
    assert "part src/calc.py: 1 files" in out and "part src/util.py: 1 files" in out
    assert "2 parts, 2 files, 2 skipped" in out
    assert "part src: 2 files" in sweep("plan")[1]  # under the default budget the directory stays together


def test_record_rejects_a_quote_that_is_not_in_the_file(sweep):
    sweep("plan")
    sweep("next")
    invented = dict(BUG, quote="return a * b  # product", title="invented")
    rc, out = sweep("record", 1, stdin={"findings": [BUG, invented]})
    assert rc == 1
    assert "accepted: #1 add subtracts" in out and "rejected: finding 2: quote is not in src/calc.py" in out
    assert "unit 1 still open" in out
    rc, out = sweep("record", 1, stdin={"findings": [BUG]})  # the retry repeats the accepted finding
    assert rc == 0 and "duplicate: finding 1 is already #1" in out and "unit 1 done" in out
    assert "1 candidate" in sweep("status")[1]


def test_finished_finder_queues_a_validator_and_confirmed_needs_proof(sweep):
    sweep("plan")
    sweep("next")
    sweep("record", 1, stdin={"findings": [BUG, dict(BUG, quote="def div(a, b):\n    return a / b", lens="edge-cases")]})
    out = sweep("next")[1]
    assert "unit 2 validate agent=repo-sweep:validator" in out
    brief = Path(out.split("brief=")[1].split()[0]).read_text()
    assert "#1 [candidate] high bugs src/calc.py:2" in brief and "src/calc.py:5" in brief
    rc, out = sweep("record", 2, stdin={"verdicts": [{"id": 1, "verdict": "confirmed", "proof": "looks wrong"}]})
    assert rc == 1 and "confirmed needs an evidence entry" in out and "no verdict for #2" in out
    good = {"id": 1, "verdict": "confirmed", "proof": "subtracts", "evidence": [{"file": "src/calc.py", "quote": "return a - b  # sum"}]}
    assert sweep("record", 2, stdin={"verdicts": [good]})[0] == 1  # #2 still has no verdict
    rc, out = sweep("record", 2, stdin={"verdicts": [good, {"id": 2, "verdict": "rejected", "proof": "callers check b first"}]})
    assert rc == 0 and "duplicate: #1 already has its verdict" in out and "unit 2 done" in out
    assert sweep("next")[1].strip() == "repo-sweep: next done"
    assert "evidence: src/calc.py:2" in sweep("report")[1]


def test_rerun_does_not_repeat_known_findings_and_rechecks_changed_code(sweep, repo):
    confirm(sweep)
    calc = repo / "src" / "calc.py"
    calc.write_text("# header\n" + calc.read_text())
    assert "1 confirmed" in sweep("plan")[1]  # the quote only moved down a line
    brief = Path(sweep("next")[1].split("brief=")[1].split()[0]).read_text()
    assert "#1 [confirmed] high bugs src/calc.py:3" in brief
    calc.write_text(calc.read_text().replace("return a - b  # sum", "return a + b"))
    assert "1 recheck" in sweep("plan")[1]
    assert "unit 4 find" in sweep("next")[1]  # unit numbers keep counting across runs
    sweep("record", 4, stdin={"findings": []})
    assert "unit 5 validate" in sweep("next")[1]
    assert sweep("record", 5, stdin={"verdicts": [{"id": 1, "verdict": "confirmed", "proof": "still there"}]})[0] == 1
    assert sweep("record", 5, stdin={"verdicts": [{"id": 1, "verdict": "fixed", "proof": "add now adds"}]})[0] == 0
    assert "1 fixed" in sweep("status")[1]


def test_record_refuses_a_report_of_the_wrong_shape(sweep):
    sweep("plan")
    sweep("next")
    assert sweep("record", 1, stdin={"verdicts": []})[0] == 1
    assert "1 find claimed" in sweep("status")[1]


def test_fix_unit_becomes_pr_open_then_follows_the_pull_request(sweep, tmp_path):
    confirm(sweep)
    out = sweep("next", "--fix")[1]
    assert "unit 3 fix agent=repo-sweep:fixer" in out and "branch=sweep-src-u3" in out
    assert sweep("next", "--fix")[1].startswith("repo-sweep: next claimed 0, 0 pending, 1 running")
    assert sweep("record", 3, stdin={"results": [{"id": 1, "outcome": "fixed"}]})[0] == 1  # a note is required
    assert sweep("record", 3, stdin={"results": [{"id": 1, "outcome": "fixed", "note": "use +; test added"}]})[0] == 0
    assert "1 findings now pr-open" in sweep("pr", 3, "https://example.test/pull/7")[1]
    assert "1 confirmed" in sweep("sync", gh=fake_gh(tmp_path, "CLOSED"))[1]
    assert "unit 4 fix" in sweep("next", "--fix")[1]
    sweep("record", 4, stdin={"results": [{"id": 1, "outcome": "fixed", "note": "again"}]})
    sweep("pr", 4, "https://example.test/pull/8")
    assert "1 fixed" in sweep("sync", gh=fake_gh(tmp_path, "MERGED"))[1]


def test_skipped_fix_needs_a_human_and_is_not_queued_again(sweep):
    confirm(sweep)
    sweep("next", "--fix")
    sweep("record", 3, stdin={"results": [{"id": 1, "outcome": "skipped", "note": "needs an API decision"}]})
    assert "1 needs-human" in sweep("status")[1]
    assert sweep("next", "--fix")[1].strip() == "repo-sweep: next done"


def test_release_requeues_once_then_fails_and_ignores_finished_units(sweep):
    sweep("plan", "--chars", 80)
    sweep("next")
    assert "unit 1 queued again" in sweep("release", 1)[1]
    assert "unit 1 find" in sweep("next")[1]
    assert "unit 1 failed after 2 attempts" in sweep("release", 1)[1]
    sweep("next")
    sweep("record", 2, stdin={"findings": []})
    assert "unit 2 is done; nothing to do" in sweep("release", 2)[1]
    assert sweep("next")[1].strip() == "repo-sweep: next done, 1 failed"


def test_sync_closes_findings_whose_file_was_removed(sweep, repo):
    confirm(sweep)
    (repo / "src" / "calc.py").unlink()
    assert sweep("sync")[1].strip() == "repo-sweep: sync 1 fixed"
