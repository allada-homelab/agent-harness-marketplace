import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "sleep_guard.py"


def run(command, tool="Bash", **extra):
    ev = {"session_id": "s", "cwd": "/", "hook_event_name": "PreToolUse", "tool_name": tool,
          "tool_input": {"command": command, **extra}}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(ev), text=True, capture_output=True)


@pytest.mark.parametrize("command", [
    "sleep 60 && kubectl get pods",
    "sleep 90",
    "  sleep 5; curl -s localhost:8080/health",
    "sleep 1m && echo done",
    "sleep 7.5\ncat log",
    "cd /srv/app && sleep 30 && docker ps",
    "cd 'my dir'; cd sub && sleep 55; tail -5 out.log",
])
def test_blocks_foreground_polling_sleep(command):
    p = run(command)
    assert p.returncode == 2
    assert "until <check>" in p.stderr and "run_in_background" in p.stderr


@pytest.mark.parametrize("command", [
    "sleep 2 && curl localhost:8080",                      # settle delay under the threshold
    "sleep 4.9",
    "sleep 30 &",                                          # already backgrounded
    "timeout 300 bash -c 'until curl -sf x; do sleep 5; done'",
    "kubectl apply -f x.yaml; sleep 10; kubectl get pods",  # not the opening command
    "echo sleep 60",
    "sleepy 60",
    "cd /tmp && ls",
])
def test_allows_everything_else(command):
    p = run(command)
    assert p.returncode == 0 and p.stderr == ""


def test_background_flag_and_other_tools_pass():
    assert run("sleep 60 && echo", run_in_background=True).returncode == 0
    assert run("sleep 60", tool="Edit").returncode == 0


def test_bad_stdin_fails_open():
    p = subprocess.run([sys.executable, str(HOOK)], input="{not json", text=True, capture_output=True)
    assert p.returncode == 0
