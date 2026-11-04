#!/usr/bin/env python3
"""Guards a repo's MAIN checkout while it sits on a protected branch.

PreToolUse (Bash): blocks (exit 2) a git command that changes that checkout's branch, files
or history — other sessions and every new worktree read it. Fails open whenever the target
can't be resolved (a `cd $VAR`), since the hint and the skill still cover that case.
In any checkout it also blocks `git worktree add` (worktrees come from `pr-flow start`, which
applies the setup rules) and a stash command that can take another session's entry from the
one stash stack every worktree shares.
PostToolUse (Edit/Write): hints, once per session per repo, after a tracked file is edited
there. Never blocks.

A repo whose convention is to change the protected branch directly opts out with
`git config pr-flow.allowMainCheckout true`. Runs on Claude natively and on pi/dsh through
their hook runners (same stdin shape).
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

PROTECTED = {"main", "master", "dev", "develop", "production", "release"}
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}
SEP = r"(?:^|[;&|(\n])\s*"
GIT = re.compile(SEP + r"(?:[A-Za-z_]\w*=\S*\s+)*git((?:\s+-[Cc]\s+\S+)*)\s+([\w-]+)(?=[\s;&|)]|$)([^;&|\n]*)")
MUTATING = {"commit", "checkout", "switch", "reset", "clean", "rebase", "merge", "cherry-pick", "revert",
            "restore", "am", "pull", "stash"}
# Reading the stack, and applying a named entry; pop/drop/clear/branch or a bare apply act on
# whichever entry is on top, possibly another session's.
STASH_OK = re.compile(r"\s+((list|show|create)(?=\s|$)|apply(\s+-\S+)*\s+[^-\s])")
CD = re.compile(SEP + r"cd\s+([^\s;&|)]+)")


def git(d, *args):
    return subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, timeout=3)


def protected_main(d):
    """(root, branch) when `d` is in a repo's main checkout on a protected branch, else None."""
    top = git(d, "rev-parse", "--show-toplevel")
    if top.returncode:
        return None
    branch = git(d, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch not in PROTECTED:
        return None
    dirs = git(d, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir").stdout.split()
    if len(dirs) != 2 or dirs[0] != dirs[1]:
        return None  # linked worktree: a branch here is the agent's own
    if git(d, "config", "--bool", "pr-flow.allowMainCheckout").stdout.strip() == "true":
        return None
    return top.stdout.strip(), branch


def resolve(base, path):
    """`path` taken from `base`, or None when the shell would have to expand it."""
    if base is None or "$" in path or "`" in path:
        return None
    p = os.path.join(base, os.path.expanduser(path.strip("\"'")))
    return os.path.realpath(p) if os.path.isdir(p) else None


def block(ev):
    if ev.get("tool_name") != "Bash":
        return None
    cmd = (ev.get("tool_input") or {}).get("command") or ""
    for m in GIT.finditer(cmd):
        flags, verb, rest = m.groups()
        if verb == "worktree" and re.match(r"\s+add(?=\s|$)", rest):
            return ("pr-flow: make worktrees with `pr-flow start <slug>` (`--base <branch>` for one off "
                    "another branch), not `git worktree add`: start applies the setup rules (no copied "
                    "virtualenvs, .worktreeinclude, a recorded base) that a bare add skips.")
        if verb == "stash" and not STASH_OK.match(rest):
            return ("pr-flow: every worktree and session shares one stash stack, so this can take or drop "
                    "another session's entry. Set work aside with a WIP commit, or `git stash create` and "
                    "`git stash apply <sha>`.")
        if verb not in MUTATING or (verb == "pull" and "--ff-only" in rest):
            continue
        if verb == "stash" and re.match(r"\s+(list|show|create)(?=\s|$)", rest):
            continue
        target = ev.get("cwd") or os.getcwd()
        cds = [c for c in CD.finditer(cmd) if c.start() < m.start()]
        if cds:
            target = resolve(target, cds[-1].group(1))
        for c in re.finditer(r"-C\s+(\S+)", flags):
            target = resolve(target, c.group(1))
        hit = protected_main(target) if target else None
        if hit:
            root, branch = hit
            return (f"pr-flow: `git {verb}` would change {root}, the main checkout on `{branch}`, which "
                    f"other sessions and every new worktree read. Run `pr-flow start <slug>` (`--carry` "
                    f"moves uncommitted edits along) and do it in the worktree; on main, only `git fetch` "
                    f"and `git pull --ff-only`. If the user wants {branch} changed in place in this repo, "
                    f"they opt it out with `git -C {root} config pr-flow.allowMainCheckout true`.")
    return None


def hint(ev):
    if ev.get("tool_name") not in EDIT_TOOLS:
        return None
    ti = ev.get("tool_input") or {}
    fp = ti.get("file_path") or ti.get("notebook_path")
    if not fp:
        return None
    base = ev.get("cwd") or os.getcwd()
    fp = os.path.abspath(fp if os.path.isabs(fp) else os.path.join(base, fp))
    d = os.path.dirname(fp)
    hit = protected_main(d)
    if not hit:
        return None
    root, branch = hit
    if git(d, "ls-files", "--error-unmatch", "--", fp).returncode:
        return None  # untracked: .env, overlays, scratch
    sid = str(ev.get("session_id") or os.getppid())
    # Own 0700 dir per user: in shared /tmp another local user could pre-create the marker
    # and silence the hint. os.open below still refuses a pre-existing file or symlink.
    mdir = os.path.join(tempfile.gettempdir(), f"pr-flow-hint-{os.getuid()}")
    os.makedirs(mdir, mode=0o700, exist_ok=True)
    if os.stat(mdir).st_uid != os.getuid() or (os.stat(mdir).st_mode & 0o077):
        return None
    marker = os.path.join(mdir, f"{sid}.{hashlib.sha1(root.encode()).hexdigest()[:12]}")
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        return None
    return (f"pr-flow: you just changed a tracked file while {root} is on `{branch}` in its main "
            f"checkout. Unless the user said to work on {branch} directly, run "
            f"`pr-flow start <slug> --carry` now — it moves these uncommitted edits into a "
            f"worktree — and continue there.")


def main():
    try:
        ev = json.load(sys.stdin)
        if ev.get("hook_event_name") == "PreToolUse":
            reason = block(ev)
            if reason:
                print(reason, file=sys.stderr)
                return 2
            return 0
        text = hint(ev)
    except Exception:  # fail open: a guard that wedges the tool loop is worse than what it guards
        return 0
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
