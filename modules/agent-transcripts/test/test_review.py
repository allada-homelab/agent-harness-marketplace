import json
import sqlite3
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MODULE / "skills/transcript-ingest"))
sys.path.insert(0, str(MODULE / "skills/transcript-sweep"))
sys.path.insert(0, str(MODULE / "skills/transcript-review"))
import findings as fi  # noqa: E402
import review as rv  # noqa: E402
import transcripts as tr  # noqa: E402


class Index:
    """A synthetic index on the real schema, so schema drift fails these tests."""

    def __init__(self, root: Path):
        self.conn = sqlite3.connect(root / "transcripts.db")
        self.conn.executescript(tr.SCHEMA)
        self.conn.execute(
            "INSERT INTO files (id, harness, relpath, size, mtime, parser_version,"
            " status, parsed_at) VALUES (1, 'claude', 'a.jsonl', 1, 1, ?, 'ok', 'now')",
            (tr.PARSER_VERSION,),
        )
        self.root = root
        self.ords: dict[int, int] = {}

    def session(self, native_id, harness="claude", started_at="2026-06-01T00:00:00Z",
                kind="main", project_key="w"):
        cur = self.conn.execute(
            "INSERT INTO sessions (harness, native_id, file_id, cwd, project_key, kind,"
            " started_at, model) VALUES (?, ?, 1, '/w', ?, ?, ?, 'test-model')",
            (harness, native_id, project_key, kind, started_at),
        )
        self.ords[cur.lastrowid] = 0
        return cur.lastrowid

    def _message(self, session_id, role, text):
        self.ords[session_id] += 1
        cur = self.conn.execute(
            "INSERT INTO messages (session_id, ord, on_main_path, role, text, raw)"
            " VALUES (?, ?, 1, ?, ?, '{}')",
            (session_id, self.ords[session_id], role, text),
        )
        return cur.lastrowid, self.ords[session_id]

    def user(self, session_id, text):
        return self._message(session_id, "user", text)[1]

    def assistant(self, session_id, text):
        return self._message(session_id, "assistant", text)[1]

    def call(self, session_id, name, arguments, is_error=0, result="", text=""):
        message_id, ord_ = self._message(session_id, "assistant", text)
        result_id, _ = self._message(session_id, "tool_result", result)
        self.conn.execute(
            "INSERT INTO tool_calls (message_id, call_id, name, arguments,"
            " result_message_id, is_error) VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, f"c{message_id}", name, arguments, result_id, is_error),
        )
        return ord_

    def close(self):
        if self.conn is not None:
            self.conn.commit()
            self.conn.close()
            self.conn = None


@pytest.fixture
def index(tmp_path):
    ix = Index(tmp_path)
    yield ix
    ix.close()


@pytest.fixture
def store(tmp_path):
    conn = fi.open_findings(tmp_path)
    run_id = fi.start_run(conn, "transcript-sweep", None, "{}")
    yield conn, run_id
    conn.commit()
    conn.close()


def sweep_flag(store, harness, native_id, kind="tool_error", severity="issue", count=1,
               evidence=None):
    conn, run_id = store
    conn.execute(
        "INSERT INTO sweep_flags (run_id, harness, native_id, kind, severity, count, detail,"
        " evidence) VALUES (?, ?, ?, ?, ?, ?, '{}', ?)",
        (run_id, harness, native_id, kind, severity, count,
         json.dumps(evidence or [])),
    )
    conn.commit()


def queue(tmp_path, capsys, *extra):
    assert rv.main(["--dest", str(tmp_path), "queue", "--json", *extra]) == 0
    out = capsys.readouterr().out.splitlines()
    return [json.loads(line) for line in out if line.strip()]


def view(tmp_path, capsys, session, *extra):
    assert rv.main(["--dest", str(tmp_path), "view", session, *extra]) == 0
    return capsys.readouterr().out


def verdict(**overrides):
    """A complete verdict: every category answered, negative unless overridden."""
    findings = []
    for category in rv.CATEGORIES:
        entry = {"category": category, "present": 0, "confidence": "low",
                 "evidence_ord": None, "quote": None, "note": ""}
        entry.update(overrides.get(category, {}))
        findings.append(entry)
    return {"findings": findings}


def record(tmp_path, session, payload, *extra, run_id=None):
    path = tmp_path / "verdict.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    argv = ["--dest", str(tmp_path), "record", session, "--file", str(path), *extra]
    if run_id is not None:
        argv += ["--run-id", str(run_id)]
    return rv.main(argv)


# ---------------------------------------------------------------------- queue


def test_queue_fires_on_issue_threshold(index, store, tmp_path, capsys):
    hot = index.session("hot")
    index.call(hot, "Bash", '{"command": "x"}', is_error=1, result="boom")
    cool = index.session("cool")
    index.call(cool, "Bash", '{"command": "y"}', result="fine")
    index.close()
    sweep_flag(store, "claude", "hot", count=9)
    sweep_flag(store, "claude", "cool", count=2)

    rows = queue(tmp_path, capsys, "--sample", "0")
    assert [r["native_id"] for r in rows] == ["hot"]
    assert "issues=9" in rows[0]["why"]
    assert rows[0]["messages"] == 2
    assert queue(tmp_path, capsys, "--sample", "0", "--issue-threshold", "20") == []


def test_queue_fires_when_the_last_message_is_the_user(index, store, tmp_path, capsys):
    hanging = index.session("hanging")
    index.user(hanging, "please fix the build")
    answered = index.session("answered")
    index.user(answered, "please fix the build")
    index.assistant(answered, "done")
    index.close()

    rows = queue(tmp_path, capsys, "--sample", "0")
    assert [r["native_id"] for r in rows] == ["hanging"]
    assert rows[0]["why"] == "ends-on-user"


def test_queue_ignores_a_trailing_injected_block(index, store, tmp_path, capsys):
    injected = index.session("injected")
    index.user(injected, "fix the build")
    index.assistant(injected, "done")
    index.user(injected, "<system-reminder>\nbackground task finished\n</system-reminder>")
    hanging = index.session("hanging")
    index.user(hanging, "fix the build")
    index.close()

    rows = queue(tmp_path, capsys, "--sample", "0")
    assert [r["native_id"] for r in rows] == ["hanging"]


def test_queue_fires_on_a_short_correction_under_boilerplate(index, store, tmp_path, capsys):
    s = index.session("corrected")
    index.user(s, "<system-reminder>\nsome injected thing\n</system-reminder>\nno, stop doing that")
    index.assistant(s, "sorry")
    long_one = index.session("long")
    index.user(long_one, "do not stop until it is done. " + "context " * 100)
    index.assistant(long_one, "ok")
    index.close()

    rows = queue(tmp_path, capsys, "--sample", "0")
    assert [r["native_id"] for r in rows] == ["corrected"]
    assert rows[0]["why"] == "correction"
    assert rows[0]["correction"] == "no, stop doing that"


def test_queue_sample_is_deterministic_and_seeded(index, store, tmp_path, capsys):
    for n in range(40):
        s = index.session("s%02d" % n)
        index.assistant(s, "hello")
    index.close()

    first = {r["native_id"] for r in queue(tmp_path, capsys, "--sample", "0.25", "--seed", "7")}
    again = {r["native_id"] for r in queue(tmp_path, capsys, "--sample", "0.25", "--seed", "7")}
    other = {r["native_id"] for r in queue(tmp_path, capsys, "--sample", "0.25", "--seed", "8")}
    assert first == again
    assert 0 < len(first) < 40
    assert first != other
    assert all(r["why"] == "sample" for r in queue(tmp_path, capsys, "--sample", "1.0"))


def test_queue_unreviewed_excludes_recorded_sessions(index, store, tmp_path, capsys):
    for name in ("done", "todo"):
        s = index.session(name)
        index.user(s, "look at this")
    index.close()
    conn, run_id = store
    conn.execute(
        "INSERT INTO review_flags (run_id, harness, native_id, category, present, confidence,"
        " created_at) VALUES (?, 'claude', 'done', 'tool_misuse', 0, 'low', 'now')",
        (run_id,),
    )
    conn.commit()

    assert {r["native_id"] for r in queue(tmp_path, capsys, "--sample", "0")} == {"done", "todo"}
    assert [r["native_id"] for r in queue(tmp_path, capsys, "--sample", "0", "--unreviewed")] == [
        "todo"
    ]


def test_queue_skips_subagent_sessions(index, store, tmp_path, capsys):
    main = index.session("main1")
    index.user(main, "no, wrong")
    sub = index.session("sub1", kind="subagent")
    index.user(sub, "no, wrong")
    index.close()

    rows = queue(tmp_path, capsys, "--sample", "0")
    assert [r["native_id"] for r in rows] == ["main1"]


def test_queue_warns_and_keeps_going_without_a_findings_store(index, tmp_path, capsys):
    s = index.session("lonely")
    index.user(s, "no, wrong")
    index.close()

    assert rv.main(["--dest", str(tmp_path), "queue", "--json", "--sample", "0"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["native_id"] == "lonely"
    assert "no findings.db" in captured.err


# ----------------------------------------------------------------------- view


def test_view_strips_boilerplate_and_keeps_the_human_text(index, store, tmp_path, capsys):
    s = index.session("v1")
    index.user(s, "<system-reminder>\nnoise the harness injected\n</system-reminder>\nwhy is CI red?")
    index.assistant(s, "looking")
    index.close()
    sweep_flag(store, "claude", "v1", kind="tool_error", count=3)

    out = view(tmp_path, capsys, "v1")
    assert "why is CI red?" in out
    assert "noise the harness injected" not in out
    assert "[stripped: system-reminder]" in out
    assert "[1] USER" in out and "[2] ASSISTANT looking" in out
    assert "tool_error=3(issue)" in out
    assert "1 stripped blocks" in out


def test_view_strips_the_dsh_and_claude_shapes(index, tmp_path):
    claude = (
        "<task-notification>\n<task-id>x</task-id>\n</task-notification>\n"
        "Stop hook feedback:\nrun the wiki loop"
    )
    clean, n = rv.strip_boilerplate(claude, "claude")
    assert n == 2 and "wiki loop" not in clean and "task-id" not in clean

    dsh = "Current runtime context. This snapshot supersedes earlier runtime-context snapshots."
    clean, n = rv.strip_boilerplate(dsh, "dsh")
    assert n == 1 and clean.strip() == "[stripped: runtime-context]"
    # scoped: a dsh-only shape is left alone on claude
    assert rv.strip_boilerplate(dsh, "claude")[1] == 0


def test_view_collapses_repeated_calls_and_marks_errors(index, tmp_path, capsys):
    s = index.session("v2")
    index.user(s, "retry it")
    for _ in range(4):
        index.call(s, "Bash", '{"command": "flaky"}', is_error=1, result="boom")
    index.call(s, "Read", '{"path": "notes"}', result="fine")
    index.close()

    out = view(tmp_path, capsys, "v2")
    assert out.count("CALL Bash") == 1
    assert "×4" in out
    assert "ERR ×4" in out
    assert "CALL Read" in out and "RESULT fine" in out


def test_view_does_not_collapse_calls_whose_results_differ(index, tmp_path, capsys):
    s = index.session("v2b")
    index.user(s, "try the socket")
    for result in ("connection refused", "connection refused", "no route to host"):
        index.call(s, "Bash", '{"command": "curl svc"}', is_error=1, result=result)
    index.close()

    out = view(tmp_path, capsys, "v2b")
    assert "×3" not in out          # the third call failed differently
    assert "×2" in out              # the two identical ones still fold
    assert out.count("CALL Bash") == 2
    assert "no route to host" in out


def test_view_caps_a_pasted_log_and_indents_its_lines(index, tmp_path, capsys):
    s = index.session("v4")
    paste = "\n".join("line %d of the paste" % i for i in range(600))
    index.user(s, "here is the log:\n" + paste)
    index.assistant(s, "read it")
    index.close()

    out = view(tmp_path, capsys, "v4", "--budget", "4000")
    body = out.split("\n\n")[1]
    assert len(body) < 4000                      # --budget is a bound now, not a suggestion
    assert "[1] USER here is the log:" in out    # the opening ask is still whole
    assert "\n    line 0 of the paste" in out    # continuation lines are indented
    assert "…[+" in out                          # and the cut is announced
    assert "line 599 of the paste" not in out


def test_view_keeps_a_window_around_the_sweep_evidence(index, store, tmp_path, capsys):
    s = index.session("v5")
    index.user(s, "run the suite")
    for i in range(80):
        index.call(s, "Read", '{"path": "p%d"}' % i, result="head %d" % i)
    bad = index.call(s, "Bash", '{"command": "pytest -q"}', is_error=1,
                     result="ImportError: no module named acme")
    for i in range(80):
        index.call(s, "Read", '{"path": "q%d"}' % i, result="tail %d" % i)
    index.assistant(s, "LAST line of the session")
    (message_id,) = index.conn.execute(
        "SELECT id FROM messages WHERE session_id = ? AND ord = ?", (s, bad)
    ).fetchone()
    index.close()
    sweep_flag(store, "claude", "v5", kind="tool_error", count=1,
               evidence=[{"message_id": message_id, "name": "Bash", "snippet": "ImportError"}])

    out = view(tmp_path, capsys, "v5", "--budget", "2000")
    assert "ImportError: no module named acme" in out   # the flagged error is visible
    assert "[%d] CALL Bash" % bad in out
    assert "anchors (sweep evidence" in out and str(bad) in out.split("\n\n")[0]
    assert "elided" in out
    assert len(out.split("\n\n")[1]) < 2400


def test_view_budget_elides_the_middle_and_keeps_the_first_user_message(index, tmp_path, capsys):
    s = index.session("v3")
    index.user(s, "FIRST: " + "the opening ask " * 20)
    for i in range(60):
        index.call(s, "Read", '{"path": "p%d"}' % i, result="body %d" % i)
    index.assistant(s, "LAST line of the session")
    index.close()

    out = view(tmp_path, capsys, "v3", "--budget", "1200")
    assert "FIRST: the opening ask" in out
    assert "elided" in out
    assert "LAST line of the session" in out
    body = out.split("\n\n")[1]
    assert len(body) < 1500


def test_view_renders_the_final_report_in_full(index, tmp_path, capsys):
    s = index.session("v6")
    index.user(s, "audit the leftover ids")
    index.call(s, "Read", '{"path": "' + "x" * 200 + '"}', result="ok")
    report = "Four ids remain: " + " ".join("id%d is expected because reason %d." % (i, i)
                                             for i in range(20)) + " END-OF-REPORT"
    ord_ = index.call(s, "SubagentHandback", json.dumps({"message": report}), result="sent")
    index.close()

    out = view(tmp_path, capsys, "v6")
    assert "[%d] CALL SubagentHandback" % ord_ in out
    assert "END-OF-REPORT" in out            # far past the 60-char args cap
    assert "id19 is expected because reason 19." in out
    assert '"' + "x" * 100 not in out           # other calls keep their cap


def test_view_renders_the_final_assistant_text_in_full_up_to_its_cap(index, tmp_path, capsys):
    s = index.session("v7")
    index.user(s, "summarize")
    index.assistant(s, "an early reply " * 60)
    index.assistant(s, "Summary: " + "verified by the suite. " * 40 + "TAIL-MARK")
    huge = index.session("v8")
    index.user(huge, "summarize")
    index.assistant(huge, "y" * (rv.FINAL_REPORT_CHARS + 500))
    index.close()

    out = view(tmp_path, capsys, "v7")
    assert "TAIL-MARK" in out
    assert "an early reply " * 40 not in out    # only the last one is exempt
    out = view(tmp_path, capsys, "v8")
    assert "y" * rv.FINAL_REPORT_CHARS + "…" in out
    assert "y" * (rv.FINAL_REPORT_CHARS + 1) not in out


def test_view_budget_always_keeps_the_final_report(index, tmp_path, capsys):
    s = index.session("v9")
    index.user(s, "FIRST: run the gate")
    for i in range(200):
        index.call(s, "Read", '{"path": "p%d"}' % i, result="body %d" % i)
    report = "gate result: " + "113 match, 0 discrepancy. " * 40 + "REPORT-END"
    ord_ = index.call(s, "SubagentHandback", json.dumps({"message": report}), result="sent")
    index.close()

    out = view(tmp_path, capsys, "v9", "--budget", "1200")
    assert "FIRST: run the gate" in out
    assert "elided" in out
    assert "[%d] CALL SubagentHandback" % ord_ in out and "REPORT-END" in out


# ----------------------------------------------------------------------- grep


def grep(tmp_path, capsys, session, *extra):
    code = rv.main(["--dest", str(tmp_path), "grep", session, *extra])
    return code, capsys.readouterr()


def test_grep_finds_evidence_the_view_elided(index, tmp_path, capsys):
    s = index.session("g1")
    index.user(s, "<system-reminder>\nsecret conclusion\n</system-reminder>\nrun the check")
    for i in range(100):
        index.call(s, "Read", '{"path": "p%d"}' % i, result="body %d" % i)
    hit = index.call(s, "Bash", '{"command": "verify --all"}',
                     result="verdicts: 113 match, 0 discrepancy")
    for i in range(100):
        index.call(s, "Read", '{"path": "q%d"}' % i, result="tail %d" % i)
    index.assistant(s, "all verified")
    index.close()

    assert "113 match" not in view(tmp_path, capsys, "g1", "--budget", "1200")
    code, cap = grep(tmp_path, capsys, "g1", r"113 MATCH")
    assert code == 0
    assert cap.out.splitlines() == ["[%d] TOOL_RESULT verdicts: 113 match, 0 discrepancy"
                                    % (hit + 1)]
    code, cap = grep(tmp_path, capsys, "g1", "verify --all")
    assert cap.out.startswith("[%d] CALL Bash " % hit)
    # stripped boilerplate is no more searchable than it is quotable
    assert grep(tmp_path, capsys, "g1", "secret conclusion")[1].out.strip() == "no matches"


def test_grep_caps_its_output_and_rejects_a_bad_pattern(index, tmp_path, capsys):
    s = index.session("g2")
    for i in range(30):
        index.assistant(s, "step %d done " % i + "z" * 1000)
    index.close()

    code, cap = grep(tmp_path, capsys, "g2", "done", "--limit", "5")
    lines = cap.out.splitlines()
    assert code == 0 and len(lines) == 6
    assert lines[-1].startswith("... 25 more matches not shown")
    assert all(len(line) < rv.GREP_CONTEXT + 40 for line in lines[:5])
    code, cap = grep(tmp_path, capsys, "g2", "(unclosed")
    assert code == 2 and "bad pattern" in cap.err


# --------------------------------------------------------------------- record


def test_record_accepts_a_valid_verdict(index, store, tmp_path, capsys):
    s = index.session("r1")
    ord_ = index.user(s, "no, I said don't touch the migration")
    index.assistant(s, "sorry")
    index.close()

    run_id = fi.start_run(store[0], "transcript-review", "small-local", "{}")
    code = record(tmp_path, "r1", verdict(user_correction={
        "present": 1, "confidence": "high", "evidence_ord": ord_,
        "quote": "I said don't touch the migration", "note": "user had to stop it",
    }), run_id=run_id)
    assert code == 0
    assert "13 findings (1 present)" in capsys.readouterr().out

    rows = store[0].execute(
        "SELECT category, present, confidence, evidence_ord, quote FROM review_flags"
        " WHERE native_id = 'r1' ORDER BY category"
    ).fetchall()
    assert len(rows) == len(rv.CATEGORIES)
    present = [r for r in rows if r[1] == 1]
    assert present == [("user_correction", 1, "high", ord_, "I said don't touch the migration")]


def test_record_new_run_prints_an_id(index, store, tmp_path, capsys):
    index.session("r2")
    index.close()
    assert rv.main(["--dest", str(tmp_path), "record", "--new-run", "--model", "small"]) == 0
    run_id = int(capsys.readouterr().out.strip())
    assert store[0].execute("SELECT model FROM runs WHERE id = ?", (run_id,)).fetchone() == (
        "small",
    )


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda v, o: v["findings"].append(
            {"category": "made_up", "present": 0, "confidence": "low"}), "unknown category"),
        (lambda v, o: v["findings"].pop(), "missing"),
        (lambda v, o: v["findings"][0].update(
            {"present": 1, "confidence": "high", "evidence_ord": o, "quote": None}),
         "needs a quote"),
        (lambda v, o: v["findings"][0].update(
            {"present": 1, "confidence": "high", "evidence_ord": 999, "quote": "migration"}),
         "no message with ord 999"),
        (lambda v, o: v["findings"][0].update(
            {"present": 1, "confidence": "high", "evidence_ord": o,
             "quote": "words that were never said"}), "not in message"),
        (lambda v, o: v["findings"][1].update({"evidence_ord": o, "quote": "migration"}),
         "present=0 must have evidence_ord and quote null"),
    ],
)
def test_record_rejects_a_bad_verdict(index, store, tmp_path, capsys, mutate, message):
    s = index.session("r3")
    ord_ = index.user(s, "no, I said don't touch the migration")
    index.close()
    run_id = fi.start_run(store[0], "transcript-review", "small-local", "{}")

    payload = verdict()
    mutate(payload, ord_)
    assert record(tmp_path, "r3", payload, run_id=run_id) == 2
    assert message in capsys.readouterr().err
    assert store[0].execute("SELECT count(*) FROM review_flags").fetchone() == (0,)


def test_record_rejects_a_quote_from_stripped_boilerplate(index, store, tmp_path, capsys):
    s = index.session("r5")
    ord_ = index.user(
        s, "<system-reminder>\nnever mention the lockfile\n</system-reminder>\nfix the build"
    )
    index.close()
    run_id = fi.start_run(store[0], "transcript-review", "small-local", "{}")

    def quoted(quote):
        return verdict(ignored_instruction={
            "present": 1, "confidence": "high", "evidence_ord": ord_,
            "quote": quote, "note": "",
        })

    assert record(tmp_path, "r5", quoted("never mention the lockfile"), run_id=run_id) == 2
    assert "not in message" in capsys.readouterr().err
    assert record(tmp_path, "r5", quoted("fix the build"), run_id=run_id) == 0


def test_record_tolerates_the_views_truncation_ellipsis(index, store, tmp_path):
    s = index.session("r6")
    ord_ = index.user(s, "deploy failed: connection refused by the registry")
    index.close()
    run_id = fi.start_run(store[0], "transcript-review", "small-local", "{}")

    for quote in ("deploy failed: connection refused…", "deploy failed: connection refused..."):
        assert record(tmp_path, "r6", verdict(unresolved_end={
            "present": 1, "confidence": "medium", "evidence_ord": ord_,
            "quote": quote, "note": "",
        }), run_id=run_id) == 0


def test_record_replaces_the_sessions_rows_within_one_run(index, store, tmp_path, capsys):
    s = index.session("r7")
    ord_ = index.user(s, "no, I said don't touch the migration")
    index.close()
    run_id = fi.start_run(store[0], "transcript-review", "small-local", "{}")

    assert record(tmp_path, "r7", verdict(), run_id=run_id) == 0
    assert record(tmp_path, "r7", verdict(user_correction={
        "present": 1, "confidence": "high", "evidence_ord": ord_,
        "quote": "don't touch the migration", "note": "second pass",
    }), run_id=run_id) == 0

    assert store[0].execute(
        "SELECT count(*), sum(present) FROM review_flags WHERE native_id = 'r7'"
    ).fetchone() == (len(rv.CATEGORIES), 1)


def test_record_accepts_a_quote_from_tool_arguments(index, store, tmp_path):
    s = index.session("r4")
    index.user(s, "clean it up")
    ord_ = index.call(s, "Bash", '{"command": "rm -rf /tmp/scratch"}', result="ok")
    index.close()
    run_id = fi.start_run(store[0], "transcript-review", "small-local", "{}")

    assert record(tmp_path, "r4", verdict(tool_misuse={
        "present": 1, "confidence": "medium", "evidence_ord": ord_,
        "quote": "rm -rf /tmp/scratch", "note": "destructive",
    }), run_id=run_id) == 0


# --------------------------------------------------------------------- rollup


def _recorded(index, store, tmp_path):
    run_id = fi.start_run(store[0], "transcript-review", "small-local", "{}")
    ords = {}
    for name, project in (("a", "alpha"), ("b", "alpha"), ("c", "beta")):
        s = index.session(name, project_key=project)
        ords[name] = index.user(s, "no, I said don't touch the migration")
        index.assistant(s, "sorry")
    index.close()  # record reads the index through its own read-only connection
    for name in ords:
        ord_ = ords[name]
        if name != "c":
            assert record(tmp_path, name, verdict(user_correction={
                "present": 1, "confidence": "high", "evidence_ord": ord_,
                "quote": "don't touch the migration", "note": "",
            }), run_id=run_id) == 0
        else:
            assert record(tmp_path, name, verdict(), run_id=run_id) == 0
    return run_id


def test_rollup_counts_by_category(index, store, tmp_path, capsys):
    _recorded(index, store, tmp_path)
    capsys.readouterr()

    assert rv.main(["--dest", str(tmp_path), "rollup"]) == 0
    out = capsys.readouterr().out
    rows = [" ".join(line.split()) for line in out.splitlines()]
    assert "user_correction claude 2 2" in rows  # 2 findings across 2 sessions
    assert "sessions reviewed: 3" in out
    assert "user_correction 2 67%" in rows  # 2 of the 3 reviewed sessions


def test_rollup_counts_by_project(index, store, tmp_path, capsys):
    _recorded(index, store, tmp_path)
    capsys.readouterr()

    assert rv.main(["--dest", str(tmp_path), "rollup", "--by", "project", "--min", "1"]) == 0
    out = capsys.readouterr().out
    assert "alpha" in out
    assert "beta" not in out  # beta's only session had nothing present


def test_rubric_lists_every_category_and_the_json_shape(capsys):
    assert rv.main(["rubric"]) == 0
    out = capsys.readouterr().out
    for category in rv.CATEGORIES:
        assert category in out
    assert '"findings"' in out


def test_the_rubric_example_is_a_verdict_record_accepts(index, store, tmp_path, capsys):
    s = index.session("ex")
    for finding in rv.EXAMPLE_VERDICT["findings"]:  # the example names its own ords
        if finding["present"] == 1:
            index.conn.execute(
                "INSERT INTO messages (session_id, ord, on_main_path, role, text, raw)"
                " VALUES (?, ?, 1, 'user', ?, '{}')",
                (s, finding["evidence_ord"], finding["quote"]),
            )
    index.close()
    run_id = fi.start_run(store[0], "transcript-review", "small-local", "{}")

    assert [f["category"] for f in rv.EXAMPLE_VERDICT["findings"]] == list(rv.CATEGORIES)
    assert record(tmp_path, "ex", rv.EXAMPLE_VERDICT, run_id=run_id) == 0
    assert "13 findings (2 present)" in capsys.readouterr().out


def test_the_skill_shows_the_same_example_as_the_script():
    skill = (MODULE / "skills/transcript-review/SKILL.md").read_text(encoding="utf-8")
    block = skill.split("```json", 1)[1].split("```", 1)[0]
    assert json.loads(block) == rv.EXAMPLE_VERDICT


# --------------------------------------------------------------- unclassified


def test_record_accepts_an_unclassified_flag(index, store, tmp_path, capsys):
    s = index.session("u1")
    ord_ = index.user(s, "no, I said don't touch the migration")
    index.close()
    run_id = fi.start_run(store[0], "transcript-review", "small-local", "{}")

    payload = verdict()
    payload["unclassified"] = {"confidence": "high", "evidence_ord": ord_,
                               "quote": "I said don't touch the migration",
                               "note": "a failure mode none of the 13 names"}
    assert record(tmp_path, "u1", payload, run_id=run_id) == 0
    assert "13 findings (0 present) + 1 unclassified" in capsys.readouterr().out

    row = store[0].execute(
        "SELECT category, present, confidence, evidence_ord, quote FROM review_flags"
        " WHERE native_id = 'u1' AND category = '__unclassified__'"
    ).fetchone()
    assert row == ("__unclassified__", 1, "high", ord_, "I said don't touch the migration")
    # the 13 categories are still all answered — the rate denominator is unchanged
    assert store[0].execute(
        "SELECT count(*) FROM review_flags WHERE native_id = 'u1'"
    ).fetchone() == (len(rv.CATEGORIES) + 1,)


def test_record_rejects_an_unclassified_without_a_quote(index, store, tmp_path, capsys):
    s = index.session("u2")
    ord_ = index.user(s, "no, I said don't touch the migration")
    index.close()
    run_id = fi.start_run(store[0], "transcript-review", "small-local", "{}")

    payload = verdict()
    payload["unclassified"] = {"confidence": "high", "evidence_ord": ord_}
    assert record(tmp_path, "u2", payload, run_id=run_id) == 2
    assert "unclassified: needs a quote" in capsys.readouterr().err
    assert store[0].execute("SELECT count(*) FROM review_flags").fetchone() == (0,)


def test_record_rejects_an_unclassified_quote_not_in_the_session(index, store, tmp_path,
                                                                 capsys):
    s = index.session("u3")
    ord_ = index.user(s, "fix the build")
    index.close()
    run_id = fi.start_run(store[0], "transcript-review", "small-local", "{}")

    payload = verdict()
    payload["unclassified"] = {"confidence": "high", "evidence_ord": ord_,
                               "quote": "words that were never said"}
    assert record(tmp_path, "u3", payload, run_id=run_id) == 2
    assert "unclassified: quote is not in message" in capsys.readouterr().err
    assert store[0].execute("SELECT count(*) FROM review_flags").fetchone() == (0,)


def test_record_rejects_an_unclassified_with_bad_confidence(index, store, tmp_path, capsys):
    s = index.session("u4")
    ord_ = index.user(s, "fix the build")
    index.close()
    run_id = fi.start_run(store[0], "transcript-review", "small-local", "{}")

    payload = verdict()
    payload["unclassified"] = {"confidence": "certain", "evidence_ord": ord_,
                               "quote": "fix the build"}
    assert record(tmp_path, "u4", payload, run_id=run_id) == 2
    assert "unclassified: confidence must be one of" in capsys.readouterr().err


def test_record_unclassified_does_not_substitute_for_a_missing_category(index, store,
                                                                        tmp_path, capsys):
    s = index.session("u5")
    ord_ = index.user(s, "fix the build")
    index.close()
    run_id = fi.start_run(store[0], "transcript-review", "small-local", "{}")

    payload = verdict()
    del payload["findings"][0]  # drop one category — an unclassified flag cannot replace it
    payload["unclassified"] = {"confidence": "high", "evidence_ord": ord_,
                               "quote": "fix the build"}
    assert record(tmp_path, "u5", payload, run_id=run_id) == 2
    assert "missing" in capsys.readouterr().err


def test_rollup_counts_unclassified_separately(index, store, tmp_path, capsys):
    run_id = fi.start_run(store[0], "transcript-review", "small-local", "{}")
    a = index.session("a")
    ord_a = index.user(a, "no, I said don't touch the migration")
    b = index.session("b")
    ord_b = index.user(b, "something unclassifiable happened")
    index.close()

    assert record(tmp_path, "a", verdict(user_correction={
        "present": 1, "confidence": "high", "evidence_ord": ord_a,
        "quote": "don't touch the migration", "note": ""}), run_id=run_id) == 0
    payload = verdict()
    payload["unclassified"] = {"confidence": "high", "evidence_ord": ord_b,
                               "quote": "something unclassifiable happened",
                               "note": "fits no category"}
    assert record(tmp_path, "b", payload, run_id=run_id) == 0
    capsys.readouterr()

    assert rv.main(["--dest", str(tmp_path), "rollup"]) == 0
    out = capsys.readouterr().out
    assert "__unclassified__" not in out          # never a category rate
    assert "unclassified: 1 session(s) flagged" in out
    assert "sessions reviewed: 2" in out


def test_rubric_mentions_the_unclassified_escape_hatch(capsys):
    assert rv.main(["rubric"]) == 0
    out = capsys.readouterr().out
    assert "unclassified" in out


# -------------------------------------------------------------------- analyze


def read(tmp_path, capsys, session, *extra):
    assert rv.main(["--dest", str(tmp_path), "read", session, *extra]) == 0
    return capsys.readouterr().out


def expand(tmp_path, capsys, session, ord_, *extra):
    assert rv.main(["--dest", str(tmp_path), "expand", session, str(ord_), *extra]) == 0
    return capsys.readouterr().out


def record_analysis(tmp_path, session, payload, run_id):
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return rv.main(["--dest", str(tmp_path), "record-analysis", session, "--file", str(path),
                    "--run-id", str(run_id)])


def analysis(ord_, quote, **overrides):
    """A valid analysis whose one went_badly item cites `quote` at `ord_`."""
    body = {
        "goal": "fix the build",
        "outcome": "partial",
        "summary": "retried the install, then stopped",
        "turning_points": [],
        "went_well": [],
        "went_badly": [{"ord": ord_, "quote": quote, "note": "retried unchanged",
                        "category": "repeat_failing_approach", "label": "reinstall-loop"}],
        "root_causes": ["treated a deterministic error as transient"],
        "recommendations": [{"target": "doctrine", "text": "read the input after two failures"}],
    }
    body.update(overrides)
    return body


def page_ords(text):
    return [int(line[1:line.index("]")]) for line in text.splitlines()
            if line.startswith("[") and "]" in line]


def test_read_hides_an_ordinary_result_behind_its_size(index, tmp_path, capsys):
    s = index.session("r1")
    call = index.call(s, "Bash", '{"command": "cat big.log"}', result="secret-ish " * 500)
    index.close()

    out = read(tmp_path, capsys, "r1")
    assert f"[{call + 1}] RESULT of Bash [{call}] ok 5,500 chars" in out
    assert "secret-ish" not in out


def test_read_shows_the_start_of_a_failed_result(index, tmp_path, capsys):
    s = index.session("r2")
    call = index.call(s, "Bash", '{"command": "x"}', is_error=1,
                      result="permission denied: /etc/shadow")
    index.close()

    out = read(tmp_path, capsys, "r2")
    assert f"[{call + 1}] RESULT of Bash [{call}] ERR permission denied: /etc/shadow" in out


def test_read_shows_a_subagent_report(index, tmp_path, capsys):
    s = index.session("r3")
    index.call(s, "Agent", '{"prompt": "run the suite"}', result="all 12 tests pass")
    index.close()

    assert "RESULT of Agent [1] all 12 tests pass" in read(tmp_path, capsys, "r3")


def test_read_shows_a_short_result_in_full(index, tmp_path, capsys):
    s = index.session("r3b")
    call = index.call(s, "Bash", '{"command": "git commit"}', result="[main 1a2b3c] fix")
    index.close()

    assert f"[{call + 1}] RESULT of Bash [{call}] [main 1a2b3c] fix" in read(tmp_path, capsys, "r3b")


def test_read_caps_call_arguments_and_says_how_long_they_were(index, tmp_path, capsys):
    s = index.session("r4")
    arguments = json.dumps({"file_path": "a.py", "content": "z" * 1000})
    index.call(s, "Write", arguments)
    index.close()

    out = read(tmp_path, capsys, "r4")
    assert f'CALL Write {{"file_path": "a.py"' in out
    assert f"…[of {len(arguments):,} chars]" in out
    assert "z" * 300 not in out


def test_read_puts_every_message_on_exactly_one_page(index, tmp_path, capsys):
    s = index.session("r5")
    for i in range(30):
        index.user(s, f"question {i} " + "q" * 400)
        index.assistant(s, f"answer {i} " + "a" * 400)
    index.close()

    table = read(tmp_path, capsys, "r5", "--index", "--page-chars", "3000")
    pages = int(table.split("pages=")[1].split()[0])
    seen = []
    for page in range(1, pages + 1):
        seen += page_ords(read(tmp_path, capsys, "r5", "--page", str(page), "--page-chars", "3000"))
    assert pages > 3
    assert seen == list(range(1, 61))


def unit(size, user=False):
    u = rv.Unit(["x" * (size - 1)])
    u.user = user
    return u


def test_paginate_breaks_at_a_user_turn_in_the_second_half():
    turn = unit(100, user=True)
    units = [unit(100, user=True), unit(400), turn, unit(300), unit(300)]

    pages = rv.paginate(units, 1000)
    assert pages[1][0] is turn


def test_paginate_breaks_at_the_overflow_when_no_user_turn_is_late_enough():
    units = [unit(100, user=True), unit(400), unit(400), unit(400)]

    assert [len(p) for p in rv.paginate(units, 1000)] == [3, 1]


def test_paginate_gives_an_oversized_message_its_own_page():
    units = [unit(100), unit(5000), unit(100)]

    assert [len(p) for p in rv.paginate(units, 1000)] == [1, 1, 1]


def test_read_refuses_a_page_past_the_end(index, tmp_path, capsys):
    s = index.session("r6")
    index.user(s, "hello")
    index.close()

    assert rv.main(["--dest", str(tmp_path), "read", "r6", "--page", "2"]) == 2
    assert "has 1 page(s)" in capsys.readouterr().err


def test_expand_pages_through_a_long_result(index, tmp_path, capsys):
    s = index.session("e1")
    call = index.call(s, "Bash", '{"command": "x"}', result="a" * 5000 + "THE-END")
    index.close()

    first = expand(tmp_path, capsys, "e1", call + 1)
    rest = expand(tmp_path, capsys, "e1", call + 1, "--offset", "4000")
    assert "(next: --offset 4000)" in first and "THE-END" not in first
    assert "THE-END" in rest and "(end)" in rest


def test_expand_shows_a_calls_full_arguments(index, tmp_path, capsys):
    s = index.session("e2")
    call = index.call(s, "Write", json.dumps({"content": "y" * 900 + "TAIL"}))
    index.close()

    assert "TAIL" in expand(tmp_path, capsys, "e2", call)


def test_expand_strips_boilerplate_from_a_user_turn(index, tmp_path, capsys):
    s = index.session("e3")
    ord_ = index.user(s, "do the thing<system-reminder>injected rules</system-reminder>")
    index.close()

    out = expand(tmp_path, capsys, "e3", ord_)
    assert "do the thing" in out and "injected rules" not in out


def analyzed_session(index, pages_of_text=1):
    """A session with one quotable failure; `pages_of_text` × ~3000 chars of padding."""
    s = index.session("a1")
    index.user(s, "fix the build")
    bad = index.call(s, "Bash", '{"command": "npm i"}', is_error=1, result="npm ERR! peer dep missing")
    for i in range(pages_of_text * 6):
        index.assistant(s, f"thinking {i} " + "t" * 480)
    index.close()
    return bad + 1


def read_all(tmp_path, capsys, session, run_id, page_chars="3000"):
    table = read(tmp_path, capsys, session, "--index", "--page-chars", page_chars)
    for page in range(1, int(table.split("pages=")[1].split()[0]) + 1):
        read(tmp_path, capsys, session, "--page", str(page), "--page-chars", page_chars,
             "--run-id", str(run_id))


def test_record_analysis_stores_a_valid_analysis_after_every_page_is_read(index, store, tmp_path,
                                                                          capsys):
    bad = analyzed_session(index, pages_of_text=3)
    run_id = fi.start_run(store[0], "transcript-analyze", "m", "{}")
    read_all(tmp_path, capsys, "a1", run_id)

    assert record_analysis(tmp_path, "a1", analysis(bad, "npm ERR! peer dep missing"), run_id) == 0
    row = store[0].execute("SELECT outcome, body FROM session_analyses").fetchone()
    assert row[0] == "partial"
    assert json.loads(row[1])["went_badly"][0]["label"] == "reinstall-loop"


def test_record_analysis_refuses_when_a_page_was_never_read(index, store, tmp_path, capsys):
    bad = analyzed_session(index, pages_of_text=3)
    run_id = fi.start_run(store[0], "transcript-analyze", "m", "{}")
    read(tmp_path, capsys, "a1", "--page", "1", "--page-chars", "3000", "--run-id", str(run_id))

    assert record_analysis(tmp_path, "a1", analysis(bad, "npm ERR! peer dep missing"), run_id) == 2
    assert "page(s) 2" in capsys.readouterr().err


def test_record_analysis_refuses_without_any_logged_read(index, store, tmp_path, capsys):
    bad = analyzed_session(index)
    run_id = fi.start_run(store[0], "transcript-analyze", "m", "{}")

    assert record_analysis(tmp_path, "a1", analysis(bad, "npm ERR! peer dep missing"), run_id) == 2
    assert "logged no page reads" in capsys.readouterr().err


@pytest.mark.parametrize("change, message", [
    ({"outcome": "great"}, "outcome must be one of"),
    ({"summary": ""}, "summary: needs a string"),
    ({"extra": 1}, "unknown: extra"),
    ({"recommendations": [{"target": "everyone", "text": "x"}]}, "target must be one of"),
    ({"root_causes": [""]}, "root_causes"),
])
def test_record_analysis_refuses_a_bad_shape(index, store, tmp_path, capsys, change, message):
    bad = analyzed_session(index)
    run_id = fi.start_run(store[0], "transcript-analyze", "m", "{}")
    read_all(tmp_path, capsys, "a1", run_id)

    payload = analysis(bad, "npm ERR! peer dep missing", **change)
    assert record_analysis(tmp_path, "a1", payload, run_id) == 2
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("item, message", [
    ({"quote": "npm ERR! something else"}, "quote is not in message"),
    ({"category": "made_up"}, "category must be a rubric category"),
    ({"label": ""}, "needs a label"),
    ({"note": ""}, "needs a note"),
    ({"ord": 999}, "no message with ord 999"),
])
def test_record_analysis_refuses_bad_evidence(index, store, tmp_path, capsys, item, message):
    bad = analyzed_session(index)
    run_id = fi.start_run(store[0], "transcript-analyze", "m", "{}")
    read_all(tmp_path, capsys, "a1", run_id)

    payload = analysis(bad, "npm ERR! peer dep missing")
    payload["went_badly"][0].update(item)
    assert record_analysis(tmp_path, "a1", payload, run_id) == 2
    assert message in capsys.readouterr().err


def test_record_analysis_replaces_the_sessions_analysis_within_one_run(index, store, tmp_path,
                                                                        capsys):
    bad = analyzed_session(index)
    run_id = fi.start_run(store[0], "transcript-analyze", "m", "{}")
    read_all(tmp_path, capsys, "a1", run_id)

    record_analysis(tmp_path, "a1", analysis(bad, "npm ERR! peer dep missing"), run_id)
    record_analysis(tmp_path, "a1", analysis(bad, "npm ERR! peer dep missing",
                                             outcome="failed"), run_id)
    rows = store[0].execute("SELECT outcome FROM session_analyses").fetchall()
    assert rows == [("failed",)]


def test_read_refuses_an_unknown_run_id(index, store, tmp_path, capsys):
    analyzed_session(index)

    with pytest.raises(SystemExit) as exc:
        rv.main(["--dest", str(tmp_path), "read", "a1", "--run-id", "999"])
    assert "no run 999" in str(exc.value)


def test_the_example_analysis_is_one_record_analysis_accepts(index, store, tmp_path, capsys):
    s = index.session("ex")
    for kind in ("turning_points", "went_badly"):
        for item in rv.EXAMPLE_ANALYSIS[kind]:  # the example names its own ords
            index.conn.execute(
                "INSERT INTO messages (session_id, ord, on_main_path, role, text, raw)"
                " VALUES (?, ?, 1, 'user', ?, '{}')", (s, item["ord"], item["quote"]),
            )
    index.close()
    run_id = fi.start_run(store[0], "transcript-analyze", "m", "{}")
    read_all(tmp_path, capsys, "ex", run_id)

    assert record_analysis(tmp_path, "ex", rv.EXAMPLE_ANALYSIS, run_id) == 0


def test_the_analyze_skill_shows_the_same_example_as_the_script():
    skill = (MODULE / "skills/transcript-analyze/SKILL.md").read_text(encoding="utf-8")
    block = skill.split("```json", 1)[1].split("```", 1)[0]
    assert json.loads(block) == rv.EXAMPLE_ANALYSIS


def two_analyzed_sessions(index, store, tmp_path, capsys):
    ords = {}
    for name in ("t1", "t2"):
        s = index.session(name)
        ords[name] = index.call(s, "Bash", '{"command": "npm i"}', is_error=1,
                                result="npm ERR! peer dep missing") + 1
    index.close()
    run_id = fi.start_run(store[0], "transcript-analyze", "m", "{}")
    for name, ord_ in ords.items():
        read_all(tmp_path, capsys, name, run_id)
        record_analysis(tmp_path, name, analysis(ord_, "npm ERR! peer dep missing"), run_id)
    expand(tmp_path, capsys, "t1", ords["t1"], "--run-id", str(run_id))
    capsys.readouterr()


def test_themes_groups_problems_by_category_and_label(index, store, tmp_path, capsys):
    two_analyzed_sessions(index, store, tmp_path, capsys)

    assert rv.main(["--dest", str(tmp_path), "themes"]) == 0
    out = capsys.readouterr().out
    assert "sessions analyzed: 2" in out
    assert "repeat_failing_approach  reinstall-loop  2      2" in out


def test_themes_shows_a_problem_seen_in_one_session_by_default(index, store, tmp_path, capsys):
    bad = analyzed_session(index)
    run_id = fi.start_run(store[0], "transcript-analyze", "m", "{}")
    read_all(tmp_path, capsys, "a1", run_id)
    record_analysis(tmp_path, "a1", analysis(bad, "npm ERR! peer dep missing"), run_id)
    capsys.readouterr()

    rv.main(["--dest", str(tmp_path), "themes"])
    assert "reinstall-loop" in capsys.readouterr().out


def test_themes_run_id_scopes_to_one_batch(index, store, tmp_path, capsys):
    two_analyzed_sessions(index, store, tmp_path, capsys)
    other = fi.start_run(store[0], "transcript-analyze", "m", "{}")

    rv.main(["--dest", str(tmp_path), "themes", "--run-id", str(other)])
    assert "no recorded analyses in this scope" in capsys.readouterr().out


def test_themes_counts_expansions_per_session(index, store, tmp_path, capsys):
    two_analyzed_sessions(index, store, tmp_path, capsys)

    rv.main(["--dest", str(tmp_path), "themes"])
    assert "mean 0.5, max 1, none in 1 of 2" in capsys.readouterr().out
