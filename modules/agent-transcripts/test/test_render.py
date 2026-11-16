import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MODULE / "skills/transcript-ingest"))
sys.path.insert(0, str(MODULE / "skills/transcript-analyze"))
import corpus as cp  # noqa: E402
import render as rd  # noqa: E402
import transcripts as tr  # noqa: E402

TEMPLATE = "You are performing an independent review of a pull request. " + "Rules follow. " * 60


class Index:
    """A synthetic index on the real schema, so schema drift fails these tests."""

    def __init__(self, root: Path):
        self.root = root
        self.conn = sqlite3.connect(root / "transcripts.db")
        self.conn.executescript(tr.SCHEMA)
        self.conn.execute(
            "INSERT INTO files (id, harness, relpath, size, mtime, parser_version, status,"
            " parsed_at) VALUES (1, 'claude', 'a.jsonl', 1, 1, ?, 'ok', 'now')",
            (tr.PARSER_VERSION,))
        self.ords: dict[int, int] = {}

    def session(self, native_id, kind="main", project_key="p", parent=None,
                started_at="2026-11-10T00:00:00Z"):
        cur = self.conn.execute(
            "INSERT INTO sessions (harness, native_id, file_id, cwd, project_key, kind,"
            " parent_native_id, started_at) VALUES ('claude', ?, 1, '/w', ?, ?, ?, ?)",
            (native_id, project_key, kind, parent, started_at))
        self.ords[cur.lastrowid] = 0
        return cur.lastrowid

    def msg(self, sid, role, text, injected=0):
        self.ords[sid] += 1
        cur = self.conn.execute(
            "INSERT INTO messages (session_id, ord, on_main_path, role, text, injected, ts)"
            " VALUES (?, ?, 1, ?, ?, ?, '2026-11-10T12:00:00Z')",
            (sid, self.ords[sid], role, text, injected))
        return cur.lastrowid

    def call(self, sid, name, arguments, result="", is_error=0, text=""):
        mid = self.msg(sid, "assistant", text)
        rid = self.msg(sid, "tool_result", result)
        self.conn.execute(
            "INSERT INTO tool_calls (message_id, call_id, name, arguments, result_message_id,"
            " is_error) VALUES (?, ?, ?, ?, ?, ?)", (mid, f"c{mid}", name, arguments, rid, is_error))
        return mid

    def done(self):
        self.conn.commit()
        return sqlite3.connect(f"file:{self.root / 'transcripts.db'}?mode=ro", uri=True)


@pytest.fixture
def ix(tmp_path):
    return Index(tmp_path)


def render(conn, sid="s1", **kw):
    return rd.render_session(conn, sid, **kw)[2]


def test_human_turns_are_never_hidden_by_the_injected_flag(ix):
    s = ix.session("s1")
    ix.msg(s, "user", "yes", injected=1)
    ix.msg(s, "user", "<system-reminder>harness text</system-reminder>commit and push", injected=1)
    out = render(ix.done())
    assert "): yes" in out
    assert "commit and push" in out and "harness text" not in out


def test_skill_body_renders_as_one_line(ix):
    s = ix.session("s1")
    ix.msg(s, "system", "Base directory for this skill: /x/skills/oncall\n" + "body " * 5000)
    out = render(ix.done())
    assert "skill loaded: oncall" in out and "body body" not in out


def test_compaction_is_a_boundary_showing_current_work(ix):
    s = ix.session("s1")
    ix.msg(s, "system", "This session is being continued from a previous conversation.\n"
                        "8. Current Work:\n   Running the e2e matrix.\n9. Optional Next Step:\n   x")
    out = render(ix.done())
    assert "CONTEXT COMPACTION 1" in out and "Running the e2e matrix." in out


@pytest.fixture
def delegated(ix):
    s = ix.session("s1")
    ix.call(s, "Agent", json.dumps({"prompt": "Review the diff for reuse."}),
            result="Async agent launched successfully. agentId: abc")
    ix.msg(s, "system", 'Another Claude session sent a message:\n<agent-message from="abc">\n'
                        "[Subagent hand-back] Preamble. The report follows:\n  Found 2 reuse issues."
                        "\n</agent-message>\nThat other session is an agent. Trailer text.")
    sub = ix.session("agent-abc", kind="subagent", parent="s1")
    ix.msg(sub, "user", "Review the diff for reuse.")
    ix.call(sub, "Read", '{"file_path": "a.py"}', result="code")
    return render(ix.done())


def test_background_launch_notice_is_collapsed(delegated):
    assert "launched in background" in delegated and "agentId" not in delegated


def test_subagent_report_is_shown_without_harness_framing(delegated):
    assert "SUBAGENT REPORT from agent-abc" in delegated and "Found 2 reuse issues." in delegated
    assert "Preamble" not in delegated and "Trailer text" not in delegated


def test_agent_call_links_to_its_subagent_session(delegated):
    assert "⤷ subagent agent-abc: 1 calls (Read 1)" in delegated


def test_final_report_arguments_are_never_cut_and_expand_shows_them(ix):
    s = ix.session("s1")
    report = json.dumps({"findings": [{"title": "t" * 7000, "id": "CC-9"}]})
    mid = ix.call(s, "StructuredOutput", report)
    conn = ix.done()
    out = render(conn)
    assert "CC-9" in out and "…[" not in out.split("StructuredOutput", 1)[1].split("\n  ←")[0]
    assert "CC-9" in rd.expand(conn, mid, offset=7000)


def test_long_assistant_turn_keeps_head_and_tail(ix):
    s = ix.session("s1")
    ix.msg(s, "assistant", "HEAD " + "x" * 5000 + " DECISIONS: pick A or B")
    ix.msg(s, "assistant", "last")
    out = render(ix.done())
    assert "HEAD" in out and "DECISIONS: pick A or B" in out and "chars omitted" in out


def test_result_hints_and_repeated_calls(ix):
    s = ix.session("s1")
    ix.call(s, "Bash", '{"command": "pytest"}', result="....\n===== 5 passed in 1.2s =====\n")
    for _ in range(3):
        ix.call(s, "Bash", '{"command": "flaky"}', result="boom", is_error=1)
    out = render(ix.done())
    assert "last line: ===== 5 passed in 1.2s =====" in out
    assert "×3 identical calls in a row" in out


def test_git_actions_are_in_the_header(ix):
    s = ix.session("s1")
    ix.call(s, "Bash", json.dumps({"command": "cd /w && git commit -m fix && git push origin b"}))
    header = render(ix.done()).split("\n\n", 1)[0]
    assert "git commit -m fix" in header and "git push origin b" in header


def test_auto_mode_outlines_and_folds_only_scripted_turns(ix):
    s = ix.session("s1")
    for _ in range(4):
        ix.msg(s, "user", "<command-name>/oncall</command-name><command-args>bugs</command-args>")
        ix.call(s, "Bash", '{"command": "check"}', result="ok")
        ix.msg(s, "assistant", "pass empty " + "z" * 400)
    for _ in range(3):
        ix.msg(s, "user", "yes")
        ix.msg(s, "assistant", "done")
    _, mode, out = rd.render_session(ix.done(), "s1", budget=500)
    assert mode == "outline"
    assert "↻ LOOP iterations 1–4 (4 scripted turns: /oncall bugs ×4)" in out
    assert out.count("): yes") == 3  # human replies stay visible
    assert "# repeated slash-command turns: /oncall bugs ×4" in out


def test_lines_are_wrapped_for_file_readers(ix):
    s = ix.session("s1")
    ix.msg(s, "assistant", "y" * 9000)
    out = render(ix.done())
    assert max(len(line) for line in out.splitlines()) <= rd.LINE_WRAP + 6
    assert "y" * 9000 in out.replace("\n    ↪ ", "")


def test_write_private_refuses_a_git_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    with pytest.raises(SystemExit, match="inside a git worktree"):
        rd.write_private(repo / "out" / "s.txt", "private")
    rd.write_private(tmp_path / "cache" / "s.txt", "ok")
    assert (tmp_path / "cache" / "s.txt").read_text() == "ok"


def test_scripted_sessions_are_found_by_shared_opening_not_slash_commands(ix):
    for i in range(3):
        sid = ix.session(f"run{i}", project_key="review-pr-1")
        ix.msg(sid, "user", TEMPLATE + f" round {i}")
    typed = ix.session("typed")
    ix.msg(typed, "user", "/dual-review https://example/pr/1 " + "please " * 100)
    conn = ix.done()
    rows = cp.classify(conn, cp.sized(conn, None, None, "main", None))
    by = {r["session_id"]: r for r in rows}
    assert all(by[f"run{i}"]["scripted"] for i in range(3))
    assert by["run0"]["group"] == by["run2"]["group"] == "run:review-pr-1"
    assert not by["typed"]["scripted"]


def test_pack_never_splits_a_run_and_respects_the_budget():
    run = [{"chars": 40}, {"chars": 40}]
    units = [run, [{"chars": 70}], [{"chars": 30}]]
    batches = cp.pack(units, budget=100)
    assert all(sum(s["chars"] for s in b) <= 100 for b in batches)
    assert any(all(s in b for s in run) for b in batches)


def test_plan_writes_sessions_and_manifest_under_the_work_dir(ix):
    for i in range(3):
        sid = ix.session(f"run{i}", project_key="review-pr-1")
        ix.msg(sid, "user", TEMPLATE)
        ix.msg(sid, "assistant", "a" * 4000)
    sid = ix.session("human")
    ix.msg(sid, "user", "fix the bug " * 300)
    ix.done()
    cp.main(["--dest", str(ix.root), "plan", "--run", "t", "--top", "1", "--random", "0",
             "--scripted", "3"])
    manifest = json.loads((ix.root / "work/t/manifest.json").read_text())
    picked = [s for b in manifest["batches"] for s in b]
    assert manifest["strata"] == {"top_typing": 1, "scripted": 3}
    assert all(Path(s["path"]).exists() for s in picked)
