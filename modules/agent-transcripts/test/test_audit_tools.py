"""Tests for the transcript-audit tooling added on top of query.py.

Covers the ingest `injected`/annotate pass, and the search.py / excerpt.py / cluster.py
helpers, against a synthetic index built through the real ingest schema so the FTS
triggers, foreign keys and the `injected` column match production.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills/transcript-ingest"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills/transcript-query"))

import transcripts as ti  # noqa: E402
import search as s  # noqa: E402
import excerpt as ex  # noqa: E402
import cluster as cl  # noqa: E402

STANDING = (
    "Always check for the devcontainer first. If a .devcontainer exists, "
    "work from the devcontainer."
)


def _seed(root: Path) -> None:
    """A dsh index with four sessions; a standing instruction repeats in the first three."""
    conn = ti.open_db(root)
    conn.execute(
        "INSERT INTO files (id, harness, relpath, size, mtime, parser_version, status,"
        " error, parsed_at) VALUES (1, 'dsh', 'raw/dsh/host/sessions/--tmp-proj--/x.jsonl.zstd',"
        " 10, 0, ?, 'ok', NULL, '2026-01-01T00:00:00.000Z')",
        (ti.PARSER_VERSION,),
    )

    def session(sid: int, title: str) -> None:
        conn.execute(
            "INSERT INTO sessions (id, harness, native_id, file_id, cwd, project_key,"
            " kind, parent_native_id, started_at, ended_at, model, title)"
            " VALUES (?, 'dsh', ?, 1, '/tmp', '--tmp-proj--', 'main', NULL,"
            " '2026-01-01T00:00:00.000Z', NULL, NULL, ?)",
            (sid, f"s-{sid}", title),
        )

    def msg(sid: int, ord_: int, role: str, text: str) -> None:
        conn.execute(
            "INSERT INTO messages (session_id, ord, native_id, parent_native_id,"
            " on_main_path, role, ts, text, model, stop_reason, input_tokens,"
            " output_tokens, raw, injected, norm_key, harness)"
            " VALUES (?, ?, NULL, NULL, 1, ?,"
            " '2026-01-01T00:00:00.000Z', ?, NULL, NULL, NULL, NULL, '', 0, ?, 'dsh')",
            (sid, ord_, role, text, ti._norm_key(text)),
        )

    session(10, "devcontainer up failed")
    session(11, "devcontainer build")
    session(12, "devcontainer config")
    session(13, "recipes work")
    # distinct first user messages (not cross-session duplicates, no 'devcontainer')
    msg(10, 0, "user", "Fix this.")
    msg(11, 0, "user", "Help.")
    msg(12, 0, "user", "Look.")
    msg(13, 0, "user", "Recipe.")
    # the standing instruction repeats across the first three sessions -> injected
    for sid in (10, 11, 12):
        msg(sid, 1, "user", STANDING)
    # Session 10: real devcontainer content (matches the term, not injected)
    msg(10, 2, "user", "How do I run the devcontainer here?")
    msg(10, 3, "tool_result", "Error: devcontainer CLI permission denied on /run/user/1002/docker.sock")
    msg(10, 4, "assistant", "devcontainer up failed with exit code 1")
    # Session 11: one real mention
    msg(11, 2, "user", "devcontainer build failed: Dev container not found")
    # Session 12: one mention, no error
    msg(12, 2, "user", "check the devcontainer.json config")
    # Session 13: no devcontainer at all
    msg(13, 2, "user", "add a recipe to the shopping list")
    conn.commit()
    conn.close()


@pytest.fixture
def index(tmp_path):
    _seed(tmp_path)
    ti.annotate(tmp_path)
    return tmp_path


def _counts(conn):
    return {
        row[0]: row[1]
        for row in conn.execute("SELECT session_id, count(*) FROM messages GROUP BY 1")
    }


# ---------------------------------------------------------------------- annotate


def test_annotate_flags_cross_session_instruction_but_not_results(index):
    conn = ti.open_db(index)
    injected = {
        row[0]
        for row in conn.execute(
            "SELECT id FROM messages WHERE injected = 1"
        )
    }
    # The three standing-instruction messages are flagged.
    rows = conn.execute(
        "SELECT m.id, m.session_id FROM messages m WHERE m.text = ?", (STANDING,)
    ).fetchall()
    assert len(rows) == 3
    assert all(r[0] in injected for r in rows)
    # The tool_result error in session 10 is NOT flagged (it is an error, not boilerplate).
    err = conn.execute(
        "SELECT id FROM messages WHERE role = 'tool_result'"
    ).fetchone()
    assert err[0] not in injected
    conn.close()


# ---------------------------------------------------------------------- search


def test_search_excludes_injected(index, capsys):
    s.main(["--term", "devcontainer", "--exclude-injected", "--dest", str(index)])
    out = capsys.readouterr().out
    lines = [l for l in out.splitlines() if l and l[0].isdigit()]
    ids = {int(l.split(" | ")[0]) for l in lines}
    assert ids == {10, 11, 12}  # session 13 has no devcontainer mention
    line = next(l for l in lines if l.startswith("10 |"))
    assert line.split(" | ")[4] == "3"  # hits (col 4): 3 real mentions, standing excluded


def test_search_counts_boilerplate_without_the_flag(index, capsys):
    s.main(["--term", "devcontainer", "--dest", str(index)])
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if l.startswith("10 |"))
    assert line.split(" | ")[4] == "4"  # 3 real + the standing instruction


def test_search_ranks_by_error_context(index, capsys):
    s.main(["--term", "devcontainer", "--exclude-injected", "--errors", "--dest", str(index)])
    out = capsys.readouterr().out
    lines = [l for l in out.splitlines() if l and l[0].isdigit()]
    first = lines[0]
    assert first.startswith("10 |")  # session 10 has the most error-context matches
    assert first.split(" | ")[5] == "2"  # error_hits (col 5)


# ---------------------------------------------------------------------- excerpt


def test_excerpt_writes_files_and_manifest(index, tmp_path):
    work = tmp_path / "work"
    ex.main([
        "--term", "devcontainer", "--exclude-injected", "--dest", str(index),
        "--work", str(work), "--run", "run1", "--head", "1", "--tail", "1",
    ])
    assert (work / "manifest.json").exists()
    manifest = __import__("json").loads((work / "manifest.json").read_text())
    assert manifest["session_count"] == 3
    by_id = {s_["id"]: s_ for s_ in manifest["sessions"]}
    # session 10 has 3 matches > head(1)+tail(1) -> truncated; the 1-match sessions are not.
    assert by_id[10]["truncated"] is True and by_id[10]["total_matches"] == 3
    assert by_id[11]["truncated"] is False and by_id[12]["truncated"] is False
    for s_ in manifest["sessions"]:
        assert Path(s_["file"]).exists()
    # A truncated excerpt mentions the omitted count.
    text = (work / "excerpts" / "10.txt").read_text()
    assert "omitted between head and tail" in text
    assert "Always check" not in text  # standing instruction was excluded


def test_excerpt_next_reads_a_later_chunk(index, capsys):
    ex.main([
        "--next", "10", "--term", "devcontainer", "--exclude-injected",
        "--offset", "1", "--count", "2", "--dest", str(index),
    ])
    out = capsys.readouterr().out
    assert "permission denied" in out
    assert "exit code 1" in out


# ---------------------------------------------------------------------- cluster


def test_cluster_groups_by_signature(tmp_path, capsys):
    verdicts = (
        "18651|VERDICT=ISSUE|SEVERITY=medium|devcontainer CLI could not reach the docker "
        "daemon, permission denied on the socket\n"
        "18761|VERDICT=ISSUE|SEVERITY=medium|rootless docker socket /run/user/1002/docker.sock "
        "denied for everyone\n"
        "18723|VERDICT=NO_ISSUE|SEVERITY=n/a|just a mention, no error\n"
    )
    path = tmp_path / "verdicts.txt"
    path.write_text(verdicts)
    cl.main(["--input", str(path), "--min", "2"])
    out = capsys.readouterr().out
    assert "rootless docker socket" in out
    assert "18651" in out and "18761" in out
    # session 18723 is unmatched (no known signature)
    assert "unmatched" in out


# ------------------------------------------------ regression: CLI bugs (v0.6.1)


def test_annotate_subcommand_arg_names(tmp_path, capsys):
    """`transcripts.py annotate` must parse --exclude-role (not --exclude_roles)."""
    _seed(tmp_path)
    rc = ti.main(["annotate", "--dest", str(tmp_path), "--exclude-role", "assistant"])
    out = capsys.readouterr().out
    assert "annotate: injected=" in out
    assert "exclude_roles=assistant" in out
    assert isinstance(rc, int)


def test_excerpt_ids_without_term(tmp_path):
    """`excerpt.py --ids` (no --term) excerpts the session's whole conversation."""
    _seed(tmp_path)
    work = tmp_path / "work"
    ex.main(["--ids", "10", "--dest", str(tmp_path), "--work", str(work), "--run", "ids"])
    text = (work / "excerpts" / "10.txt").read_text()
    assert "# session_id=10" in text
    assert "devcontainer up failed" in text  # the assistant message is included

