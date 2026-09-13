import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "skills/transcript-ingest"),
)
import transcripts as tr


# ------------------------------------------------------------- worktree guard


def test_worktree_guard_rejects_repo_dir(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    with pytest.raises(SystemExit):
        tr.assert_outside_worktree(tmp_path / "exports")


def test_worktree_guard_allows_plain_dir(tmp_path):
    tr.assert_outside_worktree(tmp_path / "new" / "deep")  # must not raise


# ------------------------------------------------------------ dest resolution


def test_resolve_dest_precedence(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".cache").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.delenv("AGENT_TRANSCRIPT_DIR", raising=False)
    assert tr.resolve_dest(None) == home / ".cache" / "agent-transcripts"

    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CACHE_HOME", str(xdg))
    assert tr.resolve_dest(None) == xdg / "agent-transcripts"

    env_dest = tmp_path / "env"
    monkeypatch.setenv("AGENT_TRANSCRIPT_DIR", str(env_dest))
    assert tr.resolve_dest(None) == env_dest

    cli_dest = tmp_path / "cli"
    assert tr.resolve_dest(str(cli_dest)) == cli_dest


# ---------------------------------------------------------- docker discovery


INSPECT_PAYLOAD = json.dumps(
    [
        {
            "Name": "/dev-a",
            "Mounts": [
                {
                    "Type": "volume",
                    "Name": "claude-code-config-abc",
                    "Destination": "/root/.claude",
                }
            ],
        },
        {
            "Name": "/dev-b",
            "Mounts": [
                {"Type": "volume", "Name": "dsh-home-xyz", "Destination": "/root/.dsh"},
                {"Type": "bind", "Source": "/x", "Destination": "/workspaces/x"},
            ],
        },
    ]
)
VOLUME_LS = (
    "claude-code-config-abc\ndsh-home-xyz\ndeepseek-harness_deepseek-home\nother\n"
)


def _fake_docker(monkeypatch):
    def fake_run(cmd, **kw):
        out = {"ps": "id1\nid2\n", "inspect": INSPECT_PAYLOAD, "volume": VOLUME_LS}
        key = next(k for k in out if k in cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=out[key], stderr="")

    monkeypatch.setattr(tr.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(tr.subprocess, "run", fake_run)


def test_discover_claude_volumes(tmp_path, monkeypatch):
    config = tmp_path / "claude-config"
    (config / "projects").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    _fake_docker(monkeypatch)

    sources = tr.discover_claude()
    host = [s for s in sources if s["kind"] == "host"]
    assert [s["origin"] for s in host] == [str(config / "projects")]
    assert {s["name"] for s in sources if s["kind"] == "volume"} == {
        "claude-code-config-abc"
    }
    assert {s["harness"] for s in sources} == {"claude"}
    assert {s["subdir"] for s in sources} == {"projects"}


def test_discover_dsh_volumes(tmp_path, monkeypatch):
    dsh_home = tmp_path / "dsh-home"
    (dsh_home / "sessions").mkdir(parents=True)
    monkeypatch.setenv("DSH_HOME", str(dsh_home))
    _fake_docker(monkeypatch)

    sources = tr.discover_dsh()
    assert {s["name"] for s in sources if s["kind"] == "volume"} == {
        "dsh-home-xyz",  # container mount tier
        "deepseek-harness_deepseek-home",  # orphan name sweep
    }
    host = [s for s in sources if s["kind"] == "host"][0]
    assert host["origin"] == str(dsh_home / "sessions")
    assert host["skipped"] == ["attachments/", "spill/"]
    assert {s["subdir"] for s in sources} == {"sessions"}


# ------------------------------------------------------------- pi discovery


def _pi_env(monkeypatch, agent_dir):
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent_dir))
    monkeypatch.delenv("PI_CODING_AGENT_SESSION_DIR", raising=False)


def test_discover_pi_with_settings(tmp_path, monkeypatch):
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (agent_dir / "settings.json").write_text(json.dumps({"sessionDir": str(elsewhere)}))
    _pi_env(monkeypatch, agent_dir)

    sources = tr.discover_pi()
    assert [(s["subdir"], s["origin"]) for s in sources] == [
        ("settings", str(elsewhere)),
        ("default", str(agent_dir / "sessions")),
    ]
    assert all(s["harness"] == "pi" and s["kind"] == "host" for s in sources)
    assert sources[0]["skipped"] == ["docker volumes (not scanned in v0.1)", "spill/"]


def test_discover_pi_without_settings(tmp_path, monkeypatch):
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    _pi_env(monkeypatch, agent_dir)

    sources = tr.discover_pi()
    assert [(s["subdir"], s["origin"]) for s in sources] == [
        ("default", str(agent_dir / "sessions"))
    ]


# ------------------------------------------------------------------- copying


def test_should_copy_skips_unchanged(tmp_path):
    dest = tmp_path / "a.jsonl"
    dest.write_bytes(b"x" * 10)
    st = dest.stat()
    assert tr.should_copy(10, int(st.st_mtime), dest) is False
    assert tr.should_copy(11, int(st.st_mtime), dest) is True


def test_safe_member_rejects_traversal():
    assert tr._is_safe_member("projects/slug/a.jsonl") is True
    assert tr._is_safe_member("../../etc/x.jsonl") is False


def _host_source(harness, origin, subdir):
    return {
        "harness": harness,
        "kind": "host",
        "name": "host",
        "origin": str(origin),
        "subdir": subdir,
        "skipped": [],
    }


def test_export_copies_tree_then_skips_unchanged(tmp_path, capsys):
    origin = tmp_path / "projects"
    (origin / "slug" / "sess").mkdir(parents=True)
    (origin / "slug" / "sess.jsonl").write_text('{"a": 1}\n')
    (origin / "slug" / "sess" / "subagents").mkdir()
    (origin / "slug" / "sess" / "subagents" / "sub.jsonl").write_text('{"b": 2}\n')
    dest = tmp_path / "cache"
    src = _host_source("claude", origin, "projects")

    manifest = tr.export_sources(dest, [src], dry_run=False)
    assert (dest / "raw/claude/host/projects/slug/sess.jsonl").read_text() == '{"a": 1}\n'
    assert (dest / "raw/claude/host/projects/slug/sess/subagents/sub.jsonl").exists()
    assert "copied=2" in capsys.readouterr().out
    entry = manifest["harnesses"]["claude"]["sources"][0]
    assert entry["files"] == 2
    assert entry["bytes"] == 18
    assert entry["newest_mtime"] > 0

    tr.export_sources(dest, [src], dry_run=False)
    assert "copied=0 unchanged=2" in capsys.readouterr().out


def test_pi_export_skips_spill(tmp_path, capsys):
    origin = tmp_path / "sessions"
    (origin / "spill").mkdir(parents=True)
    (origin / "spill" / "big.bin").write_text("payload")
    (origin / "a.jsonl").write_text("{}\n")
    dest = tmp_path / "cache"

    tr.export_sources(dest, [_host_source("pi", origin, "default")], dry_run=False)
    assert (dest / "raw/pi/host/default/a.jsonl").exists()
    assert not (dest / "raw/pi/host/default/spill").exists()
    assert "copied=1" in capsys.readouterr().out


def test_dry_run_writes_nothing(tmp_path):
    origin = tmp_path / "projects"
    origin.mkdir()
    (origin / "a.jsonl").write_text("{}\n")
    dest = tmp_path / "cache"

    tr.export_sources(dest, [_host_source("claude", origin, "projects")], dry_run=True)
    assert not dest.exists()


def test_manifest_merge_keeps_other_harnesses(tmp_path):
    claude_origin = tmp_path / "projects"
    claude_origin.mkdir()
    (claude_origin / "a.jsonl").write_text("{}\n")
    dsh_origin = tmp_path / "sessions"
    (dsh_origin / "key" / "sid").mkdir(parents=True)
    (dsh_origin / "key" / "sid" / "session.jsonl.zstd").write_bytes(b"\x28\xb5\x2f\xfd")
    dest = tmp_path / "cache"
    dest.mkdir()

    first = tr.export_sources(
        dest, [_host_source("claude", claude_origin, "projects")], dry_run=False
    )
    (dest / "manifest.json").write_text(json.dumps(first))

    second = tr.export_sources(
        dest, [_host_source("dsh", dsh_origin, "sessions")], dry_run=False
    )
    assert set(second["harnesses"]) == {"claude", "dsh"}
    assert second["harnesses"]["claude"]["sources"][0]["files"] == 1
    assert second["harnesses"]["dsh"]["sources"][0]["files"] == 1
    assert (dest / "raw/dsh/host/sessions/key/sid/session.jsonl.zstd").exists()
