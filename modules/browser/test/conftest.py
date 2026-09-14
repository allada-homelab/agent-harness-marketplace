import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "browser" / "browserctl.mjs"


@pytest.fixture
def sandbox(tmp_path):
    """A HOME with a fake agent-browser on PATH that records argv, and a fake pinned Chrome."""
    home = tmp_path / "home"
    binp = tmp_path / "bin"
    binp.mkdir()
    home.mkdir()
    fake = binp / "agent-browser"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('agent-browser 0.37.1'); sys.exit(0)\n"
        "open(os.path.join(os.environ['HOME'], 'ab-argv.json'), 'w').write(json.dumps(sys.argv[1:]))\n"
        "sys.exit(int(os.environ.get('FAKE_AB_EXIT', '0')))\n"
    )
    fake.chmod(0o755)
    chrome = home / ".browserctl" / "chrome" / "153.0.8010.36" / "chrome-linux64" / "chrome"
    chrome.parent.mkdir(parents=True)
    chrome.write_text("#!/bin/sh\necho chrome\n")
    chrome.chmod(0o755)
    (home / ".browserctl" / "chrome" / "current").symlink_to(chrome)
    return home, binp, chrome


def _run(sandbox, *args, env=None, cwd=None):
    home, binp, _ = sandbox
    e = {"HOME": str(home), "PATH": f"{binp}:{os.environ['PATH']}"}
    e.update(env or {})
    return subprocess.run(["node", str(SCRIPT), *args], env=e, cwd=cwd or home, text=True, capture_output=True)


def _argv(sandbox):
    home = sandbox[0]
    return json.loads((home / "ab-argv.json").read_text())


# The helpers reach the tests as fixtures, not `from conftest import ...`: the
# gate collects every modules/*/test directory in one pytest run, where a bare
# `conftest` module name resolves to whichever directory landed on sys.path first.
@pytest.fixture
def run():
    """Run browserctl in the sandbox: run(sandbox, *args, env=..., cwd=...)."""
    return _run


@pytest.fixture
def argv():
    """The argv the fake agent-browser recorded: argv(sandbox)."""
    return _argv
