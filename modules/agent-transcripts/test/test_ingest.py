import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest
import zstandard

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "skills/transcript-ingest"),
)
import transcripts as tr

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ------------------------------------------------------------- dsh fixture


def _frame(records) -> bytes:
    """One independent zstd frame holding these JSONL rows, as dsh writes batches."""
    body = "".join(json.dumps(r) + "\n" for r in records).encode()
    return zstandard.ZstdCompressor().compress(body)


DSH_HEADER = {
    "type": "session",
    "version": 0,
    "id": "session-0000",
    "cwd": "/tmp/proj",
    "createdAt": 1700000000000,
    "parentSession": None,
    "origin": None,
    "delegationDepth": 0,
}

DSH_BODY = [
    {
        "type": "user/message",
        "seq": 1,
        "time": 1700000001000,
        "data": {
            "id": "u1",
            "role": "user",
            "content": [{"type": "text", "text": "count the widgets"}],
        },
    },
    {"type": "assistant/chunk", "seq": 2, "data": {"delta": "listing"}},
    {"type": "text-chunks", "seq": 3, "data": {"delta": " the widgets"}},
    {
        "type": "assistant/message",
        "seq": 4,
        "time": 1700000003000,
        "data": {
            "turn": 1,
            "step": 1,
            "usage": {"inputTokens": 1, "outputTokens": 2},
            "message": {
                "id": "a1",
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "listing the widgets"},
                    {
                        "type": "toolCall",
                        "id": "c1",
                        "name": "bash",
                        "arguments": {"command": "ls"},
                    },
                ],
                "source": {
                    "model": "model-epsilon",
                    "provider": "provider-x",
                    "replayState": {"response": {"stopReason": "toolCall"}},
                },
            },
        },
    },
    {
        "type": "tool/call",
        "seq": 5,
        "data": {
            "turn": 1,
            "step": 1,
            "callId": "c1",
            "name": "bash",
            "arguments": {"command": "ls"},
        },
    },
    {
        "type": "tool/result",
        "seq": 6,
        "time": 1700000005000,
        "data": {
            "turn": 1,
            "step": 1,
            "message": {
                "id": "r1",
                "role": "toolResult",
                "content": [
                    {
                        "type": "toolResult",
                        "toolCallId": "c1",
                        "isError": False,
                        "content": [{"type": "text", "text": "widget-one"}],
                    }
                ],
            },
        },
    },
    {"type": "session/title", "data": {"title": "Widget count"}},
]

DSH_TAIL = [
    {
        "type": "user/message",
        "seq": 7,
        "time": 1700000007000,
        "data": {
            "id": "u2",
            "role": "user",
            "content": [{"type": "text", "text": "lost to truncation"}],
        },
    }
]

DSH_SUBAGENT = [
    {
        "type": "user/message",
        "seq": 1,
        "time": 1700000010000,
        "data": {
            "id": "su1",
            "role": "user",
            "content": [{"type": "text", "text": "inspect the widget shelf"}],
        },
    },
    {
        "type": "assistant/message",
        "seq": 2,
        "time": 1700000011000,
        "data": {
            "turn": 1,
            "step": 1,
            "usage": {"inputTokens": 3, "outputTokens": 4},
            "message": {
                "id": "sa1",
                "role": "assistant",
                "content": [{"type": "text", "text": "the shelf holds one widget"}],
                "source": {
                    "model": "model-epsilon",
                    "provider": "provider-x",
                    "replayState": {"response": {"stopReason": "endTurn"}},
                },
            },
        },
    },
]


def _dsh_bytes(truncated: bool = False) -> bytes:
    data = _frame([DSH_HEADER]) + _frame(DSH_BODY[:4]) + _frame(DSH_BODY[4:])
    if truncated:
        tail = _frame(DSH_TAIL)
        data += tail[: len(tail) // 2]  # a half-written final frame
    return data


def build_cache(tmp_path, truncated: bool = False) -> Path:
    """A cache root holding every fixture in the exported raw/ layout."""
    root = tmp_path / "cache"
    shutil.copytree(FIXTURES / "claude", root / "raw" / "claude" / "host")
    shutil.copytree(FIXTURES / "pi", root / "raw" / "pi" / "host")
    sessions = root / "raw" / "dsh" / "host" / "sessions" / "--tmp-proj--"
    (sessions / "session-0000").mkdir(parents=True)
    (sessions / "session-0000" / "session.jsonl.zstd").write_bytes(
        _dsh_bytes(truncated)
    )
    (sessions / "0001").mkdir()
    (sessions / "0001" / "session.jsonl.zstd").write_bytes(
        _frame(
            [
                {
                    **DSH_HEADER,
                    "id": "session-0001",
                    "parentSession": "session-0000",
                    "origin": "subagent",
                    "delegationDepth": 1,
                }
            ]
        )
        + _frame(DSH_SUBAGENT)
    )
    return root


@pytest.fixture
def cache(tmp_path):
    return build_cache(tmp_path)


def _rows(conn, sql, *params):
    return conn.execute(sql, params).fetchall()


def _ingested(root, rebuild=False):
    errors = tr.ingest(root, rebuild)
    return errors, tr.open_db(root)


# ---------------------------------------------------------------- discovery


def test_iter_raw_files_finds_every_harness(cache):
    found = tr.iter_raw_files(cache)
    assert [(h, p.relative_to(cache).as_posix()) for h, p in found] == [
        ("claude", "raw/claude/host/projects/-tmp-proj/s1.jsonl"),
        ("claude", "raw/claude/host/projects/-tmp-proj/s1/subagents/agent-a.jsonl"),
        ("dsh", "raw/dsh/host/sessions/--tmp-proj--/0001/session.jsonl.zstd"),
        ("dsh", "raw/dsh/host/sessions/--tmp-proj--/session-0000/session.jsonl.zstd"),
        ("pi", "raw/pi/host/default/2026-01-01T00-00-00-000Z_0000-uuid.jsonl"),
        ("pi", "raw/pi/host/default/v1.jsonl"),
    ]


def test_iter_raw_files_finds_dsh_v3_sessions_and_ingest_parses_them(tmp_path):
    """dsh renamed its session logs to session.v3.jsonl.zstd; both names must be found."""
    cache = build_cache(tmp_path)
    v3 = cache / "raw/dsh/host/sessions/--tmp-proj--/session-v3/session.v3.jsonl.zstd"
    v3.parent.mkdir()
    v3.write_bytes(
        _frame([{**DSH_HEADER, "id": "session-v3", "version": 3}])
        + _frame(DSH_BODY[:4])
    )
    dsh_names = [p.name for h, p in tr.iter_raw_files(cache) if h == "dsh"]
    assert "session.v3.jsonl.zstd" in dsh_names
    assert "session.jsonl.zstd" in dsh_names

    assert tr.ingest(cache, rebuild=False) == 1  # only the pi v1 fixture errors
    conn = tr.open_db(cache)
    assert (
        conn.execute(
            "SELECT count(*) FROM sessions WHERE harness = 'dsh' AND native_id = 'session-v3'"
        ).fetchone()[0]
        == 1
    )
    conn.close()


def _legacy_and_v3_pair(cache) -> tuple[Path, Path]:
    """One dsh session dir holding both names: dsh's v3 upgrade rewrites the whole
    history into session.v3.jsonl.zstd and leaves the legacy file beside it."""
    d = cache / "raw/dsh/host/sessions/--tmp-proj--/session-both"
    d.mkdir()
    header = {**DSH_HEADER, "id": "session-both"}
    legacy = d / "session.jsonl.zstd"
    legacy.write_bytes(_frame([header]) + _frame(DSH_BODY[:4]))
    v3 = d / "session.v3.jsonl.zstd"
    # the v3 copy is a superset: same history plus the later turns
    v3.write_bytes(_frame([{**header, "version": 3}]) + _frame(DSH_BODY))
    return legacy, v3


def test_iter_raw_files_prefers_v3_over_a_legacy_sibling(tmp_path):
    cache = build_cache(tmp_path)
    legacy, v3 = _legacy_and_v3_pair(cache)
    found = [p for h, p in tr.iter_raw_files(cache) if h == "dsh"]
    assert v3 in found
    assert legacy not in found

    tr.ingest(cache, rebuild=False)
    conn = tr.open_db(cache)
    assert _rows(
        conn,
        "SELECT f.relpath FROM sessions s JOIN files f ON f.id = s.file_id"
        " WHERE s.native_id = 'session-both'",
    ) == [(v3.relative_to(cache).as_posix(),)]
    conn.close()


def test_a_legacy_session_already_indexed_is_dropped_once_v3_appears(tmp_path, capsys):
    """An index built before the v3 file existed holds the legacy copy; the next
    incremental ingest must replace it, not keep both (their content differs, so
    the content-match dedupe would not catch it)."""
    cache = build_cache(tmp_path)
    legacy, v3 = _legacy_and_v3_pair(cache)
    v3_bytes = v3.read_bytes()
    v3.unlink()
    tr.ingest(cache, rebuild=False)  # indexes the legacy file
    v3.write_bytes(v3_bytes)
    capsys.readouterr()

    tr.ingest(cache, rebuild=False)
    assert "removed=1" in capsys.readouterr().out
    conn = tr.open_db(cache)
    assert _rows(
        conn,
        "SELECT f.relpath FROM sessions s JOIN files f ON f.id = s.file_id"
        " WHERE s.native_id = 'session-both'",
    ) == [(v3.relative_to(cache).as_posix(),)]
    assert _rows(
        conn, "SELECT count(*) FROM files WHERE relpath = ?",
        legacy.relative_to(cache).as_posix(),
    ) == [(0,)]
    conn.close()


def test_ingest_populates_norm_key_and_harness(cache):
    tr.ingest(cache, rebuild=False)
    conn = tr.open_db(cache)
    assert conn.execute(
        "SELECT count(*) FROM messages WHERE norm_key = '' OR harness = ''"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT count(*) FROM messages WHERE harness = 'dsh'"
    ).fetchone()[0] > 0
    assert conn.execute(
        "SELECT count(*) FROM tool_calls WHERE harness = 'dsh'"
    ).fetchone()[0] > 0
    # norm_key is a fixed-size digest, not the (possibly huge) normalized text
    keys = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT norm_key FROM messages WHERE norm_key != ''"
        )
    ]
    assert keys
    assert all(
        len(k) == 64 and all(c in "0123456789abcdef" for c in k) for k in keys
    )
    conn.close()


def test_annotate_raises_when_norm_key_unpopulated(cache):
    tr.ingest(cache, rebuild=False)
    conn = tr.open_db(cache)
    conn.execute("UPDATE messages SET norm_key = ''")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="rebuild"):
        tr.annotate(cache)


def test_to_iso_formats_epoch_millis():
    assert tr.to_iso(1700000001000) == "2023-11-14T22:13:21.000Z"


# ------------------------------------------------------------------- claude


def test_claude_session_and_messages(cache):
    _, conn = _ingested(cache)
    (main,) = _rows(
        conn,
        "SELECT native_id, cwd, project_key, kind, parent_native_id, started_at,"
        " ended_at, model, title FROM sessions WHERE harness='claude' AND kind='main'",
    )
    assert main == (
        "s1",
        "/tmp/proj",
        "-tmp-proj",
        "main",
        None,
        "2026-01-01T00:00:01.000Z",
        "2026-01-01T00:00:07.000Z",
        "model-beta",
        "Widget count",
    )
    assert _rows(
        conn,
        "SELECT native_id, kind, parent_native_id FROM sessions"
        " WHERE harness='claude' AND kind='subagent'",
    ) == [("agent-a", "subagent", "s1")]

    msgs = _rows(
        conn,
        "SELECT m.native_id, m.role, m.text, m.model, m.stop_reason, m.input_tokens,"
        " m.output_tokens FROM messages m JOIN sessions s ON s.id = m.session_id"
        " WHERE s.native_id = 's1' ORDER BY m.ord",
    )
    assert [(r[0], r[1]) for r in msgs] == [
        ("u1", "user"),
        ("a1", "assistant"),
        ("r1", "tool_result"),  # a user record carrying a tool_result block
        ("a2", "assistant"),
        ("a3", "assistant"),
        ("u2", "user"),
    ]
    assert msgs[0][2] == "count the widgets"  # a plain string is one text block
    assert msgs[1][2] == "listing the widgets"  # tool_use input is not text
    assert msgs[1][3:] == ("model-alpha", "tool_use", 1, 2)


def test_claude_branch_marks_main_path(cache):
    _, conn = _ingested(cache)
    assert dict(
        _rows(
            conn,
            "SELECT m.native_id, m.on_main_path FROM messages m"
            " JOIN sessions s ON s.id = m.session_id WHERE s.native_id = 's1'",
        )
    ) == {"u1": 1, "a1": 1, "r1": 1, "a2": 0, "a3": 1, "u2": 1}


def test_claude_tool_call_links_its_result(cache):
    _, conn = _ingested(cache)
    (row,) = _rows(
        conn,
        "SELECT t.call_id, t.name, t.arguments, t.is_error, r.native_id"
        " FROM tool_calls t JOIN messages m ON m.id = t.message_id"
        " JOIN messages r ON r.id = t.result_message_id"
        " JOIN sessions s ON s.id = m.session_id WHERE s.harness = 'claude'",
    )
    assert row == ("tu1", "Bash", '{"command": "ls"}', 0, "r1")


# ----------------------------------------------------------------------- pi


def test_pi_session_and_messages(cache):
    _, conn = _ingested(cache)
    (sess,) = _rows(
        conn,
        "SELECT native_id, cwd, project_key, kind, started_at, ended_at, model, title"
        " FROM sessions WHERE harness = 'pi'",
    )
    assert sess == (
        "0000-uuid",
        "/tmp/proj",
        "-tmp-proj",
        "main",
        "2026-01-01T00:00:01.000Z",
        "2026-01-01T00:00:05.000Z",
        "model-delta",
        "Widget count",
    )
    msgs = _rows(
        conn,
        "SELECT m.native_id, m.role, m.text, m.model, m.stop_reason, m.input_tokens,"
        " m.output_tokens FROM messages m JOIN sessions s ON s.id = m.session_id"
        " WHERE s.harness = 'pi' ORDER BY m.ord",
    )
    assert [(r[0], r[1]) for r in msgs] == [
        ("aaaa1111", "user"),
        ("bbbb2222", "assistant"),
        ("cccc3333", "tool_result"),
        ("dddd4444", "assistant"),
        ("eeee5555", "assistant"),
    ]
    # model_change supplies the model for the assistant message that lacks one
    assert msgs[1][3:] == ("model-gamma", "toolCall", 1, 2)
    assert msgs[2][2] == "widget-one"
    assert msgs[3][3] == "model-delta"


def test_pi_fork_marks_main_path(cache):
    _, conn = _ingested(cache)
    assert dict(
        _rows(
            conn,
            "SELECT m.native_id, m.on_main_path FROM messages m"
            " JOIN sessions s ON s.id = m.session_id WHERE s.harness = 'pi'",
        )
    ) == {
        "aaaa1111": 1,
        "bbbb2222": 1,
        "cccc3333": 1,
        "dddd4444": 0,
        "eeee5555": 1,
    }


def test_pi_tool_call_links_its_result(cache):
    _, conn = _ingested(cache)
    (row,) = _rows(
        conn,
        "SELECT t.call_id, t.name, t.arguments, t.is_error, r.native_id"
        " FROM tool_calls t JOIN messages m ON m.id = t.message_id"
        " JOIN messages r ON r.id = t.result_message_id"
        " JOIN sessions s ON s.id = m.session_id WHERE s.harness = 'pi'",
    )
    assert row == ("tc1", "bash", '{"command": "ls"}', 0, "cccc3333")


def test_pi_v1_header_is_recorded_as_an_error(cache):
    errors, conn = _ingested(cache)
    assert errors == 1
    (row,) = _rows(
        conn, "SELECT relpath, status, error FROM files WHERE status = 'error'"
    )
    assert row[0].endswith("v1.jsonl")
    assert "v1 is unsupported" in row[2]
    assert tr.main(["ingest", "--dest", str(cache), "--rebuild"]) == 1


# ---------------------------------------------------------------------- dsh


def test_dsh_session_and_messages(cache):
    _, conn = _ingested(cache)
    (main,) = _rows(
        conn,
        "SELECT native_id, cwd, project_key, kind, parent_native_id, started_at,"
        " ended_at, model, title FROM sessions WHERE harness='dsh' AND kind='main'",
    )
    assert main == (
        "session-0000",
        "/tmp/proj",
        "--tmp-proj--",
        "main",
        None,
        "2023-11-14T22:13:21.000Z",
        "2023-11-14T22:13:25.000Z",
        "model-epsilon",
        "Widget count",
    )
    assert _rows(
        conn,
        "SELECT native_id, kind, parent_native_id FROM sessions"
        " WHERE harness='dsh' AND kind='subagent'",
    ) == [("session-0001", "subagent", "session-0000")]

    msgs = _rows(
        conn,
        "SELECT m.native_id, m.role, m.text, m.on_main_path, m.model, m.stop_reason,"
        " m.input_tokens, m.output_tokens FROM messages m"
        " JOIN sessions s ON s.id = m.session_id"
        " WHERE s.native_id = 'session-0000' ORDER BY m.ord",
    )
    # every chunk row is dropped: only the three real messages survive
    assert [(r[0], r[1], r[3]) for r in msgs] == [
        ("u1", "user", 1),
        ("a1", "assistant", 1),
        ("r1", "tool_result", 1),
    ]
    assert msgs[1][2] == "listing the widgets"
    assert msgs[1][4:] == ("model-epsilon", "toolCall", 1, 2)
    assert msgs[2][2] == "widget-one"


def test_dsh_tool_call_is_not_duplicated_by_the_call_row(cache):
    _, conn = _ingested(cache)
    rows = _rows(
        conn,
        "SELECT t.call_id, t.name, t.arguments, t.is_error, m.native_id, r.native_id"
        " FROM tool_calls t JOIN messages m ON m.id = t.message_id"
        " JOIN messages r ON r.id = t.result_message_id"
        " JOIN sessions s ON s.id = m.session_id WHERE s.harness = 'dsh'",
    )
    assert rows == [("c1", "bash", '{"command": "ls"}', 0, "a1", "r1")]


def test_dsh_truncated_tail_keeps_the_complete_prefix(tmp_path):
    root = build_cache(tmp_path, truncated=True)
    path = root / "raw/dsh/host/sessions/--tmp-proj--/session-0000/session.jsonl.zstd"
    lines = list(tr.decode_zstd_lines(path))
    assert len(lines) == len(DSH_BODY) + 1  # header + every complete body row
    assert all("lost to truncation" not in line for line in lines)

    errors, conn = _ingested(root)
    assert errors == 1  # only the pi v1 file
    assert _rows(
        conn,
        "SELECT count(*) FROM messages m JOIN sessions s ON s.id = m.session_id"
        " WHERE s.native_id = 'session-0000'",
    ) == [(3,)]


# The shape dsh actually writes: `tool-result` content items, the call id on the
# item and on message.source, and tool/call arguments as a JSON *string*.
DSH_NATIVE_TOOLS = [
    {
        "type": "user/message",
        "seq": 1,
        "time": 1700000001000,
        "data": {
            "id": "nu1",
            "role": "user",
            "content": [{"type": "text", "text": "count the widgets"}],
        },
    },
    {
        "type": "assistant/message",
        "seq": 2,
        "time": 1700000002000,
        "data": {
            "turn": 1,
            "step": 1,
            "message": {
                "id": "na1",
                "role": "assistant",
                "content": [{"type": "text", "text": "listing the widgets"}],
                "source": {"model": "model-epsilon", "provider": "provider-x"},
            },
        },
    },
    {
        "type": "tool/call",
        "seq": 3,
        "time": 1700000003000,
        "data": {
            "turn": 1,
            "step": 1,
            "callId": "call-ok",
            "name": "run_code",
            "arguments": '{"command": "ls"}',
        },
    },
    {
        "type": "tool/result",
        "seq": 4,
        "time": 1700000004000,
        "data": {
            "turn": 1,
            "step": 1,
            "message": {
                "id": "res-ok",
                "role": "toolResult",
                "source": {"kind": "tool", "callId": "call-ok"},
                "content": [
                    {
                        "type": "tool-result",
                        "toolCallId": "call-ok",
                        "isError": False,
                        "content": [{"type": "text", "text": "widget-one"}],
                    }
                ],
            },
        },
    },
    {
        "type": "tool/call",
        "seq": 5,
        "time": 1700000005000,
        "data": {
            "turn": 1,
            "step": 2,
            "callId": "call-bad",
            "name": "run_code",
            "arguments": "not json at all",
        },
    },
    {
        "type": "tool/result",
        "seq": 6,
        "time": 1700000006000,
        "data": {
            "turn": 1,
            "step": 2,
            "error": {"name": "ToolArgsError", "code": "INVALID_ARGS"},
            "message": {
                "id": "res-bad",
                "role": "toolResult",
                "source": {"kind": "tool", "callId": "call-bad"},
                "content": [
                    {
                        "type": "tool-result",
                        "toolCallId": "call-bad",
                        "isError": True,
                        "content": [{"type": "text", "text": "Error: bad arguments"}],
                    }
                ],
            },
        },
    },
    {
        "type": "tool/call",
        "seq": 7,
        "time": 1700000007000,
        "data": {"turn": 1, "step": 3, "callId": "call-row", "name": "run_code"},
    },
    {
        "type": "tool/result",
        "seq": 8,
        "time": 1700000008000,
        "data": {
            "turn": 1,
            "step": 3,
            "error": {"name": "ToolArgsError", "code": "INVALID_ARGS"},
            "message": {
                "id": "res-row",
                "role": "toolResult",
                "source": {"kind": "tool", "callId": "call-row"},
                "content": [
                    {
                        "type": "tool-result",
                        "toolCallId": "call-row",
                        "content": [{"type": "text", "text": "row-level failure"}],
                    }
                ],
            },
        },
    },
]


@pytest.fixture
def dsh_native_cache(tmp_path):
    """A cache holding one dsh session written the way dsh really writes tool rows."""
    root = tmp_path / "cache"
    session = root / "raw/dsh/host/sessions/--tmp-proj--/session-9999"
    session.mkdir(parents=True)
    (session / "session.jsonl.zstd").write_bytes(
        _frame([{**DSH_HEADER, "id": "session-9999"}]) + _frame(DSH_NATIVE_TOOLS)
    )
    return root


def test_dsh_native_tool_results_link_and_carry_their_error_flag(dsh_native_cache):
    errors, conn = _ingested(dsh_native_cache)
    assert errors == 0
    assert _rows(
        conn,
        "SELECT t.call_id, t.is_error, r.native_id FROM tool_calls t"
        " JOIN messages r ON r.id = t.result_message_id ORDER BY t.call_id",
    ) == [
        ("call-bad", 1, "res-bad"),
        ("call-ok", 0, "res-ok"),
        ("call-row", 1, "res-row"),  # flagged by data.error alone
    ]


def test_dsh_tool_result_text_is_stored_and_indexed(dsh_native_cache):
    _, conn = _ingested(dsh_native_cache)
    assert _rows(
        conn,
        "SELECT native_id, text FROM messages WHERE role = 'tool_result' ORDER BY ord",
    ) == [
        ("res-ok", "widget-one"),
        ("res-bad", "Error: bad arguments"),
        ("res-row", "row-level failure"),
    ]
    assert _rows(
        conn,
        "SELECT m.native_id FROM messages_fts f JOIN messages m ON m.id = f.rowid"
        " WHERE messages_fts MATCH '\"widget-one\"'",
    ) == [("res-ok",)]


def test_dsh_arguments_are_unwrapped_from_their_json_string(dsh_native_cache):
    _, conn = _ingested(dsh_native_cache)
    assert _rows(
        conn, "SELECT call_id, arguments FROM tool_calls ORDER BY call_id"
    ) == [
        ("call-bad", '"not json at all"'),  # not JSON: kept as the string it is
        ("call-ok", '{"command": "ls"}'),
        ("call-row", "null"),
    ]


# dsh's bash tool marks a failed run only by appending "[exit code: N]" to the
# result text; isError/data.error stay unset even on a nonzero exit.
DSH_BASH_EXIT_CODE_TOOLS = [
    {
        "type": "user/message",
        "seq": 1,
        "time": 1700000001000,
        "data": {"id": "bu1", "role": "user", "content": [{"type": "text", "text": "run stuff"}]},
    },
    {
        "type": "assistant/message",
        "seq": 2,
        "time": 1700000002000,
        "data": {
            "turn": 1,
            "step": 1,
            "message": {
                "id": "ba1",
                "role": "assistant",
                "content": [{"type": "text", "text": "running it"}],
                "source": {"model": "model-epsilon"},
            },
        },
    },
    {
        "type": "tool/call",
        "seq": 3,
        "time": 1700000003000,
        "data": {"turn": 1, "step": 1, "callId": "bash-fail", "name": "bash", "arguments": '{"command": "false"}'},
    },
    {
        "type": "tool/result",
        "seq": 4,
        "time": 1700000004000,
        "data": {
            "turn": 1,
            "step": 1,
            "message": {
                "id": "bres-fail",
                "role": "toolResult",
                "content": [
                    {
                        "type": "tool-result",
                        "toolCallId": "bash-fail",
                        "isError": False,
                        "content": [{"type": "text", "text": "boom\n[exit code: 1]"}],
                    }
                ],
            },
        },
    },
    {
        "type": "tool/call",
        "seq": 5,
        "time": 1700000005000,
        "data": {"turn": 1, "step": 2, "callId": "bash-ok", "name": "bash", "arguments": '{"command": "true"}'},
    },
    {
        "type": "tool/result",
        "seq": 6,
        "time": 1700000006000,
        "data": {
            "turn": 1,
            "step": 2,
            "message": {
                "id": "bres-ok",
                "role": "toolResult",
                "content": [
                    {
                        "type": "tool-result",
                        "toolCallId": "bash-ok",
                        "isError": False,
                        "content": [{"type": "text", "text": "ok"}],
                    }
                ],
            },
        },
    },
    {
        "type": "tool/call",
        "seq": 7,
        "time": 1700000007000,
        "data": {"turn": 1, "step": 3, "callId": "read-fail", "name": "read", "arguments": '{"path": "x"}'},
    },
    {
        "type": "tool/result",
        "seq": 8,
        "time": 1700000008000,
        "data": {
            "turn": 1,
            "step": 3,
            "message": {
                "id": "rres",
                "role": "toolResult",
                "content": [
                    {
                        "type": "tool-result",
                        "toolCallId": "read-fail",
                        "isError": False,
                        # a non-bash tool's own output can legitimately contain the same
                        # text; it must not be read as that tool's exit status.
                        "content": [{"type": "text", "text": "grep hit: '[exit code: 1]'"}],
                    }
                ],
            },
        },
    },
]


@pytest.fixture
def dsh_bash_exit_cache(tmp_path):
    root = tmp_path / "cache"
    session = root / "raw/dsh/host/sessions/--tmp-proj--/session-8888"
    session.mkdir(parents=True)
    (session / "session.jsonl.zstd").write_bytes(
        _frame([{**DSH_HEADER, "id": "session-8888"}]) + _frame(DSH_BASH_EXIT_CODE_TOOLS)
    )
    return root


def test_dsh_bash_is_error_is_derived_from_the_exit_code_marker(dsh_bash_exit_cache):
    errors, conn = _ingested(dsh_bash_exit_cache)
    assert errors == 0
    assert _rows(
        conn,
        "SELECT t.call_id, t.name, t.is_error FROM tool_calls t ORDER BY t.call_id",
    ) == [
        ("bash-fail", "bash", 1),  # isError absent, but "[exit code: 1]" -> derived error
        ("bash-ok", "bash", 0),  # no exit-code marker at all -> untouched
        ("read-fail", "read", 0),  # non-bash tool: the marker text is not interpreted
    ]


# ------------------------------------------------------- claude tool results


CLAUDE_RESULT_LINES = [
    {
        "type": "assistant",
        "uuid": "ra1",
        "parentUuid": None,
        "timestamp": "2026-01-01T00:00:01.000Z",
        "message": {
            "role": "assistant",
            "model": "model-alpha",
            "content": [
                {"type": "tool_use", "id": "tu9", "name": "Read", "input": {"f": "a"}},
                {"type": "tool_use", "id": "tu8", "name": "Read", "input": {"f": "b"}},
            ],
        },
    },
    {
        "type": "user",
        "uuid": "rr1",
        "parentUuid": "ra1",
        "timestamp": "2026-01-01T00:00:02.000Z",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tu9",
                    "is_error": True,
                    "content": "<tool_use_error>File has not been read yet."
                    "</tool_use_error>",
                }
            ],
        },
    },
    {
        "type": "user",
        "uuid": "rr2",
        "parentUuid": "rr1",
        "timestamp": "2026-01-01T00:00:03.000Z",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tu8",
                    "is_error": False,
                    "content": [
                        {"type": "text", "text": "widget-one"},
                        {"type": "tool_reference", "name": "Read"},
                        {"type": "text", "text": "widget-two"},
                    ],
                }
            ],
        },
    },
]


def test_claude_tool_result_text_covers_both_content_shapes(tmp_path):
    path = tmp_path / "s9.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in CLAUDE_RESULT_LINES))
    parsed = tr.parse_claude(path, "raw/claude/host/projects/-tmp-proj/s9.jsonl")
    results = [m for m in parsed.messages if m.role == "tool_result"]
    # a plain string is the whole result; a block list keeps only its text blocks
    assert [m.text for m in results] == [
        "<tool_use_error>File has not been read yet.</tool_use_error>",
        "widget-one\nwidget-two",
    ]
    assert [m.results for m in results] == [[("tu9", True)], [("tu8", False)]]


CLAUDE_MIXED_RESULT_LINES = [
    {
        "type": "assistant",
        "uuid": "ma1",
        "parentUuid": None,
        "timestamp": "2026-01-01T00:00:01.000Z",
        "message": {
            "role": "assistant",
            "model": "model-alpha",
            "content": [{"type": "tool_use", "id": "tu7", "name": "Read", "input": {"f": "a"}}],
        },
    },
    {
        "type": "user",
        "uuid": "mr1",
        "parentUuid": "ma1",
        "timestamp": "2026-01-01T00:00:02.000Z",
        "message": {
            "role": "user",
            "content": [
                {"type": "text", "text": "the user typed this alongside the result"},
                {"type": "tool_result", "tool_use_id": "tu7", "content": "widget-one"},
            ],
        },
    },
]


def test_claude_tool_result_keeps_sibling_text_blocks(tmp_path):
    path = tmp_path / "s10.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in CLAUDE_MIXED_RESULT_LINES))
    parsed = tr.parse_claude(path, "raw/claude/host/projects/-tmp-proj/s10.jsonl")
    (result,) = [m for m in parsed.messages if m.role == "tool_result"]
    assert result.text == "the user typed this alongside the result\nwidget-one"


# ------------------------------------------------------------- cache tokens


def _write_lines(path: Path, records) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def test_every_harness_stores_cache_read_and_write_tokens(tmp_path):
    """Every harness reports `input` exclusive of the prompt cache, so the cache
    reads and writes must land in their own columns or processed volume is lost."""
    root = tmp_path / "cache"
    _write_lines(
        root / "raw/claude/host/projects/-tmp-proj/c1.jsonl",
        [
            {
                "type": "assistant",
                "uuid": "ca1",
                "parentUuid": None,
                "timestamp": "2026-01-01T00:00:01.000Z",
                "message": {
                    "role": "assistant",
                    "usage": {
                        "input_tokens": 2,
                        "output_tokens": 3,
                        "cache_read_input_tokens": 500,
                        "cache_creation_input_tokens": 70,
                    },
                    "content": [{"type": "text", "text": "claude reply"}],
                },
            }
        ],
    )
    _write_lines(
        root / "raw/pi/host/default/2026-01-01T00-00-00-000Z_p1.jsonl",
        [
            {"type": "session", "version": 3, "id": "p1", "cwd": "/tmp/proj"},
            {
                "type": "message",
                "id": "pa1",
                "parentId": None,
                "timestamp": "2026-01-01T00:00:01.000Z",
                "message": {
                    "role": "assistant",
                    "usage": {"input": 4, "output": 5, "cacheRead": 600, "cacheWrite": 80},
                    "content": [{"type": "text", "text": "pi reply"}],
                },
            },
        ],
    )
    d = root / "raw/dsh/host/sessions/--tmp-proj--/session-tok"
    d.mkdir(parents=True)
    body = json.loads(json.dumps(DSH_BODY[:4]))
    body[3]["data"]["usage"] = {
        "inputTokens": 6,
        "outputTokens": 7,
        "cacheReadTokens": 700,
        "cacheWriteTokens": 90,
    }
    (d / "session.v3.jsonl.zstd").write_bytes(
        _frame([{**DSH_HEADER, "id": "session-tok", "version": 3}]) + _frame(body)
    )

    errors, conn = _ingested(root)
    assert errors == 0
    assert _rows(
        conn,
        "SELECT harness, input_tokens, output_tokens, cache_read_tokens,"
        " cache_write_tokens FROM messages WHERE role = 'assistant' ORDER BY harness",
    ) == [
        ("claude", 2, 3, 500, 70),
        ("dsh", 6, 7, 700, 90),
        ("pi", 4, 5, 600, 80),
    ]
    conn.close()


def test_cache_tokens_stay_null_when_the_harness_omits_them(cache):
    _, conn = _ingested(cache)
    assert _rows(
        conn,
        "SELECT count(*) FROM messages WHERE role = 'assistant'"
        " AND (cache_read_tokens IS NOT NULL OR cache_write_tokens IS NOT NULL)",
    ) == [(0,)]
    conn.close()


def test_a_v2_database_gains_the_cache_columns_and_reparses(tmp_path):
    """An index from before the cache columns migrates in place, and the parser
    bump re-parses every file so the new columns fill without `--rebuild`."""
    root = tmp_path / "cache"
    root.mkdir()
    conn = sqlite3.connect(root / "transcripts.db")
    conn.execute("PRAGMA journal_mode=WAL")
    for step in tr.MIGRATIONS[:2]:
        for statement in step:
            conn.execute(statement)
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()

    conn = tr.open_db(root)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
    assert {"cache_read_tokens", "cache_write_tokens"} <= cols
    assert tr.PARSER_VERSION > 4  # rows written by version 4 lack the cache columns
    conn.close()


# ------------------------------------------- claude subagents and per-call usage


def _claude_user(uuid: str, text: str) -> dict:
    return {
        "type": "user",
        "uuid": uuid,
        "parentUuid": None,
        "timestamp": "2026-01-01T00:00:01.000Z",
        "cwd": "/tmp/proj",
        "message": {"role": "user", "content": text},
    }


def _claude_block_row(uuid: str, parent: str, msg_id: str, block: dict, usage: dict) -> dict:
    """One row of a multi-block API response: Claude Code writes a row per content
    block, each repeating the response's message.id and usage."""
    return {
        "type": "assistant",
        "uuid": uuid,
        "parentUuid": parent,
        "timestamp": "2026-01-01T00:00:02.000Z",
        "message": {
            "id": msg_id,
            "role": "assistant",
            "model": "model-alpha",
            "usage": usage,
            "content": [block],
        },
    }


def test_a_workflow_agent_nested_under_subagents_is_a_subagent_of_its_session(tmp_path):
    """Workflow agents live at `<session>/subagents/workflows/<run>/agent-<id>.jsonl`,
    two levels below a direct subagent; both belong to the session that owns `subagents/`."""
    root = tmp_path / "cache"
    proj = root / "raw/claude/host/projects/-tmp-proj"
    _write_lines(proj / "sess-1.jsonl", [_claude_user("m1", "main")])
    _write_lines(proj / "sess-1/subagents/agent-d1.jsonl", [_claude_user("d1", "direct")])
    _write_lines(
        proj / "sess-1/subagents/workflows/wf_run1/agent-w1.jsonl",
        [_claude_user("w1", "workflow")],
    )

    errors, conn = _ingested(root)
    assert errors == 0
    assert _rows(
        conn,
        "SELECT native_id, kind, parent_native_id, project_key FROM sessions"
        " WHERE harness = 'claude' ORDER BY native_id",
    ) == [
        ("agent-d1", "subagent", "sess-1", "-tmp-proj"),
        ("agent-w1", "subagent", "sess-1", "-tmp-proj"),
        ("sess-1", "main", None, "-tmp-proj"),
    ]
    conn.close()


def _token_rows(conn, native_id: str):
    return _rows(
        conn,
        "SELECT m.native_id, m.input_tokens, m.output_tokens, m.cache_read_tokens,"
        " m.cache_write_tokens FROM messages m JOIN sessions s ON s.id = m.session_id"
        " WHERE s.native_id = ? AND m.role = 'assistant' ORDER BY m.ord",
        native_id,
    )


def test_streamed_partial_usage_is_counted_once_at_its_final_value(tmp_path):
    """Subagent files carry partial streaming usage on a response's early rows; the
    response must count once, at each field's maximum, not summed and not first-row."""
    root = tmp_path / "cache"
    partial = {"input_tokens": 5, "output_tokens": 1, "cache_read_input_tokens": 100}
    final = {
        "input_tokens": 5,
        "output_tokens": 40,
        "cache_read_input_tokens": 100,
        "cache_creation_input_tokens": 20,
    }
    _write_lines(
        root / "raw/claude/host/projects/-tmp-proj/sess-2/subagents/agent-s1.jsonl",
        [
            _claude_user("u1", "go"),
            _claude_block_row("b1", "u1", "msg_1", {"type": "text", "text": "a"}, partial),
            _claude_block_row(
                "b2", "b1", "msg_1", {"type": "tool_use", "id": "t1", "name": "X", "input": {}},
                partial,
            ),
            _claude_block_row(
                "b3", "b2", "msg_1", {"type": "tool_use", "id": "t2", "name": "Y", "input": {}},
                final,
            ),
        ],
    )

    errors, conn = _ingested(root)
    assert errors == 0
    assert _token_rows(conn, "agent-s1") == [
        ("b1", None, None, None, None),
        ("b2", None, None, None, None),
        ("b3", 5, 40, 100, 20),
    ]
    conn.close()


def test_usage_repeated_across_a_responses_rows_is_counted_once(tmp_path):
    """Main-session files repeat the identical usage on every row of a response, so
    storing it per row would double a SUM over messages."""
    root = tmp_path / "cache"
    usage = {
        "input_tokens": 3,
        "output_tokens": 7,
        "cache_read_input_tokens": 50,
        "cache_creation_input_tokens": 10,
    }
    _write_lines(
        root / "raw/claude/host/projects/-tmp-proj/sess-3.jsonl",
        [
            _claude_user("u1", "go"),
            _claude_block_row("c1", "u1", "msg_2", {"type": "text", "text": "a"}, usage),
            _claude_block_row(
                "c2", "c1", "msg_2", {"type": "tool_use", "id": "t1", "name": "X", "input": {}},
                usage,
            ),
        ],
    )

    errors, conn = _ingested(root)
    assert errors == 0
    assert _token_rows(conn, "sess-3") == [
        ("c1", None, None, None, None),
        ("c2", 3, 7, 50, 10),
    ]
    conn.close()


# ---------------------------------------------------- native-id dedup (aliasing)


DUP_SESSION_LINE = {
    "type": "user",
    "uuid": "dup-session",
    "parentUuid": None,
    "timestamp": "2026-01-01T00:00:01.000Z",
    "cwd": "/tmp/repo",
    "message": {"role": "user", "content": "hello"},
}


def test_duplicate_native_id_across_aliased_project_dirs_keeps_one_session(tmp_path):
    """Two host project dirs can alias the same repo (e.g. a plain `~/dotfiles`
    symlink and `~/.dotted-name`), each holding a byte-identical copy of the same
    session. Ingest must keep exactly one row per (harness, native_id), not one
    per copy."""
    root = tmp_path / "cache"
    body = json.dumps(DUP_SESSION_LINE) + "\n"
    for alias in ("alias-a", "alias-b"):
        d = root / "raw/claude/host/projects" / alias
        d.mkdir(parents=True)
        # session id is the file stem; both files use the same one on purpose
        (d / "dup-session.jsonl").write_text(body)

    errors, conn = _ingested(root)
    assert errors == 0
    rows = _rows(
        conn, "SELECT project_key FROM sessions WHERE native_id = 'dup-session'"
    )
    assert len(rows) == 1  # only one alias's copy survived
    conn.close()


def test_an_already_duplicated_database_heals_on_the_next_ingest(tmp_path):
    """Simulates the pre-fix state: two files already indexed as separate sessions
    under the same native_id, at a stale parser_version. Re-running `ingest` with
    no `--rebuild` must collapse them to one row — bumping PARSER_VERSION is what
    forces the stale duplicate to be re-parsed and caught by the dedup check."""
    root = tmp_path / "cache"
    body = json.dumps(DUP_SESSION_LINE) + "\n"
    paths = {}
    for alias in ("alias-a", "alias-b"):
        d = root / "raw/claude/host/projects" / alias
        d.mkdir(parents=True)
        p = d / "dup-session.jsonl"
        p.write_text(body)
        paths[alias] = p

    conn = tr.open_db(root)
    for alias, p in paths.items():
        st = p.stat()
        cur = conn.execute(
            "INSERT INTO files (harness, relpath, size, mtime, parser_version,"
            " status, parsed_at) VALUES ('claude', ?, ?, ?, ?, 'ok', '')",
            (
                p.relative_to(root).as_posix(),
                st.st_size,
                int(st.st_mtime),
                tr.PARSER_VERSION - 1,  # stale: forces a re-parse on next ingest
            ),
        )
        conn.execute(
            "INSERT INTO sessions (harness, native_id, file_id, kind)"
            " VALUES ('claude', 'dup-session', ?, 'main')",
            (cur.lastrowid,),
        )
    conn.commit()
    assert conn.execute(
        "SELECT count(*) FROM sessions WHERE native_id = 'dup-session'"
    ).fetchone()[0] == 2  # the fabricated pre-fix duplicated state
    conn.close()

    tr.ingest(root, rebuild=False)

    conn = tr.open_db(root)
    assert conn.execute(
        "SELECT count(*) FROM sessions WHERE native_id = 'dup-session'"
    ).fetchone()[0] == 1
    conn.close()


def test_a_native_id_collision_between_different_content_keeps_both_sessions(tmp_path):
    """A subagent tool can give its own log a generic filename (e.g. a workflow's
    journal.jsonl), which becomes that file's native_id too — so unrelated
    workflow runs collide on the SAME native_id despite being genuinely
    different content. Deduping on native_id alone would silently drop one of
    them; the content check must tell this apart from a true alias duplicate."""
    root = tmp_path / "cache"
    for alias, text in (("wf-a", "hello from workflow A"), ("wf-b", "a different workflow entirely")):
        d = root / "raw/claude/host/projects" / alias
        d.mkdir(parents=True)
        line = {
            "type": "user",
            "uuid": "journal",  # same filename -> same native_id in both
            "parentUuid": None,
            "timestamp": "2026-01-01T00:00:01.000Z",
            "cwd": "/tmp/repo",
            "message": {"role": "user", "content": text},
        }
        (d / "journal.jsonl").write_text(json.dumps(line) + "\n")

    errors, conn = _ingested(root)
    assert errors == 0
    rows = _rows(
        conn,
        "SELECT s.project_key, m.text FROM sessions s JOIN messages m"
        " ON m.session_id = s.id WHERE s.native_id = 'journal' ORDER BY s.project_key",
    )
    # both survive — neither is silently treated as a duplicate of the other
    assert rows == [
        ("wf-a", "hello from workflow A"),
        ("wf-b", "a different workflow entirely"),
    ]
    conn.close()


# ------------------------------------------------------------------ general


def test_ingest_is_incremental_and_rebuildable(cache, capsys):
    assert tr.ingest(cache, rebuild=False) == 1
    assert "parsed=5 unchanged=0 errors=1" in capsys.readouterr().out
    conn = tr.open_db(cache)
    before = _rows(
        conn,
        "SELECT (SELECT count(*) FROM sessions), (SELECT count(*) FROM messages),"
        " (SELECT count(*) FROM tool_calls), (SELECT count(*) FROM files)",
    )
    conn.close()

    tr.ingest(cache, rebuild=False)
    assert "parsed=0 unchanged=6 errors=0" in capsys.readouterr().out

    touched = cache / "raw/claude/host/projects/-tmp-proj/s1.jsonl"
    os.utime(touched, (1800000000, 1800000000))
    tr.ingest(cache, rebuild=False)
    assert "parsed=1 unchanged=5 errors=0" in capsys.readouterr().out

    tr.ingest(cache, rebuild=True)
    assert "parsed=5 unchanged=0 errors=1" in capsys.readouterr().out
    conn = tr.open_db(cache)
    after = _rows(
        conn,
        "SELECT (SELECT count(*) FROM sessions), (SELECT count(*) FROM messages),"
        " (SELECT count(*) FROM tool_calls), (SELECT count(*) FROM files)",
    )
    assert after == before == [(5, 18, 3, 6)]


def test_fts_finds_a_message_by_a_word_in_its_text(cache):
    _, conn = _ingested(cache)
    hits = _rows(
        conn,
        "SELECT m.native_id FROM messages_fts f JOIN messages m ON m.id = f.rowid"
        " JOIN sessions s ON s.id = m.session_id"
        " WHERE messages_fts MATCH 'shelf' AND s.harness = 'claude'"
        " ORDER BY m.native_id",
    )
    assert hits == [("sa1",), ("su1",)]

    # a re-parse must not leave the index stale
    tr.ingest(cache, rebuild=True)
    conn = tr.open_db(cache)
    assert _rows(
        conn,
        "SELECT count(*) FROM messages_fts WHERE messages_fts MATCH 'shelf'",
    ) == [(4,)]


def test_stats_table_counts_every_harness(cache):
    _, conn = _ingested(cache)
    table = tr.stats(conn)
    lines = [line.split() for line in table.splitlines()]
    assert lines[0] == [
        "harness",
        "files",
        "ok",
        "error",
        "sessions",
        "messages",
        "tool_calls",
    ]
    assert lines[1] == ["claude", "2", "2", "0", "2", "8", "1"]
    assert lines[2] == ["pi", "2", "1", "1", "1", "5", "1"]
    assert lines[3] == ["dsh", "2", "2", "0", "2", "5", "1"]
    assert lines[4] == ["total", "6", "5", "1", "5", "18", "3"]


def test_json_lines_splits_on_newline_only_and_drops_a_torn_tail(tmp_path):
    # U+2028 inside a JSON string is not a record boundary; a NUL-padded final
    # line is a crash-torn write and must not fail the whole file.
    good = '{"type": "user", "note": "line separator inside"}'
    path = tmp_path / "s.jsonl"
    path.write_text(good + "\n" + good + "\n" + "\x00" * 16, encoding="utf-8")
    lines = tr._json_lines(path)
    assert lines == [good, good]
