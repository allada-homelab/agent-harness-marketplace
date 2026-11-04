import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import git

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "protected-branch.py"


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
    assert hint and "pr-flow start" in hint and "--carry" in hint and "main" in hint
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


def test_marker_lives_in_a_private_per_user_dir(repo, tmp_path):
    root, _ = repo
    assert fire(tmp_path, root / "README.md")
    d = tmp_path / "tmp" / f"pr-flow-hint-{os.getuid()}"
    assert d.is_dir() and (d.stat().st_mode & 0o777) == 0o700
    assert not list((tmp_path / "tmp").glob("pr-flow-hint.*"))


def guard(cwd, command):
    ev = {"session_id": "s1", "cwd": str(cwd), "hook_event_name": "PreToolUse", "tool_name": "Bash",
          "tool_input": {"command": command}}
    p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(ev), text=True, capture_output=True)
    assert p.stdout == ""
    return p.returncode, p.stderr


@pytest.mark.parametrize("command", [
    "git commit -qm x",
    "git add README.md && git commit -m x",
    "git reset --hard HEAD~1",
    "git switch -c feat/x",
    "git pull",
    "FOO=1 git -c core.pager=cat restore README.md",
])
def test_guard_blocks_mutating_git_on_main(repo, command):
    root, _ = repo
    rc, err = guard(root, command)
    assert rc == 2 and "pr-flow start" in err and "allowMainCheckout" in err


@pytest.mark.parametrize("command", [
    "git status", "git fetch origin", "git pull --ff-only", "git stash list", "git stash show",
    "git merge-base HEAD origin/main", "git log --oneline -1", "echo 'git commit -m x'",
])
def test_guard_allows_read_only_git_on_main(repo, command):
    root, _ = repo
    assert guard(root, command)[0] == 0


def test_guard_follows_cd_and_dash_c_to_the_real_target(repo, tmp_path):
    root, _ = repo
    wt = tmp_path / "wt"
    git("worktree", "add", "-q", "-b", "feat/y", str(wt), cwd=root)
    assert guard(root, f"cd {wt} && git commit -m x")[0] == 0        # a worktree, from main's cwd
    assert guard(root, f"git -C {wt} commit -m x")[0] == 0
    assert guard(tmp_path, f"cd {root} && git commit -m x")[0] == 2  # main, from elsewhere
    assert guard(tmp_path, f"git -C {root} reset --hard")[0] == 2


def test_guard_fails_open_when_target_needs_expansion(repo):
    root, _ = repo
    assert guard(root, "cd $W && git commit -m x")[0] == 0
    assert guard(root, "git -C \"$W\" commit -m x")[0] == 0


def test_guard_silent_off_protected_branch_and_when_opted_out(repo):
    root, _ = repo
    git("switch", "-q", "-c", "feat/z", cwd=root)
    assert guard(root, "git commit -m x")[0] == 0
    git("switch", "-q", "main", cwd=root)
    git("config", "pr-flow.allowMainCheckout", "true", cwd=root)
    assert guard(root, "git commit -m x")[0] == 0


def test_guard_ignores_other_tools_and_bad_stdin(repo):
    root, _ = repo
    ev = {"cwd": str(root), "hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {"command": "git commit"}}
    assert subprocess.run([sys.executable, str(HOOK)], input=json.dumps(ev), text=True).returncode == 0
    p = subprocess.run([sys.executable, str(HOOK)], input="not json", text=True, capture_output=True)
    assert p.returncode == 0


@pytest.mark.parametrize(("command", "blocked"), [
    ("git stash", True), ("git stash push -m wip", True), ("git stash pop", True),
    ("git stash drop", True), ("git stash clear", True), ("git stash apply", True),
    ("git stash branch b", True),
    ("git stash list", False), ("git stash show -p", False), ("git stash create", False),
    ("git stash apply 1a2b3c", False), ("git stash apply --index 1a2b3c", False),
])
def test_guard_stash_rule_holds_in_any_worktree(repo, tmp_path, command, blocked):
    root, _ = repo
    wt = tmp_path / "wt"
    git("worktree", "add", "-q", "-b", "feat/s", str(wt), cwd=root)
    rc, err = guard(wt, command)
    assert (rc == 2) == blocked, err
    if blocked:
        assert "stash stack" in err


@pytest.mark.parametrize("cwd_is_main", [True, False])
def test_guard_blocks_bare_worktree_add_anywhere(repo, tmp_path, cwd_is_main):
    root, _ = repo
    wt = tmp_path / "wt"
    git("worktree", "add", "-q", "-b", "feat/w", str(wt), cwd=root)
    rc, err = guard(root if cwd_is_main else wt, f"git worktree add -b feat/q {tmp_path / 'q'}")
    assert rc == 2 and "pr-flow start" in err
    assert guard(root, "git worktree list")[0] == 0
