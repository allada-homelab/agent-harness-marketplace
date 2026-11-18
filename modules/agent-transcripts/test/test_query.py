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


# ------------------------------------------------- cost recipes in SKILL.md

SKILL = Path(__file__).resolve().parent.parent / "skills/transcript-query/SKILL.md"


def _cost_recipes() -> list[str]:
    """The SQL blocks of the SKILL.md cost section, so the doc stays the only copy."""
    text = SKILL.read_text()
    section = text.split("### Where the tokens go", 1)[1].split("\n## ", 1)[0]
    return [b.split("```", 1)[0] for b in section.split("```sql\n")[1:]]


@pytest.fixture
def costed(tmp_path):
    """A real-schema index: one main session with a compaction, one typed subagent."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills/transcript-ingest"))
    import transcripts as tr

    conn = tr.open_db(tmp_path)
    conn.execute(
        "INSERT INTO files (id, harness, relpath, size, mtime, parser_version, status, parsed_at)"
        " VALUES (1, 'claude', 'f', 0, 0, 0, 'ok', '')"
    )
    conn.executemany(
        "INSERT INTO sessions (id, harness, native_id, file_id, kind, parent_native_id,"
        " project_key, started_at) VALUES (?, 'claude', ?, 1, ?, ?, 'proj', '2026-01-01')",
        [(1, "main-1", "main", None), (2, "agent-0123456789abcdef0", "subagent", "main-1")],
    )
    compaction = "This session is being continued from a previous conversation. Summary."
    rows = [  # (id, session, ord, role, text, output_tokens)
        (1, 1, 0, "user", "go", None),
        (2, 1, 1, "assistant", "", 10),  # calls Read
        (3, 1, 2, "tool_result", "x" * 4_000_000, None),  # ~1M tokens
        (4, 1, 3, "assistant", "", 10),  # calls Agent
        (5, 1, 4, "tool_result", "agentId: 0123456789abcdef0 (internal ID)", None),
        (6, 1, 5, "assistant", "", 10),
        (7, 1, 6, "system", compaction, None),
        (8, 1, 7, "assistant", "", 10),  # after compaction: must not re-read row 3
        (9, 2, 0, "assistant", "", 1_000_000),
    ]
    conn.executemany(
        "INSERT INTO messages (id, session_id, ord, on_main_path, role, ts, text, output_tokens,"
        " injected, norm_key, harness) VALUES (?, ?, ?, 1, ?, '2026-01-02', ?, ?, 0, '', 'claude')",
        rows,
    )
    conn.executemany(
        "INSERT INTO tool_calls (message_id, call_id, name, arguments, result_message_id,"
        " is_error, harness) VALUES (?, ?, ?, ?, ?, 0, 'claude')",
        [
            (2, "c1", "Read", '{"file_path": "/big.txt"}', 3),
            (4, "c2", "Agent", '{"subagent_type": "Explore"}', 5),
        ],
    )
    conn.commit()
    conn.close()
    return tmp_path


def _run(dest, sql, *params):
    conn = q.connect(dest)
    return conn.execute(sql, params).fetchall()


def test_cost_section_has_every_recipe():
    assert len(_cost_recipes()) == 5


def test_session_and_model_recipes_roll_up_subagents(costed):
    top, by_model, *_ = _cost_recipes()
    # 4 main calls × 10 output × 5 + subagent 1M output × 5, all under the main session
    assert _run(costed, top, "2026-01-01") == [("main-1", "proj", "2026-01-01", 5.0, 100.0)]
    assert {r[0] for r in _run(costed, by_model, "2026-01-01")} == {"main", "subagent"}


def test_residency_ends_at_compaction(costed):
    residency = _cost_recipes()[2]
    rows = {r[0]: r for r in _run(costed, residency, "2026-01-01")}
    # Read result: 1M tokens × (2 write + 0.1 × 2 later calls before the compaction)
    assert rows["Read"][3] == 2 and rows["Read"][4] == 2.2


def test_drill_down_reuses_the_residency_steps(costed):
    _, _, residency, drill, _ = _cost_recipes()
    sql = residency[: residency.index("SELECT t.name")] + drill
    assert _run(costed, sql, "2026-01-01", "Read") == [("/big.txt", 1, 1_000_000.0, 2.2)]


def test_agent_type_recipe_links_call_to_subagent(costed):
    by_type = _cost_recipes()[4]
    assert _run(costed, by_type, "2026-01-01") == [("Explore", None, 1, 5.0, 5000.0)]
