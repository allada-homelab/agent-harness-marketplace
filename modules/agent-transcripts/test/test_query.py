import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "skills/transcript-query"),
)
import query as q  # noqa: E402


@pytest.fixture
def indexed(tmp_path):
    """A cache root holding a minimal index with one long message."""
    conn = sqlite3.connect(tmp_path / "transcripts.db")
    conn.executescript(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, text TEXT);"
        "INSERT INTO messages (id, role, text) VALUES (1, 'user', '"
        + "x" * 900
        + "');"
        "INSERT INTO messages (id, role, text) VALUES (2, 'assistant', 'short');"
    )
    conn.commit()
    conn.close()
    return tmp_path


def test_resolve_dest_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TRANSCRIPT_DIR", str(tmp_path / "env"))
    assert q.resolve_dest(str(tmp_path / "cli")) == tmp_path / "cli"
    assert q.resolve_dest(None) == tmp_path / "env"
    monkeypatch.delenv("AGENT_TRANSCRIPT_DIR")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    assert q.resolve_dest(None) == tmp_path / "cache" / "agent-transcripts"


def test_missing_index_is_a_clear_error(tmp_path):
    with pytest.raises(SystemExit) as e:
        q.connect(tmp_path)
    assert "transcript-ingest" in str(e.value)


def test_connection_is_read_only(indexed):
    conn = q.connect(indexed)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM messages")


def test_cells_are_truncated_to_the_width_cap(indexed, capsys):
    q.main(["SELECT text FROM messages WHERE id = 1", "--dest", str(indexed)])
    out = capsys.readouterr().out
    assert "…(+700)" in out  # 900 chars shown at the 200-char default
    assert len(max(out.splitlines(), key=len)) < 300


def test_row_cap_limits_output_and_warns(indexed, capsys):
    q.main(["SELECT id FROM messages", "--dest", str(indexed), "--limit", "1"])
    captured = capsys.readouterr()
    assert len(captured.out.strip().splitlines()) == 2  # header + one row
    assert "more rows" in captured.err


def test_placeholders_are_bound_not_interpolated(indexed, capsys):
    q.main(["SELECT id FROM messages WHERE role = ?", "assistant", "--dest", str(indexed)])
    assert "2" in capsys.readouterr().out


def test_newlines_never_break_the_row_shape(indexed, capsys):
    conn = sqlite3.connect(indexed / "transcripts.db")
    conn.execute("INSERT INTO messages VALUES (3, 'user', 'a\nb')")
    conn.commit()
    conn.close()
    q.main(["SELECT text FROM messages WHERE id = 3", "--dest", str(indexed)])
    out = capsys.readouterr().out
    assert "a\\nb" in out
    assert len(out.strip().splitlines()) == 2
