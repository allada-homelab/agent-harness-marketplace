import json
import os
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "wiki"
SCRIPT = SKILL / "okf.py"
sys.path.insert(0, str(SKILL))
import okf  # noqa: E402,F401  (re-exported to the test modules)

GOOD_META = """type: gotcha
title: pnpm drops peer deps of linked modules
description: Linked modules lose peer deps under pnpm; add them to the root package.json because hoisting skips links.
tags: [pnpm, deps]
sources:
  - {id: s1, resource: "commit:e4132f6", title: fix peer deps}
"""
GOOD_BODY = """
# pnpm drops peer deps of linked modules

## Symptom

Import fails at runtime.[^s1]

## Verify

- `src/app.py` :: `resolve_peers`
"""


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def make_repo(tmp_path, monkeypatch):
    """A git repo with one commit, a `.wiki/`, and isolated state/cache dirs."""
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    (r / "src").mkdir()
    (r / "src" / "app.py").write_text("def resolve_peers():\n    return 1\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "init")
    (r / ".wiki").mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("AGENT_TRANSCRIPT_DIR", str(tmp_path / "transcripts"))
    monkeypatch.delenv("OKF_WIKI_FANOUT", raising=False)
    return r


def concept(repo, cid, meta=GOOD_META, body=GOOD_BODY):
    p = repo / ".wiki" / f"{cid}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n{meta}---\n{body}")
    return p


def run(repo, *args, stdin=None, env=None):
    """Run okf.py as a subprocess, the way skills and hooks call it."""
    e = {**os.environ, **(env or {})}
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(repo), *args],
                          input=stdin, capture_output=True, text=True, env=e, cwd=repo)


def hook(repo, verb, event, env=None):
    e = {**os.environ, **(env or {})}
    return subprocess.run([sys.executable, str(SCRIPT), verb], input=json.dumps(event),
                          capture_output=True, text=True, env=e, cwd=repo)
