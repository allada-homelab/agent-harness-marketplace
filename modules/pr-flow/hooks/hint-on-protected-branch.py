#!/usr/bin/env python3
"""PostToolUse soft guard: hint, once per session per repo, when a tracked file is
edited on a protected branch in a repo's MAIN checkout. Never blocks; always exits 0.
Runs on Claude natively and on pi/dsh through their hook runners (same stdin shape)."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

PROTECTED = {"main", "master", "dev", "develop", "production", "release"}
TOOLS = {"Edit", "Write", "NotebookEdit"}


def git(d, *args):
    return subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, timeout=3)


def hint(ev):
    if ev.get("tool_name") not in TOOLS:
        return None
    ti = ev.get("tool_input") or {}
    fp = ti.get("file_path") or ti.get("notebook_path")
    if not fp:
        return None
    base = ev.get("cwd") or os.getcwd()
    fp = fp if os.path.isabs(fp) else os.path.join(base, fp)
    fp = os.path.abspath(fp)
    d = os.path.dirname(fp)
    top = git(d, "rev-parse", "--show-toplevel")
    if top.returncode:
        return None
    root = top.stdout.strip()
    branch = git(d, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch not in PROTECTED:
        return None
    dirs = git(d, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir").stdout.split()
    if len(dirs) != 2 or dirs[0] != dirs[1]:
        return None  # linked worktree: a branch here is the agent's own
    if git(d, "ls-files", "--error-unmatch", "--", fp).returncode:
        return None  # untracked: .env, overlays, scratch
    sid = str(ev.get("session_id") or os.getppid())
    marker = os.path.join(tempfile.gettempdir(),
                          f"pr-flow-hint.{sid}.{hashlib.sha1(root.encode()).hexdigest()[:12]}")
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.close(fd)
    except FileExistsError:
        return None
    return (f"pr-flow: you just changed a tracked file while {root} is on `{branch}` in its main "
            f"checkout. Unless the user said to work on {branch} directly, run "
            f"`pr-flow start <slug>` now — it moves these uncommitted edits into a worktree — "
            f"and continue there.")


def main():
    try:
        ev = json.load(sys.stdin)
        text = hint(ev)
    except Exception:  # fail open: a guard that wedges the tool loop is worse than what it hints at
        return 0
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
