import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "skills/transcript-sweep"),
)
import findings as fi  # noqa: E402


def flag(kind, count=1, severity="issue"):
    return {
        "kind": kind,
        "severity": severity,
        "count": count,
        "detail": {"threshold": count},
        "evidence": [{"snippet": kind}],
    }


def test_schema_applies_and_is_idempotent(tmp_path):
    conn = fi.open_findings(tmp_path)
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    indexes = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'"
                                   " AND name NOT LIKE 'sqlite_%'")
    }
    conn.close()

    assert {"runs", "sweep_flags", "review_flags"} <= tables
    assert indexes == {
        "sweep_flags_session",
        "review_flags_session",
        "review_flags_category",
        "review_flags_run",
    }

    again = fi.open_findings(tmp_path)  # reopening an existing store must not raise
    again.execute("SELECT count(*) FROM sweep_flags").fetchone()
    again.close()
    assert (tmp_path / "findings.db").exists()


def test_open_findings_creates_the_directory(tmp_path):
    conn = fi.open_findings(tmp_path / "nested" / "cache")
    conn.close()
    assert (tmp_path / "nested" / "cache" / "findings.db").exists()


def test_start_run_records_the_invocation(tmp_path):
    conn = fi.open_findings(tmp_path)
    run_id = fi.start_run(conn, "transcript-sweep", None, ["--harness", "pi"])
    other = fi.start_run(conn, "transcript-review", "haiku", "raw string")

    rows = conn.execute("SELECT id, skill, model, started_at, args FROM runs ORDER BY id").fetchall()
    conn.close()

    assert [r[0] for r in rows] == [run_id, other]
    assert rows[0][1:3] == ("transcript-sweep", None)
    assert rows[0][4] == json.dumps(["--harness", "pi"])
    assert rows[0][3].endswith("+00:00")  # UTC, not local
    assert rows[1][1:3] == ("transcript-review", "haiku")
    assert rows[1][4] == "raw string"  # a string is stored as given


def test_replace_sweep_flags_replaces_rather_than_duplicates(tmp_path):
    conn = fi.open_findings(tmp_path)
    run_id = fi.start_run(conn, "transcript-sweep", None, [])

    assert fi.replace_sweep_flags(conn, run_id, "pi", "abc", [flag("tool_error", 3)]) == 1
    conn.commit()

    second = fi.start_run(conn, "transcript-sweep", None, [])
    fi.replace_sweep_flags(
        conn, run_id, "pi", "other", [flag("tool_error", 9)]
    )  # a sibling session is untouched
    fi.replace_sweep_flags(conn, second, "pi", "abc", [flag("tool_error", 5), flag("long_session")])
    conn.commit()

    rows = conn.execute(
        "SELECT run_id, kind, count, detail, evidence FROM sweep_flags"
        " WHERE native_id = 'abc' ORDER BY kind"
    ).fetchall()
    assert [r[:3] for r in rows] == [(second, "long_session", 1), (second, "tool_error", 5)]
    assert json.loads(rows[1][3]) == {"threshold": 5}
    assert json.loads(rows[1][4]) == [{"snippet": "tool_error"}]
    assert conn.execute("SELECT count(*) FROM sweep_flags").fetchone()[0] == 3

    fi.replace_sweep_flags(conn, second, "pi", "abc", [])  # a clean session keeps no rows
    conn.commit()
    assert conn.execute(
        "SELECT count(*) FROM sweep_flags WHERE native_id = 'abc'"
    ).fetchone()[0] == 0
    conn.close()


def test_same_native_id_on_two_harnesses_is_two_sessions(tmp_path):
    conn = fi.open_findings(tmp_path)
    run_id = fi.start_run(conn, "transcript-sweep", None, [])
    fi.replace_sweep_flags(conn, run_id, "pi", "abc", [flag("tool_error")])
    fi.replace_sweep_flags(conn, run_id, "dsh", "abc", [flag("tool_error")])
    conn.commit()

    assert conn.execute("SELECT count(*) FROM sweep_flags").fetchone()[0] == 2
    conn.close()


def test_one_kind_per_session_is_unique(tmp_path):
    conn = fi.open_findings(tmp_path)
    run_id = fi.start_run(conn, "transcript-sweep", None, [])
    with pytest.raises(sqlite3.IntegrityError):
        fi.replace_sweep_flags(
            conn, run_id, "pi", "abc", [flag("tool_error", 1), flag("tool_error", 2)]
        )
    conn.rollback()
    conn.close()


def legacy_store(tmp_path, review_rows=0):
    """The schema as it shipped before review_flags gained its UNIQUE key."""
    legacy = fi.FINDINGS_SCHEMA.replace(
        "    created_at   TEXT NOT NULL,\n    UNIQUE(run_id, harness, native_id, category)\n",
        "    created_at   TEXT NOT NULL\n",
    )
    assert "UNIQUE(run_id" not in legacy  # the replacement really removed the constraint
    conn = sqlite3.connect(tmp_path / "findings.db")
    conn.executescript(legacy)
    conn.execute(
        "INSERT INTO runs (id, skill, started_at) VALUES (1, 'transcript-sweep', 'then')"
    )
    conn.execute(
        "INSERT INTO sweep_flags (run_id, harness, native_id, kind, severity, count, detail,"
        " evidence) VALUES (1, 'pi', 'old', 'tool_error', 'issue', 2, '{}', '[]')"
    )
    for i in range(review_rows):
        conn.execute(
            "INSERT INTO review_flags (run_id, harness, native_id, category, present,"
            " confidence, created_at) VALUES (1, 'pi', 'old', ?, 0, 'low', 'then')",
            ("cat%d" % i,),
        )
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()


def test_review_flags_are_unique_per_run_session_and_category(tmp_path):
    conn = fi.open_findings(tmp_path)
    run_id = fi.start_run(conn, "transcript-review", "small", [])
    insert = (
        "INSERT INTO review_flags (run_id, harness, native_id, category, present, confidence,"
        " created_at) VALUES (?, 'pi', 'abc', 'tool_misuse', ?, 'low', 'now')"
    )
    conn.execute(insert, (run_id, 0))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, (run_id, 1))
    conn.rollback()
    conn.close()


def test_an_old_store_without_review_findings_is_recreated(tmp_path):
    legacy_store(tmp_path)

    conn = fi.open_findings(tmp_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == fi.SCHEMA_VERSION
    # the migration drops review_flags only; the sweep's work survives
    assert conn.execute("SELECT count(*) FROM sweep_flags").fetchone()[0] == 1
    insert = (
        "INSERT INTO review_flags (run_id, harness, native_id, category, present, confidence,"
        " created_at) VALUES (1, 'pi', 'abc', 'tool_misuse', 0, 'low', 'now')"
    )
    conn.execute(insert)
    with pytest.raises(sqlite3.IntegrityError):  # the constraint is really there now
        conn.execute(insert)
    conn.rollback()
    conn.close()


def test_an_old_store_with_review_findings_refuses_with_exit_2(tmp_path, capsys):
    legacy_store(tmp_path, review_rows=3)

    with pytest.raises(SystemExit) as exc:
        fi.open_findings(tmp_path)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "3 rows" in err and "Move the file aside" in err

    conn = sqlite3.connect(tmp_path / "findings.db")  # and nothing was touched
    assert conn.execute("SELECT count(*) FROM review_flags").fetchone()[0] == 3
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    conn.close()


def test_readonly_open_of_a_missing_store_is_a_clear_error(tmp_path):
    with pytest.raises(SystemExit) as e:
        fi.open_findings(tmp_path, readonly=True)
    assert "transcript-sweep" in str(e.value)
    assert not (tmp_path / "findings.db").exists()  # read-only never creates


def test_readonly_open_cannot_write(tmp_path):
    conn = fi.open_findings(tmp_path)
    run_id = fi.start_run(conn, "transcript-sweep", None, [])
    fi.replace_sweep_flags(conn, run_id, "pi", "abc", [flag("tool_error", 4)])
    conn.commit()
    conn.close()

    ro = fi.open_findings(tmp_path, readonly=True)
    assert ro.execute("SELECT count FROM sweep_flags").fetchone()[0] == 4
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("DELETE FROM sweep_flags")
    ro.close()
