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


class _Retry(Exception):
    """Internal: a transient gh failure inside classify()'s unresolved() callback. cmd_watch
    catches this and treats it as 'keep polling' rather than a terminal verdict."""


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
    text = exclude.read_text() if exclude.exists() else ""
    lines = text.splitlines()
    missing = [w for w in wanted if w not in lines]
    if missing:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a") as f:
            if text and not text.endswith("\n"):
                f.write("\n")
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


def worktreeinclude_matches(root):
    """Resolve .worktreeinclude patterns to repo-relative paths.

    Refuses (Fail) any pattern that is absolute, `~`-rooted, or whose glob match resolves
    outside the repo (e.g. `../secret`) — such a pattern would read or write outside both
    the main checkout and the worktree it's meant to seed.
    """
    inc = root / ".worktreeinclude"
    if not inc.is_file():
        return []
    root_r = root.resolve()
    matches = []
    for pattern in inc.read_text().splitlines():
        pattern = pattern.strip()
        if not pattern or pattern.startswith("#"):
            continue
        if os.path.isabs(pattern) or pattern.startswith("~"):
            raise Fail(f".worktreeinclude: {pattern!r} must be a repo-relative pattern")
        for src in glob.glob(str(root / pattern), recursive=True):
            resolved = Path(src).resolve()
            try:
                rel = resolved.relative_to(root_r)
            except ValueError:
                raise Fail(f".worktreeinclude: {pattern!r} resolves outside the repo ({resolved})")
            if rel.parts and rel.parts[0] in (".git", ".claude"):
                continue
            if rel not in matches:
                matches.append(rel)
    return matches


def copy_worktreeinclude(root, wt, rel_paths):
    for rel in rel_paths:
        src, dst = root / rel, wt / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
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
    include = worktreeinclude_matches(root)
    tag = None
    if ctx.is_main and git("status", "--porcelain", cwd=root):
        stash_tag = f"pr-flow start {branch} {secrets.token_hex(4)}"
        # Exclude .worktreeinclude targets from the stash — they're meant to be copied to
        # the new worktree, not moved out of root (stash would remove the only copy of an
        # untracked one, e.g. .env, until `stash apply` lands it in the worktree instead).
        excludes = [f":(exclude){p.as_posix()}" for p in include]
        git("stash", "push", "-q", "-u", "-m", stash_tag, "--", ".", *excludes, cwd=root)
        # The exclude pathspec can leave nothing to stash (e.g. the only dirty content was
        # a .worktreeinclude match) — `git stash push` then no-ops ("No local changes to
        # save") without creating an entry. Look it up now, immediately after the push, so
        # that ambiguity is resolved right here rather than surfacing as a bogus "stash
        # apply conflicted" warning later.
        if stash_sha(root, stash_tag) is not None:
            tag = stash_tag
    git("worktree", "add", "-q", "-b", branch, wt, f"origin/{base}", cwd=root)
    copy_worktreeinclude(root, wt, include)
    if tag:
        sha = stash_sha(root, tag)
        if sha is None:
            raise Fail(f"stash '{tag}' was created but can no longer be found; check `git stash list` in {root}")
        try:
            git("stash", "apply", "-q", sha, cwd=wt)
            drop_stash(root, tag)
        except Fail as e:
            warn(f"stash apply conflicted; entry '{tag}' kept for you to resolve: {e}")
    print(wt)
    return done("start", "ok", wt)


def pr_url(cwd):
    """Look up the current branch's PR.

    Returns (url, state) — state is one of gh's PR states ("OPEN", "CLOSED", "MERGED").
    Returns (None, None) if gh fails (no PR exists for this branch, not pushed, etc).
    """
    try:
        data = json.loads(gh("pr", "view", "--json", "url,state", cwd=cwd))
        return data.get("url"), data.get("state")
    except Fail:
        return None, None


FIELDS = "state,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup,url,headRefOid,number"
BAD = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", "STALE"}
OK = {"SUCCESS", "SKIPPED", "NEUTRAL"}
SLEEP_SCALE = float(os.environ.get("PR_FLOW_SLEEP", "1"))
THREADS_Q = ("query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){pullRequest(number:$n)"
             "{reviewThreads(first:100){nodes{isResolved}}}}}")


def poll(cwd):
    return json.loads(gh("pr", "view", "--json", FIELDS, cwd=cwd))


def check_outcome(c):
    return (c.get("conclusion") or c.get("state") or "").upper()


def unresolved_threads(cwd, number):
    owner, repo = gh("repo", "view", "--json", "owner,name", "--jq", '.owner.login+" "+.name', cwd=cwd).split()
    out = json.loads(gh("api", "graphql", "-f", f"query={THREADS_Q}", "-F", f"o={owner}", "-F", f"r={repo}",
                        "-F", f"n={number}", cwd=cwd))
    nodes = out["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    return sum(1 for t in nodes if not t.get("isResolved"))


def classify(pr, unresolved):
    """Terminal verdict for a PR snapshot, or None to keep polling."""
    if pr.get("state") == "MERGED":
        return "merged"
    if pr.get("state") == "CLOSED":
        return "closed"
    checks = pr.get("statusCheckRollup") or []
    if any(check_outcome(c) in BAD for c in checks):
        return "checks-failed"
    if pr.get("mergeable") == "CONFLICTING":
        return "conflict"
    if any(check_outcome(c) not in OK for c in checks) or pr.get("mergeable") == "UNKNOWN":
        return None
    if pr.get("reviewDecision") == "CHANGES_REQUESTED":
        return "review"
    if unresolved() > 0:
        return "review"
    return "green"


def state_path(ctx, branch):
    d = ctx.common_dir / "pr-flow"
    d.mkdir(exist_ok=True)
    return d / (branch.replace("/", "%2F") + ".json")


def load_state(ctx, branch, number):
    p = state_path(ctx, branch)
    try:
        st = json.loads(p.read_text())
    except (OSError, ValueError):
        st = {}
    if st.get("pr") != number:
        st = {"pr": number, "attempts": 0}
    return st


def save_state(ctx, branch, st):
    path = state_path(ctx, branch)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(st))
    os.replace(tmp, path)


def print_failed_logs(pr, cwd):
    seen = set()
    for c in pr.get("statusCheckRollup") or []:
        if check_outcome(c) not in BAD:
            continue
        url = c.get("detailsUrl") or c.get("targetUrl") or ""
        print(f"--- failed: {c.get('name') or c.get('context')} {url}")
        parts = url.split("/actions/runs/")
        if len(parts) == 2:
            run_id = parts[1].split("/")[0]
            if run_id in seen:
                continue
            seen.add(run_id)
            try:
                log = gh("run", "view", run_id, "--log-failed", cwd=cwd)
                lines = log.splitlines()[-200:]
                print("\n".join(lines) if lines else "(no log output)")
            except (Fail, subprocess.TimeoutExpired) as e:
                warn(f"could not fetch log for run {run_id}: {e}")


def do_merge(ctx, cwd, pr):
    gh("pr", "merge", str(pr["number"]), "--merge", cwd=cwd)
    after = poll(cwd)
    if after.get("state") != "MERGED":
        raise Fail(f"merge requested but PR state is {after.get('state')}; not tearing down")
    print(f"merged {pr.get('url', '')}")
    return "merged"


def teardown(ctx, branch, dry_run=False):
    if branch in PROTECTED:
        raise Fail(f"{branch} is protected")
    root = ctx.main_root
    wt = worktree_for_branch(root, branch)
    if wt is not None and wt.is_dir():
        dirty = git("status", "--porcelain", cwd=wt)
        if dirty:
            raise Fail(f"worktree {wt} is dirty; commit or discard first:\n{dirty}")
    base = default_base(root)
    git("fetch", "-q", "origin", base, cwd=root)
    merged = subprocess.run([GIT, "merge-base", "--is-ancestor", branch, f"origin/{base}"], cwd=root).returncode == 0
    if not merged:
        raise Fail(f"branch {branch} is not merged into origin/{base}; refusing to delete it")
    if dry_run:
        print(f"would remove {wt} and delete {branch}")
        return
    if wt is not None:
        git("worktree", "remove", "--force", wt, cwd=root)
    git("branch", "-D", branch, cwd=root)
    if subprocess.run([GIT, "push", "-q", "origin", "--delete", branch], cwd=root, capture_output=True).returncode:
        warn(f"remote branch {branch} already gone or not deletable; continuing")
    git("worktree", "prune", cwd=root)
    try:
        state_path(ctx, branch).unlink()
    except OSError:
        pass


def cmd_watch(a):
    cwd = Path.cwd()
    ctx = repo_ctx(cwd)
    deadline = time.time() + a.timeout
    interval, last_head, pr, verdict = a.interval, None, {}, None
    threads = {"n": 0}
    consecutive_fails = 0
    while True:
        try:
            pr = poll(cwd)
        except (Fail, subprocess.TimeoutExpired) as e:
            consecutive_fails += 1
            warn(f"poll failed ({consecutive_fails} consecutive): {e}")
            if consecutive_fails >= 10:
                raise Fail("gh failed 10 polls in a row; giving up")
            verdict = None
        else:
            consecutive_fails = 0
            if pr.get("headRefOid") != last_head:
                interval, last_head = a.interval, pr.get("headRefOid")

            def unresolved():
                try:
                    threads["n"] = unresolved_threads(cwd, pr["number"])
                except (Fail, subprocess.TimeoutExpired) as e:
                    warn(f"could not check review threads: {e}")
                    raise _Retry from e
                return threads["n"]

            try:
                verdict = classify(pr, unresolved)
            except _Retry:
                verdict = None

        if verdict:
            break
        if time.time() >= deadline:
            verdict = "timeout"
            break
        warn(f"next poll in {interval:.0f}s")
        time.sleep(min(interval, max(0.0, deadline - time.time())) * SLEEP_SCALE)
        interval = min(interval * 1.5, a.interval_max)

    st = load_state(ctx, ctx.branch, pr.get("number"))
    if verdict in FIX_CLASS:
        st["attempts"] += 1
        save_state(ctx, ctx.branch, st)
        if verdict == "checks-failed":
            print_failed_logs(pr, cwd)
        elif verdict == "review":
            print(f"{threads['n']} unresolved review thread(s); reviewDecision={pr.get('reviewDecision') or '-'}")
        elif verdict == "conflict":
            print(f"conflicts with base; in the worktree: git fetch origin && git merge origin/{default_base(ctx.main_root)}")
        if st["attempts"] > MAX_ATTEMPTS:
            print(f"{st['attempts'] - 1} fix attempts used on this PR; last verdict {verdict}")
            verdict = "attempts-exhausted"
    elif verdict in ("green", "merged"):
        st["attempts"] = 0
        save_state(ctx, ctx.branch, st)
    if verdict == "green" and a.merge:
        verdict = do_merge(ctx, cwd, pr)
    if verdict == "merged" and not ctx.is_main:
        # Ruling 1: a PR merged by someone else may not yet be an ancestor of the base in
        # this worktree — teardown failing here must never turn a merged verdict into exit 2.
        try:
            teardown(ctx, ctx.branch)
        except Fail as e:
            warn(f"teardown after merge failed: {e}")
    return done("watch", verdict, pr.get("url", ""))


def cmd_open(a):
    cwd = Path.cwd()
    ctx = repo_ctx(cwd)
    if ctx.branch in PROTECTED:
        raise Fail(f"refusing to open a PR from protected branch {ctx.branch}; run `pr-flow start <slug>` first")
    git("push", "-q", "-u", "origin", ctx.branch, cwd=cwd)
    url, state = pr_url(cwd)
    if state == "MERGED":
        raise Fail(f"PR for {ctx.branch} is already merged; run `pr-flow start` for new work")
    if not url or state == "CLOSED":
        args = ["pr", "create", "--head", ctx.branch]
        args += ["--title", a.title] if a.title else ["--fill"]
        if a.body_file:
            args += ["--body-file", a.body_file]
        if a.draft:
            args.append("--draft")
        url = gh(*args, cwd=cwd).splitlines()[-1]
    print(url)
    return done("open", "ok", url)


def cmd_teardown(a):
    cwd = Path.cwd()
    ctx = repo_ctx(cwd)
    branch = a.branch or ctx.branch
    if not ctx.is_main:
        # Re-exec from the main checkout: a process whose cwd is being removed is a bad way to end.
        os.chdir(ctx.main_root)
        os.execv(sys.executable, [sys.executable, os.path.abspath(__file__), "teardown", branch])
    teardown(ctx, branch)
    return done("teardown", "ok", branch)


def cmd_gc(a):
    cwd = Path.cwd()
    ctx = repo_ctx(cwd)
    root = ctx.main_root
    swept, kept = [], []
    for path, branch in worktrees(root):
        if path.resolve() == root.resolve() or not branch:
            continue
        p = subprocess.run([GH, "pr", "list", "--head", branch, "--state", "merged", "--json", "number", "--jq", "length"],
                            cwd=root, text=True, capture_output=True)
        if p.returncode:
            warn(f"gh pr list failed for {branch} (rc {p.returncode}): {p.stderr.strip() or p.stdout.strip()}")
            kept.append(branch)
            continue
        if p.stdout.strip() not in ("0", ""):
            try:
                teardown(ctx, branch, dry_run=a.dry_run)
                swept.append(branch)
            except Fail as e:
                warn(str(e))
                kept.append(branch)
        else:
            kept.append(branch)
    if a.dry_run:
        print("would sweep: " + (", ".join(swept) or "-"))
        print("kept:  " + (", ".join(kept) or "-"))
        return done("gc", "dry-run", f"{len(swept)} would-sweep")
    print("swept: " + (", ".join(swept) or "-"))
    print("kept:  " + (", ".join(kept) or "-"))
    return done("gc", "ok", f"{len(swept)} swept")


def main(argv=None):
    p = argparse.ArgumentParser(prog="pr-flow", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="verb", required=True)
    s = sub.add_parser("start", help="create branch + worktree off the base branch")
    s.add_argument("slug")
    s.add_argument("--base")
    s.set_defaults(fn=cmd_start)
    o = sub.add_parser("open", help="push the branch and open (or reuse) its PR")
    o.add_argument("--title")
    o.add_argument("--body-file")
    o.add_argument("--draft", action="store_true")
    o.set_defaults(fn=cmd_open)
    w = sub.add_parser("watch", help="poll the PR until a terminal verdict")
    w.add_argument("--merge", action="store_true", help="merge (merge commit) when green; only when the user said so")
    w.add_argument("--timeout", type=float, default=3600)
    w.add_argument("--interval", type=float, default=60)
    w.add_argument("--interval-max", type=float, default=300)
    w.set_defaults(fn=cmd_watch)
    t = sub.add_parser("teardown", help="remove the worktree and delete the merged branch")
    t.add_argument("branch", nargs="?")
    t.set_defaults(fn=cmd_teardown)
    g = sub.add_parser("gc", help="tear down every worktree whose PR is merged")
    g.add_argument("--dry-run", action="store_true")
    g.set_defaults(fn=cmd_gc)
    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except Fail as e:
        warn(str(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
