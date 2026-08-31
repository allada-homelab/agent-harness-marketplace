import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent
        / "skills/claude-transcript-export"
    ),
)
import export as ex


def test_worktree_guard_rejects_repo_dir(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    inner = tmp_path / "exports"
    with pytest.raises(SystemExit):
        ex.assert_outside_worktree(inner)


def test_worktree_guard_allows_plain_dir(tmp_path):
    ex.assert_outside_worktree(tmp_path / "new" / "deep")  # must not raise


def test_discover_parses_container_mounts(monkeypatch):
    # docker ps -a -q -> two ids; docker inspect -> one has a .claude volume mount
    inspect_payload = json.dumps(
        [
            {
                "Name": "/dev-a",
                "Mounts": [
                    {
                        "Type": "volume",
                        "Name": "claude-code-config-abc",
                        "Destination": "/home/vscode/.claude",
                    }
                ],
            },
            {
                "Name": "/dev-b",
                "Mounts": [
                    {"Type": "bind", "Source": "/x", "Destination": "/workspaces/x"}
                ],
            },
        ]
    )

    def fake_run(cmd, **kw):
        out = {
            "ps": "id1\nid2\n",
            "inspect": inspect_payload,
            "volume": "claude-code-config-abc\nclaude-code-config-zzz\nother\n",
        }
        key = next(k for k in out if k in cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=out[key], stderr="")

    monkeypatch.setattr(ex.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(ex.subprocess, "run", fake_run)
    names = {s["name"] for s in ex.discover_sources() if s["kind"] == "volume"}
    assert names == {
        "claude-code-config-abc",
        "claude-code-config-zzz",
    }  # deduped + pattern sweep


def test_should_copy_skips_unchanged(tmp_path):
    dest = tmp_path / "a.jsonl"
    dest.write_bytes(b"x" * 10)
    st = dest.stat()
    assert ex.should_copy({"size": 10, "mtime": int(st.st_mtime)}, dest) is False
    assert ex.should_copy({"size": 11, "mtime": int(st.st_mtime)}, dest) is True


def test_safe_member_rejects_traversal():
    assert ex._is_safe_member("projects/slug/a.jsonl") is True
    assert ex._is_safe_member("../../etc/x.jsonl") is False
    assert ex._is_safe_member("/abs/x.jsonl") is False
