import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "skills/transcript-ingest"),
)
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "skills/transcript-sweep"),
)
import sweep as sw  # noqa: E402
import transcripts as tr  # noqa: E402


class Index:
    """A synthetic index on the real schema, so schema drift fails these tests."""

    def __init__(self, root: Path, parser_version: int | None = None):
        self.conn = sqlite3.connect(root / "transcripts.db")
        self.conn.executescript(tr.SCHEMA)
        self.conn.execute(
            "INSERT INTO files (id, harness, relpath, size, mtime, parser_version,"
            " status, parsed_at) VALUES (1, 'claude', 'a.jsonl', 1, 1, ?, 'ok', 'now')",
            (tr.PARSER_VERSION if parser_version is None else parser_version,),
        )
        self.root = root
        self.ord = 0

    def session(self, native_id, harness="claude", started_at="2026-06-01T00:00:00Z"):
        cur = self.conn.execute(
            "INSERT INTO sessions (harness, native_id, file_id, cwd, project_key, kind,"
            " started_at) VALUES (?, ?, 1, '/w', 'w', 'main', ?)",
            (harness, native_id, started_at),
        )
        return cur.lastrowid

    def _message(self, session_id, role, text):
        self.ord += 1
        cur = self.conn.execute(
            "INSERT INTO messages (session_id, ord, on_main_path, role, text, raw)"
            " VALUES (?, ?, 1, ?, ?, '{}')",
            (session_id, self.ord, role, text),
        )
        return cur.lastrowid

    def call(self, session_id, name, arguments, is_error=0, result=""):
        message_id = self._message(session_id, "assistant", "")
        result_id = self._message(session_id, "tool_result", result)
        self.conn.execute(
            "INSERT INTO tool_calls (message_id, call_id, name, arguments,"
            " result_message_id, is_error) VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, f"c{message_id}", name, arguments, result_id, is_error),
        )

    def close(self):
        if self.conn is not None:  # tests close explicitly; the fixture closes again
            self.conn.commit()
            self.conn.close()
            self.conn = None


@pytest.fixture
def index(tmp_path):
    ix = Index(tmp_path)
    yield ix
    ix.close()


def run(tmp_path, *extra):
    """The JSONL path, with the findings store off: the store has its own tests below."""
    out = tmp_path / "sweep.jsonl"
    code = sw.main(["--dest", str(tmp_path), "--out", str(out), "--no-db", *extra])
    assert code == 0
    return [json.loads(line) for line in out.read_text().splitlines()]


def of_kind(records, kind):
    return [r for r in records if r["kind"] == kind]


def test_tool_error_counts_and_classifies_signatures(index, tmp_path):
    s = index.session("s1")
    index.call(s, "Bash", '{"command": "a"}', is_error=1, result="bash: permission denied")
    index.call(s, "Edit", '{"path": "b"}', is_error=1, result="old_string not found in file")
    index.call(s, "Read", '{"path": "c"}', is_error=1, result="No such file or directory")
    index.call(s, "Bash", '{"command": "d"}', is_error=1, result="command exited with code 3")
    index.call(s, "Bash", '{"command": "e"}', is_error=1, result="something else entirely")
    index.call(s, "Read", '{"path": "f"}', result="fine")
    index.close()

    (rec,) = of_kind(run(tmp_path), "tool_error")
    assert rec["severity"] == "issue"
    assert rec["count"] == 5
    assert rec["detail"]["signatures"] == {
        "permission_denied": 1,
        "edit_anchor_miss": 1,
        "file_not_found": 1,
        "nonzero_exit": 1,
        "other": 1,
    }
    assert rec["native_id"] == "s1" and rec["harness"] == "claude"


def test_error_streak_needs_three_consecutive(index, tmp_path):
    s = index.session("s1")
    for i in range(2):  # a two-long run is not a streak
        index.call(s, "Bash", '{"command": "x%d"}' % i, is_error=1, result="boom")
    index.call(s, "Bash", '{"command": "ok"}', result="fine")
    for i in range(4):
        index.call(s, "Bash", '{"command": "y%d"}' % i, is_error=1, result="boom")
    index.close()

    (rec,) = of_kind(run(tmp_path), "error_streak")
    assert rec["count"] == 1
    assert rec["detail"] == {"streaks": 1, "max_len": 4}


def test_retry_same_input_after_error(index, tmp_path):
    s = index.session("s1")
    index.call(s, "Bash", '{"command": "flaky"}', is_error=1, result="boom")
    index.call(s, "Read", '{"path": "notes"}', result="fine")
    index.call(s, "Bash", '{"command": "flaky"}', result="fine")  # retry, within the window
    index.call(s, "Bash", '{"command": "other"}', is_error=1, result="boom")
    for i in range(3):  # pushes the failure out of the window before it repeats
        index.call(s, "Read", '{"path": "p%d"}' % i, result="fine")
    index.call(s, "Bash", '{"command": "other"}', result="fine")
    index.close()

    (rec,) = of_kind(run(tmp_path), "retry_same_input_after_error")
    assert rec["count"] == 1
    assert rec["detail"]["names"] == {"Bash": 1}


def test_retry_window_boundary_is_two_calls(index, tmp_path):
    s = index.session("s1")
    index.call(s, "Bash", '{"command": "near"}', is_error=1, result="boom")
    index.call(s, "Read", '{"path": "n0"}', result="fine")
    index.call(s, "Bash", '{"command": "near"}', result="fine")  # 2 calls after: inside
    index.close()

    (rec,) = of_kind(run(tmp_path), "retry_same_input_after_error")
    assert rec["count"] == 1


def test_retry_window_excludes_three_calls_later(index, tmp_path):
    s = index.session("s1")
    index.call(s, "Bash", '{"command": "far"}', is_error=1, result="boom")
    for i in range(2):
        index.call(s, "Read", '{"path": "f%d"}' % i, result="fine")
    index.call(s, "Bash", '{"command": "far"}', result="fine")  # 3 calls after: outside
    index.close()

    assert of_kind(run(tmp_path), "retry_same_input_after_error") == []


def test_error_streaks_do_not_span_sessions(index, tmp_path):
    for n in range(3):  # each session ends and starts on an error: a streak only if concatenated
        s = index.session("s%d" % n)
        index.call(s, "Bash", '{"command": "a%d"}' % n, is_error=1, result="boom")
        index.call(s, "Read", '{"path": "ok%d"}' % n, result="fine")
        index.call(s, "Bash", '{"command": "z%d"}' % n, is_error=1, result="boom")
    index.close()

    assert of_kind(run(tmp_path), "error_streak") == []


def test_duplicate_call_ignores_key_order(index, tmp_path):
    s = index.session("s1")
    index.call(s, "Read", '{"path": "a", "offset": 1}', result="fine")
    index.call(s, "Read", '{"offset": 1, "path": "a"}', result="fine")
    index.call(s, "Read", '{"path": "b"}', result="fine")
    index.close()

    (rec,) = of_kind(run(tmp_path), "duplicate_call")
    assert rec["severity"] == "potential"
    assert rec["count"] == 1  # one redundant repeat
    assert rec["detail"] == {"groups": 1, "max_repeat": 2}


def test_bash_substitute_only_fires_on_a_whole_command(index, tmp_path):
    s = index.session("s1")
    for command in ("cat foo", "cd /x && cat foo | head", "cat a && ls b", "grep x | sort"):
        index.call(s, "Bash", json.dumps({"command": command}), result="fine")
    index.close()

    (rec,) = of_kind(run(tmp_path), "bash_substitute")
    assert rec["count"] == 2
    assert [e["snippet"] for e in rec["evidence"]] == ["cat foo", "cd /x && cat foo | head"]


def test_bash_substitute_rule_by_command():
    flagged = [
        "cat foo",
        "  head -50 foo  ",
        "cd /x && cat foo | head",
        "grep -rn needle src | wc -l",
        "sed -n 1,20p file",
        "ls -la",
    ]
    not_flagged = [
        "cat a && ls b",
        "grep x | sort",
        "cat foo > bar",
        "cat $(ls)",
        "python -c 'print(1)'",
        "sed -i s/a/b/ file",
        "cat a; cat b",
    ]
    assert [c for c in flagged if not sw.is_bash_substitute(c)] == []
    assert [c for c in not_flagged if sw.is_bash_substitute(c)] == []


def test_long_result(index, tmp_path):
    s = index.session("s1")
    index.call(s, "Read", '{"path": "big"}', result="x" * 300)
    index.call(s, "Read", '{"path": "small"}', result="x" * 50)
    index.close()

    (rec,) = of_kind(run(tmp_path, "--long-result", "100"), "long_result")
    assert rec["count"] == 1
    assert rec["detail"] == {"threshold": 100, "max_length": 300}
    assert len(rec["evidence"][0]["snippet"]) == 200  # the snippet cap, not the result


def test_long_session(index, tmp_path):
    s = index.session("s1")
    for i in range(4):
        index.call(s, "Read", '{"path": "p%d"}' % i, result="fine")
    index.close()

    records = run(tmp_path, "--long-session", "3")
    (rec,) = of_kind(records, "long_session")
    assert rec["count"] == 1  # one flag, not one per call: the grid and ranking must not skew
    assert rec["detail"] == {"threshold": 3, "tool_calls": 4}
    assert of_kind(run(tmp_path, "--long-session", "4"), "long_session") == []


def test_stale_parser_version_refuses_with_exit_2(tmp_path, capsys):
    ix = Index(tmp_path, parser_version=tr.PARSER_VERSION - 1)
    s = ix.session("s1")
    ix.call(s, "Bash", '{"command": "x"}', is_error=1, result="boom")
    ix.close()

    out = tmp_path / "sweep.jsonl"
    assert sw.main(["--dest", str(tmp_path), "--out", str(out)]) == 2
    assert "transcript-ingest" in capsys.readouterr().err
    assert not out.exists()


def test_partially_reingested_index_refuses_with_exit_2(tmp_path, capsys):
    ix = Index(tmp_path, parser_version=tr.PARSER_VERSION - 1)
    ix.conn.execute(
        "INSERT INTO files (id, harness, relpath, size, mtime, parser_version,"
        " status, parsed_at) VALUES (2, 'claude', 'b.jsonl', 1, 1, ?, 'ok', 'now')",
        (tr.PARSER_VERSION,),
    )
    s = ix.session("s1")
    ix.call(s, "Bash", '{"command": "x"}', is_error=1, result="boom")
    ix.close()

    out = tmp_path / "sweep.jsonl"
    assert sw.main(["--dest", str(tmp_path), "--out", str(out)]) == 2
    assert "transcript-ingest" in capsys.readouterr().err
    assert not out.exists()


def test_missing_index_is_a_clear_error(tmp_path):
    with pytest.raises(SystemExit) as e:
        sw.connect(tmp_path)
    assert "transcript-ingest" in str(e.value)


def test_since_and_harness_filters(index, tmp_path):
    old = index.session("old", started_at="2026-01-01T00:00:00Z")
    new = index.session("new", started_at="2026-08-01T00:00:00Z")
    pi = index.session("pi1", harness="pi", started_at="2026-08-02T00:00:00Z")
    for s in (old, new, pi):
        index.call(s, "Bash", '{"command": "x"}', is_error=1, result="boom")
    index.close()

    assert {r["native_id"] for r in run(tmp_path, "--since", "2026-03-01")} == {"new", "pi1"}
    assert {r["native_id"] for r in run(tmp_path, "--harness", "pi")} == {"pi1"}
    assert {r["native_id"] for r in run(tmp_path, "--session", "old")} == {"old"}


def test_evidence_is_capped_at_three(index, tmp_path):
    s = index.session("s1")
    for i in range(5):
        index.call(s, "Bash", '{"command": "x%d"}' % i, is_error=1, result="boom")
    index.close()

    (rec,) = of_kind(run(tmp_path), "tool_error")
    assert rec["count"] == 5
    assert len(rec["evidence"]) == 3
    assert set(rec["evidence"][0]) == {"tool_call_id", "message_id", "name", "snippet"}


def sweep_into_store(tmp_path, *extra):
    assert sw.main(["--dest", str(tmp_path), *extra]) == 0
    conn = sqlite3.connect(tmp_path / "findings.db")
    try:
        rows = conn.execute(
            "SELECT harness, native_id, kind, count FROM sweep_flags ORDER BY native_id, kind"
        ).fetchall()
        runs = conn.execute("SELECT skill, model, args FROM runs ORDER BY id").fetchall()
    finally:
        conn.close()
    return rows, runs


def test_sweep_writes_findings_db_without_a_jsonl(index, tmp_path):
    s = index.session("s1")
    for i in range(3):
        index.call(s, "Bash", '{"command": "x%d"}' % i, is_error=1, result="boom")
    index.close()

    rows, runs = sweep_into_store(tmp_path)
    assert ("claude", "s1", "tool_error", 3) in rows
    assert ("claude", "s1", "error_streak", 1) in rows
    assert runs == [("transcript-sweep", None, json.dumps(["--dest", str(tmp_path)]))]
    assert not (tmp_path / "sweeps").exists()  # no --out, no JSONL anywhere


def test_a_crash_mid_sweep_leaves_the_stored_flags_alone(index, tmp_path, monkeypatch):
    s = index.session("s1")
    for i in range(3):
        index.call(s, "Bash", '{"command": "x%d"}' % i, is_error=1, result="boom")
    index.close()

    rows, _ = sweep_into_store(tmp_path)
    assert len(rows) == 2  # tool_error + error_streak

    def killed(*_args, **_kwargs):
        raise RuntimeError("killed mid-sweep")

    monkeypatch.setattr(sw, "emit", killed)
    with pytest.raises(RuntimeError):
        sw.main(["--dest", str(tmp_path)])

    conn = sqlite3.connect(tmp_path / "findings.db")
    try:  # a crashed run may leave the store stale; it must never leave it empty
        assert conn.execute("SELECT count(*) FROM sweep_flags").fetchone()[0] == 2
    finally:
        conn.close()


def test_resweep_replaces_flags_and_clears_a_now_clean_session(index, tmp_path):
    keeps = index.session("keeps")
    clears = index.session("clears")
    for s in (keeps, clears):
        for i in range(3):
            index.call(s, "Bash", '{"command": "%d-%d"}' % (s, i), is_error=1, result="boom")
    index.close()

    rows, _ = sweep_into_store(tmp_path)
    assert {r[1] for r in rows} == {"keeps", "clears"}

    fix = sqlite3.connect(tmp_path / "transcripts.db")  # the session stops failing
    fix.execute(
        "UPDATE tool_calls SET is_error = 0 WHERE message_id IN"
        " (SELECT id FROM messages WHERE session_id = ?)",
        (clears,),
    )
    fix.commit()
    fix.close()

    rows, runs = sweep_into_store(tmp_path)
    assert {r[1] for r in rows} == {"keeps"}  # stale flags retired, not left behind
    assert [r[2] for r in rows if r[1] == "keeps"] == ["error_streak", "tool_error"]
    assert len(runs) == 2  # one run row per invocation
