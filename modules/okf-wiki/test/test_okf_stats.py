import json
import sqlite3

from okf_testlib import concept, git, run

SCHEMA = """
CREATE TABLE sessions (id INTEGER PRIMARY KEY, harness TEXT, native_id TEXT, file_id INTEGER,
  cwd TEXT, project_key TEXT, kind TEXT, parent_native_id TEXT, started_at TEXT, ended_at TEXT,
  model TEXT, title TEXT);
CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id INTEGER, ord INTEGER, native_id TEXT,
  parent_native_id TEXT, on_main_path INTEGER, role TEXT, ts TEXT, text TEXT, model TEXT,
  stop_reason TEXT, input_tokens INTEGER, output_tokens INTEGER, raw TEXT, injected INTEGER,
  norm_key TEXT, harness TEXT);
CREATE TABLE tool_calls (id INTEGER PRIMARY KEY, message_id INTEGER, call_id TEXT, name TEXT,
  arguments TEXT, result_message_id INTEGER, is_error INTEGER, harness TEXT);
CREATE VIRTUAL TABLE messages_fts USING fts5(text, content='messages', content_rowid='id');
CREATE TRIGGER messages_fts_ai AFTER INSERT ON messages BEGIN
  INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text); END;
"""


def make_db(tmp_path, repo):
    d = tmp_path / "transcripts"
    d.mkdir()
    conn = sqlite3.connect(d / "transcripts.db")
    conn.executescript(SCHEMA)
    rows = [(1, str(repo)), (2, str(repo / "sub")), (3, "/elsewhere")]
    for sid, cwd in rows:
        conn.execute("INSERT INTO sessions (id, harness, native_id, file_id, cwd, kind, started_at) "
                     "VALUES (?, 'claude', ?, 1, ?, 'main', '2999-01-01T00:00:00Z')", (sid, str(sid), cwd))
    msgs = [
        (1, "user", "okf-wiki:digest v1 · .wiki/ · 1 concepts"),
        (1, "assistant", "Per concept:pnpm-peer-trap the fix is X. wiki: +gotcha/new-one"),
        (2, "user", "okf-wiki:digest v1 · .wiki/ · 1 concepts"),
        (2, "assistant", "GAP: nothing on caching"),
        (3, "assistant", "concept:pnpm-peer-trap elsewhere, must not count"),
    ]
    for i, (sid, role, text) in enumerate(msgs, 1):
        conn.execute("INSERT INTO messages (id, session_id, ord, on_main_path, role, text, raw, injected) "
                     "VALUES (?, ?, ?, 1, ?, ?, '{}', 0)", (i, sid, i, role, text))
    conn.execute("INSERT INTO tool_calls (message_id, call_id, name, arguments) VALUES (4, 'c1', 'Read', ?)",
                 (json.dumps({"file_path": str(repo / ".wiki/x.md")}),))
    conn.commit()
    conn.close()


def test_stats_counts_markers_only_for_this_repo(repo, tmp_path):
    concept(repo, "pnpm-peer-trap")
    concept(repo, "unused")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "wiki")
    make_db(tmp_path, repo)
    r = run(repo, "stats")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout.rsplit("\n", 2)[0])
    t = data["transcripts"]
    assert t["sessions"] == 2 and t["digest_sessions"] == 2
    assert t["consulted_sessions"] == 2
    assert t["cited"] == {"pnpm-peer-trap": 1}
    assert t["gaps"] == 1
    assert t["receipts"] == {"created_or_updated": 1, "healed": 0, "failed": 0}
    assert data["never_cited"] == ["unused"]
    assert data["git"]["added"] == ["pnpm-peer-trap", "unused"]


def test_stats_without_a_transcript_index_says_why(repo):
    concept(repo, "a")
    data = json.loads(run(repo, "stats").stdout.rsplit("\n", 2)[0])
    assert data["transcripts"]["available"] is False
    assert "agent-transcripts ingest" in data["transcripts"]["reason"]
    assert data["never_cited"] is None
