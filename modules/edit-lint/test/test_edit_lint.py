import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "edit_lint.py"


@pytest.fixture
def stubs(tmp_path):
    """Install fake linters on a PATH that holds nothing else. Each records its argv and cwd."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"

    def make(name, out="", rc=0, where=bindir):
        where.mkdir(parents=True, exist_ok=True)
        p = where / name
        p.write_text(f"#!/bin/sh\necho \"$(pwd)|{name} $*\" >> '{log}'\nprintf '%b\\n' '{out}'\nexit {rc}\n")
        p.chmod(0o755)
        return p

    def calls():
        return log.read_text().splitlines() if log.exists() else []

    make.calls = calls
    make.bindir = bindir
    return make


def fire(tmp_path, file_path, stubs=None, tool="Edit", cwd=None, claude=False, path=None):
    ev = {"session_id": "s", "cwd": str(cwd or tmp_path), "hook_event_name": "PostToolUse", "tool_name": tool,
          "tool_input": {"file_path": str(file_path)}, "tool_response": ""}
    env = {"PATH": path if path is not None else str(stubs.bindir), "HOME": str(tmp_path),
           "XDG_CACHE_HOME": str(tmp_path / "cache")}
    if claude:
        env["CLAUDECODE"] = "1"
    p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(ev), env=env, text=True, capture_output=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"] if p.stdout.strip() else None


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_shell_findings_are_reported(tmp_path, stubs):
    stubs("shellcheck", out="x.sh:2:1: warning: quote this [SC2086]", rc=1)
    f = write(tmp_path / "x.sh", "#!/bin/bash\necho $a\n")
    ctx = fire(tmp_path, f, stubs)
    assert "shellcheck reported issues" in ctx and "SC2086" in ctx
    assert "-S warning" in stubs.calls()[0]


def test_clean_file_is_silent(tmp_path, stubs):
    stubs("shellcheck", rc=0)
    assert fire(tmp_path, write(tmp_path / "x.sh", "echo hi\n"), stubs) is None


def test_shebang_decides_extensionless_and_zsh(tmp_path, stubs):
    stubs("shellcheck", out="finding", rc=1)
    assert fire(tmp_path, write(tmp_path / "tool", "#!/usr/bin/env bash\necho $a\n"), stubs)
    assert fire(tmp_path, write(tmp_path / "zshy.sh", "#!/usr/bin/env zsh\necho $a\n"), stubs) is None
    assert fire(tmp_path, write(tmp_path / "rc.zsh", "echo $a\n"), stubs) is None
    assert fire(tmp_path, write(tmp_path / "notes", "plain text\n"), stubs) is None
    assert len(stubs.calls()) == 1


def test_workflow_runs_actionlint_from_repo_root(tmp_path, stubs):
    stubs("actionlint", out="ci.yml:3:5: bad", rc=1)
    f = write(tmp_path / "repo" / ".github" / "workflows" / "ci.yml", "on: push\n")
    assert "actionlint" in fire(tmp_path, f, stubs)
    assert stubs.calls()[0].startswith(f"{tmp_path / 'repo'}|actionlint")


def test_k8s_manifest_runs_kubeconform_and_drops_schema_noise(tmp_path, stubs):
    f = write(tmp_path / "deploy.yaml", "apiVersion: apps/v1\nkind: Deployment\n")
    stubs("kubeconform", out="deploy.yaml - Deployment x failed validation: missing spec", rc=1)
    assert "failed validation" in fire(tmp_path, f, stubs)
    assert "-ignore-missing-schemas" in stubs.calls()[0]
    stubs("kubeconform", out="deploy.yaml - Foo x failed downloading schema", rc=1)
    assert fire(tmp_path, f, stubs) is None


def test_templated_yaml_is_skipped(tmp_path, stubs):
    stubs("kubeconform", out="noise", rc=1)
    f = write(tmp_path / "templates" / "svc.yaml", "apiVersion: v1\nkind: Service\nname: {{ .Values.x }}\n")
    assert fire(tmp_path, f, stubs) is None and stubs.calls() == []


def test_ansible_yaml_runs_offline_from_its_config_dir(tmp_path, stubs):
    stubs("ansible-lint", out="roles/web/tasks/main.yml:4: name[missing] All tasks should be named", rc=2)
    write(tmp_path / "infra" / ".ansible-lint", "")
    f = write(tmp_path / "infra" / "roles" / "web" / "tasks" / "main.yml", "- ansible.builtin.ping:\n")
    assert "name[missing]" in fire(tmp_path, f, stubs)
    call = stubs.calls()[0]
    assert call.startswith(f"{tmp_path / 'infra'}|ansible-lint") and "--offline" in call
    play = write(tmp_path / "site.yml", "- hosts: all\n  tasks: []\n")
    assert fire(tmp_path, play, stubs)


def test_other_yaml_is_ignored(tmp_path, stubs):
    for name in ("shellcheck", "actionlint", "kubeconform", "ansible-lint"):
        stubs(name, out="x", rc=1)
    assert fire(tmp_path, write(tmp_path / "compose.yaml", "services: {}\n"), stubs) is None
    assert stubs.calls() == []


def test_js_checked_off_claude_and_skipped_on_claude(tmp_path, stubs):
    stubs("node", out="SyntaxError: Unexpected token", rc=1)
    f = write(tmp_path / "a.mjs", "export const = 1\n")
    assert "SyntaxError" in fire(tmp_path, f, stubs)
    assert fire(tmp_path, f, stubs, claude=True) is None
    assert len(stubs.calls()) == 1


def test_js_in_a_jsx_project_is_skipped(tmp_path, stubs):
    stubs("node", out="SyntaxError", rc=1)
    write(tmp_path / "web" / "package.json", json.dumps({"dependencies": {"react": "^19"}}))
    assert fire(tmp_path, write(tmp_path / "web" / "src" / "App.js", "const a = <div/>\n"), stubs) is None


def test_ts_uses_local_tsc_and_reports_only_the_edited_file(tmp_path, stubs):
    proj = tmp_path / "proj"
    write(proj / "tsconfig.json", "{}")
    out = "src/a.ts(1,7): error TS2322: bad\\nsrc/b.ts(2,1): error TS1005: other"
    stubs("tsc", out=out, rc=2, where=proj / "node_modules" / ".bin")
    f = write(proj / "src" / "a.ts", "const x: number = 's'\n")
    ctx = fire(tmp_path, f, stubs)
    assert "src/a.ts(1,7)" in ctx and "src/b.ts" not in ctx
    assert "--noEmit" in stubs.calls()[0] and stubs.calls()[0].startswith(f"{proj}|tsc")
    assert fire(tmp_path, f, stubs, claude=True) is None


def test_ts_without_tsconfig_is_skipped(tmp_path, stubs):
    stubs("tsc", out="x", rc=2)
    assert fire(tmp_path, write(tmp_path / "loose.ts", "let a = 1\n"), stubs) is None


def test_missing_linter_and_linter_failure_are_silent(tmp_path, stubs):
    f = write(tmp_path / "x.sh", "echo $a\n")
    assert fire(tmp_path, f, stubs) is None  # no shellcheck on PATH
    stubs("shellcheck", out="internal error", rc=3)
    assert fire(tmp_path, f, stubs) is None


def test_relative_path_resolves_against_event_cwd(tmp_path, stubs):
    stubs("shellcheck", out="finding", rc=1)
    write(tmp_path / "proj" / "x.sh", "echo $a\n")
    assert fire(tmp_path, "x.sh", stubs, cwd=tmp_path / "proj")


def test_long_output_is_truncated(tmp_path, stubs):
    stubs("shellcheck", out="y" * 9000, rc=1)
    ctx = fire(tmp_path, write(tmp_path / "x.sh", "echo\n"), stubs)
    assert ctx.endswith("(truncated)") and len(ctx) < 4300


def test_other_tools_missing_files_and_bad_stdin_are_silent(tmp_path, stubs):
    stubs("shellcheck", out="finding", rc=1)
    f = write(tmp_path / "x.sh", "echo $a\n")
    assert fire(tmp_path, f, stubs, tool="Bash") is None
    assert fire(tmp_path, tmp_path / "gone.sh", stubs) is None
    p = subprocess.run([sys.executable, str(HOOK)], input="not json", text=True, capture_output=True)
    assert p.returncode == 0 and p.stdout == ""


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck not installed")
def test_real_shellcheck_round_trip(tmp_path):
    f = write(tmp_path / "x.sh", "#!/bin/bash\ncd $1\n")
    ctx = fire(tmp_path, f, path=os.path.dirname(shutil.which("shellcheck")))
    assert ctx and "SC2164" in ctx  # cd without || exit is a warning; SC2086 (info) is filtered by -S warning
