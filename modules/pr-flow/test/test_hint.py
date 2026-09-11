import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import git

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "hint-on-protected-branch.py"


def fire(tmp_path, file_path, session="s1", tool="Edit"):
    ev = {"session_id": session, "cwd": str(tmp_path), "hook_event_name": "PostToolUse", "tool_name": tool,
          "tool_input": {"file_path": str(file_path)}, "tool_response": ""}
    env = dict(os.environ, TMPDIR=str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir(exist_ok=True)
    p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(ev), env=env, text=True, capture_output=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"] if p.stdout.strip() else None


def test_hints_once_for_tracked_file_on_main(repo, tmp_path):
    root, _ = repo
    hint = fire(tmp_path, root / "README.md")
    assert hint and "pr-flow start" in hint and "main" in hint
    assert fire(tmp_path, root / "README.md") is None            # same session: silent
    assert fire(tmp_path, root / "README.md", session="s2")      # new session: hints again


def test_silent_on_feature_branch(repo, tmp_path):
    root, _ = repo
    git("switch", "-q", "-c", "feat/x", cwd=root)
    assert fire(tmp_path, root / "README.md") is None


def test_silent_for_untracked_file_and_outside_repo(repo, tmp_path):
    root, _ = repo
    (root / ".env").write_text("X=1\n")
    assert fire(tmp_path, root / ".env") is None
    assert fire(tmp_path, tmp_path / "loose.txt") is None


def test_silent_in_linked_worktree_even_on_main_name(repo, tmp_path):
    root, _ = repo
    wt = tmp_path / "wt"
    git("worktree", "add", "-q", "--detach", str(wt), cwd=root)
    git("switch", "-q", "-c", "main-copy", cwd=wt)
    assert fire(tmp_path, wt / "README.md") is None


def test_silent_in_linked_worktree_on_protected_name(repo, tmp_path):
    # A protected NAME ("release") that is not checked out anywhere else — this
    # proves the worktree rule fires independently of whether the branch name
    # happens to be protected, unlike main-copy above which is silent only
    # because "main-copy" isn't in PROTECTED.
    root, _ = repo
    wt = tmp_path / "wt2"
    git("worktree", "add", "-q", "--detach", str(wt), cwd=root)
    git("switch", "-q", "-c", "release", cwd=wt)
    assert fire(tmp_path, wt / "README.md") is None


def test_silent_for_other_tools_and_bad_stdin(repo, tmp_path):
    root, _ = repo
    assert fire(tmp_path, root / "README.md", tool="Bash") is None
    p = subprocess.run([sys.executable, str(HOOK)], input="not json", text=True, capture_output=True)
    assert p.returncode == 0 and p.stdout.strip() == ""


def fire_from(proc_cwd, ev_cwd, file_path, session="s1", tool="Edit"):
    """Like fire(), but the hook process itself runs from proc_cwd while the event's
    own `cwd` field is ev_cwd — proves a relative file_path resolves against ev["cwd"],
    not the hook process's own working directory (pi may send relative paths; Claude
    sends absolute ones, so this only bites non-Claude runners)."""
    ev = {"session_id": session, "cwd": str(ev_cwd), "hook_event_name": "PostToolUse", "tool_name": tool,
          "tool_input": {"file_path": str(file_path)}, "tool_response": ""}
    env = dict(os.environ, TMPDIR=str(proc_cwd / "tmp"))
    (proc_cwd / "tmp").mkdir(exist_ok=True)
    p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(ev), cwd=proc_cwd, env=env,
                        text=True, capture_output=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"] if p.stdout.strip() else None


def test_relative_file_path_resolves_against_event_cwd(repo, tmp_path):
    root, _ = repo
    # Hook process cwd is tmp_path (not the repo); tool_input.file_path is relative,
    # so it must resolve against ev["cwd"] (= root) to find the tracked file on main.
    hint = fire_from(tmp_path, root, "README.md")
    assert hint and "pr-flow start" in hint

    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert fire_from(tmp_path, outside, "README.md") is None
