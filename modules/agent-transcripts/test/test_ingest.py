import json
import os
import shutil
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
