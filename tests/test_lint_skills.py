"""bin/lint-skills.py: `context: fork` is the one portable Claude key.

A forked skill is dispatched as an isolated agent on all three harnesses, so
`allowed-tools`, `model` and `agent` carry meaning there; without `context: fork`
they still fail a portable skill. See docs/authoring.md and agent-contract/README.md.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINT = ROOT / "bin" / "lint-skills.py"


def lint(tmp_path, name, text):
    d = tmp_path / "mod" / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(text)
    return subprocess.run([sys.executable, str(LINT), str(tmp_path / "mod")],
                          capture_output=True, text=True)


FORK = """---
name: scout
description: Explore the codebase and report back.
context: fork
allowed-tools: Read, Grep, Bash(git log:*)
model: sonnet
agent: feature-dev:code-explorer
---
Scout the repository for $ARGUMENTS and return a brief.
"""


def test_fork_skill_is_portable(tmp_path):
    p = lint(tmp_path, "scout", FORK)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "FAIL" not in p.stdout


def test_fork_skill_with_unknown_agent_warns_but_passes(tmp_path):
    p = lint(tmp_path, "scout", FORK.replace("agent: feature-dev:code-explorer", "agent: Researcher"))
    assert p.returncode == 0, p.stdout + p.stderr
    assert "WARN" in p.stdout and "Researcher" in p.stdout


def test_context_other_than_fork_is_rejected(tmp_path):
    p = lint(tmp_path, "scout", FORK.replace("context: fork", "context: agent"))
    assert p.returncode == 1
    assert "context: 'agent'" in p.stdout
    # the unlock is tied to fork: the other three keys fail again
    for key in ("allowed-tools", "model", "agent"):
        assert f"key '{key}' is Claude-only" in p.stdout


def test_claude_only_keys_still_fail_without_context(tmp_path):
    p = lint(tmp_path, "scout", FORK.replace("context: fork\n", ""))
    assert p.returncode == 1
    assert "key 'allowed-tools' is Claude-only" in p.stdout


def test_builtin_agent_names_draw_no_agent_warning(tmp_path):
    p = lint(tmp_path, "scout", FORK.replace("agent: feature-dev:code-explorer", "agent: Explore"))
    assert p.returncode == 0, p.stdout + p.stderr
    assert "Explore" not in p.stdout
