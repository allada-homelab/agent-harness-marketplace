import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "pr-flow" / "pr-flow.py"
FAKE_GH = Path(__file__).resolve().parent / "fake_gh.py"


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, capture_output=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    main_root = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", str(origin), str(main_root)], check=True)
    git("config", "user.email", "t@example.com", cwd=main_root)
    git("config", "user.name", "t", cwd=main_root)
    (main_root / "README.md").write_text("hello\n")
    git("add", "README.md", cwd=main_root)
    git("commit", "-q", "-m", "init", cwd=main_root)
    git("push", "-q", "-u", "origin", "main", cwd=main_root)
    git("remote", "set-head", "origin", "main", cwd=main_root)
    return main_root, origin


def run(*args, cwd, env=None, replay=None):
    """Run pr-flow.py with a fake gh. `replay` is a list of JSON-able dicts the fake returns for successive `gh pr view` calls."""
    e = dict(os.environ, PR_FLOW_GH=str(FAKE_GH), PR_FLOW_SLEEP="0")
    if replay is not None:
        import json
        p = cwd / ".gh-replay.json"
        p.write_text(json.dumps(replay))
        e["FAKE_GH_REPLAY"] = str(p)
        e["FAKE_GH_LOG"] = str(cwd / ".gh-log")
    if env:
        e.update(env)
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, env=e, text=True, capture_output=True)
