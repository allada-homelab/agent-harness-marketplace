import json
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MODULE / "skills/transcript-decide"))
from test_review import index  # noqa: E402,F401  the synthetic index on the real schema
import decide as dc  # noqa: E402
import findings as fi  # noqa: E402


@pytest.fixture
def asked(monkeypatch):
    """Replace the model: every noul answers 0.9, every choice its first option. Records the states."""
    states_seen: list[str] = []

    def fake_ask(url, questions, states):
        states_seen.extend(states)
        answers = {}
        for qid, q in questions.items():
            if q["type"] == "noul":
                answers[qid] = {"type": "noul", "noul": 0.9}
            else:
                first = next(iter(q["criteria"]))
                answers[qid] = {"type": "choice", "choice": first, "confidence": 0.8,
                                "probabilities": {k: (0.9 if k == first else 0.1 / (len(q["criteria"]) - 1))
                                                  for k in q["criteria"]}}
        return [(answers, "rev1") for _ in states], "queue;dur=0.2"

    monkeypatch.setattr(dc, "ask", fake_ask)
    monkeypatch.setenv("DECISION_URL", "http://decision.test")
    return states_seen


def run(tmp_path, *extra):
    return dc.main(["--dest", str(tmp_path), "run", *extra])


def answers(tmp_path, battery):
    conn = fi.open_findings(tmp_path, readonly=True)
    return conn.execute("SELECT native_id, unit, qid, value, label, revision FROM decision_answers"
                        " WHERE battery = ? ORDER BY native_id, unit, qid", (battery,)).fetchall()


def label(tmp_path, native_id, present, at="now"):
    """One review verdict on user_correction, in a review run of its own."""
    conn = fi.open_findings(tmp_path)
    run_id = fi.start_run(conn, "transcript-review", None, "{}")
    conn.execute("INSERT INTO review_flags (run_id, harness, native_id, category, present,"
                 " confidence, created_at) VALUES (?, 'claude', ?, 'user_correction', ?, 'high', ?)",
                 (run_id, native_id, present, at))
    conn.commit()
    conn.close()


def test_run_without_a_decision_url_skips_and_succeeds(index, tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("DECISION_URL", raising=False)
    index.close()
    assert run(tmp_path, "--battery", "turn") == 0
    assert "DECISION_URL is not set" in capsys.readouterr().out
    assert not (tmp_path / "findings.db").exists()


def test_turn_battery_asks_each_human_turn_of_main_sessions_only(index, tmp_path, asked):
    s = index.session("main1")
    index.user(s, "fix the build")
    index.assistant(s, "I changed the lockfile and the build passes now.")
    index.user(s, "<system-reminder>injected</system-reminder>")  # nothing human left
    index.user(s, "no, that broke prod")
    sub = index.session("sub1", kind="subagent")
    index.user(sub, "parent prompt, not a human")
    index.close()

    assert run(tmp_path, "--battery", "turn") == 0
    assert len(asked) == 2
    assert "USER MESSAGE:\nno, that broke prod" in asked[1]
    assert "the build passes now." in asked[1]  # the agent message it answers
    rows = answers(tmp_path, "turn")
    assert {(r[0], r[1]) for r in rows} == {("main1", "ord:1"), ("main1", "ord:4")}
    assert {r[2] for r in rows} == set(dc.BATTERIES["turn"])
    assert all(r[5] == "rev1" for r in rows)


def test_a_second_run_asks_only_what_is_new(index, tmp_path, asked):
    s = index.session("main1")
    index.user(s, "first")
    index.close()
    run(tmp_path, "--battery", "turn")
    asked.clear()
    assert run(tmp_path, "--battery", "turn") == 0
    assert asked == []


def test_session_battery_replaces_the_answer_when_the_session_grew(index, tmp_path, asked):
    s = index.session("main1")
    index.user(s, "write the docs")
    index.assistant(s, "Docs written.")
    index.conn.commit()
    run(tmp_path, "--battery", "session")
    assert "AGENT'S FINAL MESSAGE:\nDocs written." in asked[0]

    index.user(s, "also the README")
    index.assistant(s, "README written too.")
    index.close()
    run(tmp_path, "--battery", "session")
    units = {r[1] for r in answers(tmp_path, "session")}
    assert units == {"ord:1-4"}  # the old ord:1-2 answer is gone, not kept beside it


def test_reviewed_limits_the_run_to_labelled_sessions(index, tmp_path, asked):
    for name in ("a", "b"):
        index.user(index.session(name), f"task {name}")
    index.close()
    label(tmp_path, "b", present=1)
    run(tmp_path, "--battery", "turn", "--reviewed")
    assert asked == ["PREVIOUS AGENT MESSAGE (end):\n(none)\n\nUSER MESSAGE:\ntask b"]


def test_calibrate_scores_the_signal_against_the_latest_review_label(index, tmp_path, asked, capsys):
    for name in ("a", "b"):
        index.user(index.session(name), f"task {name}")
    index.close()
    run(tmp_path, "--battery", "turn")
    label(tmp_path, "a", present=0, at="1")
    label(tmp_path, "a", present=1, at="2")  # the later review wins
    label(tmp_path, "b", present=0, at="1")
    capsys.readouterr()
    assert dc.main(["--dest", str(tmp_path), "calibrate", "--battery", "turn"]) == 0
    out = capsys.readouterr().out
    assert "2 sessions, 1 labelled present" in out
    # both score 0.9: at 0.5 both are flagged and one agrees; at 0.95 none are flagged
    assert any(line.split()[:5] == ["0.5", "2", "1", "0.50", "1.00"] for line in out.splitlines())
    assert any(line.split()[:3] == ["0.95", "0", "0"] for line in out.splitlines())


def test_rollup_splits_nouls_into_yes_no_unsure(index, tmp_path, asked, capsys):
    index.user(index.session("a"), "go")
    index.close()
    run(tmp_path, "--battery", "turn")
    capsys.readouterr()
    assert dc.main(["--dest", str(tmp_path), "rollup", "--battery", "turn"]) == 0
    out = capsys.readouterr().out
    assert "yes 1  no 0  unsure 0" in out
    assert "new_task 1" in out


def test_ask_puts_the_first_state_top_level_and_maps_the_rest_back_in_order(monkeypatch):
    sent = {}

    def fake_post(url, body):
        sent.update(body)
        a = lambda p: {"q": {"type": "noul", "noul": p}}  # noqa: E731
        return {"answers": a(0.1), "states": {"1": {"answers": a(0.2)}, "2": {"answers": a(0.3)}},
                "meta": {"revision": "r"}}, "queue;dur=0.2"

    monkeypatch.setattr(dc, "post", fake_post)
    out, _ = dc.ask("http://x", {"q": {"type": "noul"}}, ["s0", "s1", "s2"])
    assert sent["state"] == "s0" and sent["model"] == dc.MODEL
    assert {k: v["state"] for k, v in sent["states"].items()} == {"1": "s1", "2": "s2"}
    assert [a["q"]["noul"] for a, _ in out] == [0.1, 0.2, 0.3]


def test_battery_hash_changes_when_a_question_changes(monkeypatch):
    before = dc.battery_hash("turn")
    changed = json.loads(json.dumps(dc.BATTERIES))
    changed["turn"]["frustration"]["instructions"] += " "
    monkeypatch.setattr(dc, "BATTERIES", changed)
    assert dc.battery_hash("turn") != before
