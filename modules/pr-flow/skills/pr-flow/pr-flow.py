#!/usr/bin/env python3
"""pr-flow — branch + worktree → PR → watch until green → (merge when told) → teardown.

Stdlib only. `gh` and `git` are shelled out; PR_FLOW_GH / PR_FLOW_GIT override the
binaries so tests replay recorded answers. Final stdout line is a stable interface:
    pr-flow: <verb> <verdict> [<url-or-path>]
"""
import argparse
import glob
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

GH = os.environ.get("PR_FLOW_GH", "gh")
GIT = os.environ.get("PR_FLOW_GIT", "git")
PROTECTED = {"main", "master", "dev", "develop", "production", "release"}
EXIT = {"ok": 0, "green": 0, "merged": 0, "checks-failed": 10, "conflict": 11, "review": 12,
        "closed": 13, "timeout": 14, "attempts-exhausted": 15}
MAX_ATTEMPTS = 5
FIX_CLASS = {"checks-failed", "conflict", "review"}


class Fail(Exception):
    """A refusal or a failed prerequisite. Message goes to stderr, exit 2."""


def sh(*args, cwd=None, check=True, timeout=600):
    p = subprocess.run([str(a) for a in args], cwd=cwd, text=True, capture_output=True, timeout=timeout)
    if check and p.returncode:
        raise Fail(f"{' '.join(map(str, args))} failed (rc {p.returncode}): {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout.strip()


def git(*args, cwd=None, **kw):
    return sh(GIT, *args, cwd=cwd, **kw)


def gh(*args, cwd=None, **kw):
    return sh(GH, *args, cwd=cwd, **kw)


def warn(msg):
    print(f"pr-flow: {msg}", file=sys.stderr)


def done(verb, verdict, extra=""):
    print(f"pr-flow: {verb} {verdict}{(' ' + str(extra)) if extra else ''}")
    return EXIT.get(verdict, 0)


@dataclass
class Ctx:
    main_root: Path
    common_dir: Path
    is_main: bool
    branch: str


def repo_ctx(cwd):
    out = git("rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir", cwd=cwd).splitlines()
    git_dir, common = Path(out[0]), Path(out[1])
    branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    return Ctx(main_root=common.parent, common_dir=common, is_main=(git_dir == common), branch=branch)


def default_base(root):
    try:
        ref = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=root)
        return ref.split("/", 1)[1]
    except Fail:
        return "main"


def worktrees(root):
    """[(path, branch)] from `git worktree list --porcelain`, main checkout included."""
    out, path, branch = [], None, None
    for line in git("worktree", "list", "--porcelain", cwd=root).splitlines() + [""]:
        if line.startswith("worktree "):
            path = Path(line[9:])
        elif line.startswith("branch "):
            branch = line[7:].replace("refs/heads/", "", 1)
        elif line == "":
            if path is not None:
                out.append((path, branch))
            path, branch = None, None
    return out


def worktree_for_branch(root, branch):
    for path, b in worktrees(root):
        if b == branch and path.resolve() != root.resolve():
            return path
    return None


def ensure_excludes(root):
    """Keep .claude/worktrees/ and .agents/worktrees out of `git status` for this repo.

    Without this, pr-flow's own scaffolding (and every worktree nested under it) reads
    as untracked content, so a clean repo looks dirty and start's carry-over stash would
    scoop up the scaffolding itself instead of leaving root exactly as it was.
    """
    exclude = root / ".git" / "info" / "exclude"
    wanted = ["/.claude/worktrees/", "/.agents/worktrees"]
    lines = exclude.read_text().splitlines() if exclude.exists() else []
    missing = [w for w in wanted if w not in lines]
    if missing:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a") as f:
            for w in missing:
                f.write(w + "\n")


def ensure_worktree_dirs(root):
    ensure_excludes(root)
    real = root / ".claude" / "worktrees"
    real.mkdir(parents=True, exist_ok=True)
    agents = root / ".agents"
    agents.mkdir(exist_ok=True)
    link = agents / "worktrees"
    target = "../.claude/worktrees"
    if link.is_symlink():
        if os.readlink(link) != target:
            link.unlink()
            link.symlink_to(target)
    elif link.exists():
        raise Fail(f"{link} is a real directory, not a symlink to {target}; move it aside and rerun")
    else:
        link.symlink_to(target)
    return real


def copy_worktreeinclude(root, wt):
    inc = root / ".worktreeinclude"
    if not inc.is_file():
        return
    for pattern in inc.read_text().splitlines():
        pattern = pattern.strip()
        if not pattern or pattern.startswith("#"):
            continue
        for src in glob.glob(str(root / pattern), recursive=True):
            rel = Path(src).relative_to(root)
            if rel.parts and rel.parts[0] in (".git", ".claude"):
                continue
            dst = wt / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if Path(src).is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)


def stash_sha(root, tag):
    for line in git("stash", "list", "--format=%H %gs", cwd=root).splitlines():
        sha, subject = line.split(" ", 1)
        if subject.endswith(tag):
            return sha
    return None


def drop_stash(root, tag):
    for line in git("stash", "list", "--format=%gd %gs", cwd=root).splitlines():
        ref, subject = line.split(" ", 1)
        if subject.endswith(tag):
            git("stash", "drop", "-q", ref, cwd=root)
            return


def cmd_start(a):
    ctx = repo_ctx(Path.cwd())
    root = ctx.main_root
    base = a.base or default_base(root)
    branch = a.slug if "/" in a.slug else f"feat/{a.slug}"
    if branch in PROTECTED:
        raise Fail(f"{branch} is a protected branch name")
    real = ensure_worktree_dirs(root)
    existing = worktree_for_branch(root, branch)
    if existing:
        warn(f"worktree for {branch} already exists")
        print(existing)
        return done("start", "ok", existing)
    git("fetch", "-q", "origin", base, cwd=root)
    wt = real / branch.replace("/", "-")
    tag = None
    if ctx.is_main and git("status", "--porcelain", cwd=root):
        tag = f"pr-flow start {branch} {secrets.token_hex(4)}"
        git("stash", "push", "-q", "-u", "-m", tag, cwd=root)
    git("worktree", "add", "-q", "-b", branch, wt, f"origin/{base}", cwd=root)
    copy_worktreeinclude(root, wt)
    if tag:
        sha = stash_sha(root, tag)
        try:
            git("stash", "apply", "-q", sha, cwd=wt)
            drop_stash(root, tag)
        except Fail as e:
            warn(f"stash apply conflicted; entry '{tag}' kept for you to resolve: {e}")
    print(wt)
    return done("start", "ok", wt)


def main(argv=None):
    p = argparse.ArgumentParser(prog="pr-flow", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="verb", required=True)
    s = sub.add_parser("start", help="create branch + worktree off the base branch")
    s.add_argument("slug")
    s.add_argument("--base")
    s.set_defaults(fn=cmd_start)
    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except Fail as e:
        warn(str(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
