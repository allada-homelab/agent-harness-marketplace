#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Ask an optional decision model fixed batteries of yes/no and choice questions about sessions.

A decision model reads a short text and answers typed questions with probabilities, not prose:
cheap, fast, and only good at questions the text answers outright. This script renders short
states from the index (one per human turn, one per session), sends each battery as one fixed
unit, and stores the raw answers in `findings.db` beside the sweep's and the review's. Nothing
else in the module depends on it: with `$DECISION_URL` unset it says so and exits 0.

Batteries are fixed on purpose: on a text-only request the model sees every question in the
batch, so an answer depends on its neighbours. A battery's hash is stored with every answer and
a changed battery is a new battery — thresholds calibrated on the old one do not carry over.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "transcript-review"))
import review  # noqa: E402  sibling: dest resolution, the index connection, findings.db, rendering helpers
from signals import human_text  # noqa: E402  review put the ingest dir on sys.path

SKILL = "transcript-decide"
# The gateway alias the request routes on; the URL is the gateway's base, e.g. https://host.
MODEL = "decision-default"
PATH = "/v1/systemone"
TIMEOUT = 120  # a full batch of long states is ~10 s of compute; queueing behind others adds more
RETRY_STATUSES = (429, 503)  # busy, or the model is still loading after a swap
RETRY_FOR = 180  # seconds: a cold start is ~35 s, a deploy longer
FLOOR = 0.801  # a noul is decided only past this; inside the band the model sat near a coin flip
# One request at a time, half the server's max_num_seqs (32): the card is shared, and rows past
# that queue in front of every other caller (measured: 4x32 in flight put 40 s of queue on them).
STATES_PER_REQUEST = 16
PREV_CHARS, TURN_CHARS = 500, 4000
REQUEST_CHARS, REPORT_CHARS = 2000, 6000  # with the caps every state stays far under the token limit

NO_CORRECTION = "The user continues, approves, answers or asks something new; nothing the agent did is called wrong."
BATTERIES = {
    "turn": {
        "intent": {
            "type": "choice",
            "instructions": "What is the user doing in this message?",
            "criteria": {
                "new_task": "Starts a new, unrelated task.",
                "follow_up": "Adds the next step or a new requirement to the current work.",
                "correction": "Says the agent did, assumed or said something wrong, or tells it to stop or undo.",
                "approval": "Approves or tells the agent to go ahead, with nothing new to do.",
                "answers_agent": "Answers a question the agent asked.",
                "asks_question": "Asks the agent a question.",
                "other": "None of these.",
            },
        },
        "corrects_agent": {
            "type": "noul",
            "instructions": "Does the user say the agent did, assumed or said something wrong?",
            "criteria": {
                "false": NO_CORRECTION,
                "true": "The user points out a mistake, a wrong assumption, or work the agent should not have done.",
            },
        },
        "frustration": {
            "type": "noul",
            "instructions": "Does the user sound frustrated or impatient with the agent?",
            "criteria": {"false": "Neutral or positive tone.", "true": "Irritated, impatient or exasperated tone."},
        },
        "grants_permission": {
            "type": "noul",
            "instructions": "Does the user give the agent permission to take an action it asked about or proposed?",
            "criteria": {
                "false": "No permission is given for a proposed action.",
                "true": "The user says yes, go, do it, merge, push or similar to a proposed action.",
            },
        },
    },
    "session": {
        "claimed_outcome": {
            "type": "choice",
            "instructions": "What does the agent's final message say about the user's request?",
            "criteria": {
                "completed": "Says the requested work is done or the question is answered.",
                "partial": "Says some of the work is done and some remains.",
                "blocked": "Says it cannot continue because of an error, missing access or missing information.",
                "asks_user": "Ends by asking the user to choose or confirm something before it continues.",
                "unclear": "Does not say how the request stands.",
            },
        },
        "claims_tests_passed": {
            "type": "noul",
            "instructions": "Does the final message claim that tests, a build or a check passed?",
            "criteria": {"false": "No claim that a test, build or check passed.", "true": "Claims a test, build or check passed."},
        },
        "claims_shipped": {
            "type": "noul",
            "instructions": "Does the final message claim that something was committed, pushed, merged or deployed?",
            "criteria": {"false": "Nothing is said to be committed, pushed, merged or deployed.",
                         "true": "Says a commit, push, merge or deploy happened."},
        },
        "lists_open_items": {
            "type": "noul",
            "instructions": "Does the final message list work that is still open, owed or left for later?",
            "criteria": {"false": "No open or remaining work is listed.", "true": "Lists remaining, owed or follow-up work."},
        },
        "task_kind": {
            "type": "choice",
            "instructions": "What kind of task did the user ask for?",
            "criteria": {
                "bug_fix": "Fix something broken.",
                "feature": "Build or add something new.",
                "refactor": "Restructure or clean up existing code without changing behaviour.",
                "research": "Answer a question, investigate or explain; no change asked for.",
                "ops": "Deploy, operate, monitor or repair a running system.",
                "config": "Change configuration, infrastructure or tooling setup.",
                "docs": "Write or edit documentation or prose.",
                "review": "Review code, a PR or a design.",
                "other": "None of these.",
            },
        },
        "touches_live_systems": {
            "type": "noul",
            "instructions": "Did the task touch a live or production system (a deploy, a running service, real data)?",
            "criteria": {"false": "Only code, files or local work.", "true": "A deploy, a running service or live data was involved."},
        },
    },
}

# What `calibrate` compares against: a decision signal per session vs the review's category label.
CALIBRATION = {
    "turn": [("max corrects_agent over the session's turns", "user_correction",
              "SELECT harness, native_id, max(value) FROM decision_answers"
              " WHERE battery = 'turn' AND qid = 'corrects_agent' AND battery_hash = ?"
              " GROUP BY harness, native_id")],
    "session": [
        ("P(claimed_outcome in blocked, asks_user)", "unresolved_end",
         "SELECT harness, native_id, coalesce(json_extract(probabilities, '$.blocked'), 0)"
         " + coalesce(json_extract(probabilities, '$.asks_user'), 0) FROM decision_answers"
         " WHERE battery = 'session' AND qid = 'claimed_outcome' AND battery_hash = ?"),
        ("P(claimed_outcome = partial)", "stopped_short",
         "SELECT harness, native_id, coalesce(json_extract(probabilities, '$.partial'), 0)"
         " FROM decision_answers WHERE battery = 'session' AND qid = 'claimed_outcome'"
         " AND battery_hash = ?"),
    ],
}
THRESHOLDS = (0.5, 0.7, 0.8, 0.9, 0.95, 0.99)


def battery_hash(name: str) -> str:
    return hashlib.sha256(json.dumps(BATTERIES[name], sort_keys=True).encode()).hexdigest()[:12]


# ------------------------------------------------------------------- states


def human_turns(conn, session_id: int, harness: str) -> list[tuple[str, str]]:
    """(unit, state) per human turn: the turn plus the end of the assistant text before it."""
    out, prev = [], ""
    for ord_, role, text in conn.execute(
        "SELECT ord, role, text FROM messages WHERE session_id = ? AND injected = 0"
        " AND role IN ('user', 'assistant') ORDER BY ord, id",
        (session_id,),
    ):
        text = text or ""
        if role == "assistant":
            if text.strip():
                prev = text
            continue
        clean = human_text(text, harness)
        if not clean:
            continue
        state = (f"PREVIOUS AGENT MESSAGE (end):\n{review.normalize(prev)[-PREV_CHARS:] or '(none)'}"
                 f"\n\nUSER MESSAGE:\n{clean[:TURN_CHARS]}")
        out.append((f"ord:{ord_}", state))
    return out


def session_state(conn, session_id: int, harness: str) -> list[tuple[str, str]]:
    """One unit: the first request and the final report, keyed by both ords so a resumed
    session that grew a new final report is asked again."""
    first = None
    for ord_, text in conn.execute(
        "SELECT ord, text FROM messages WHERE session_id = ? AND injected = 0 AND role = 'user'"
        " ORDER BY ord, id",
        (session_id,),
    ):
        clean = human_text(text, harness)
        if clean:
            first = (ord_, clean)
            break
    final_text, final_call = review.final_report(conn, session_id)
    report = None
    if final_call:
        report = conn.execute("SELECT ord FROM messages m JOIN tool_calls t ON t.message_id = m.id"
                              " WHERE t.id = ?", (final_call[0],)).fetchone()[0], final_call[1]
    elif final_text:
        report = conn.execute("SELECT ord FROM messages WHERE id = ?",
                              (final_text[0],)).fetchone()[0], final_text[1]
    if first is None or report is None:
        return []
    state = (f"USER'S FIRST REQUEST:\n{first[1][:REQUEST_CHARS]}"
             f"\n\nAGENT'S FINAL MESSAGE:\n{(report[1] or '')[:REPORT_CHARS]}")
    return [(f"ord:{first[0]}-{report[0]}", state)]


RENDER = {"turn": (human_turns, "main"), "session": (session_state, None)}


# ------------------------------------------------------------------- client


def post(url: str, body: dict) -> tuple[dict, str]:
    """(body, Server-Timing) of one request, retrying only what a retry can fix: busy, loading,
    unreachable. A high `queue` with a normal `forward` means another caller's backlog."""
    deadline = time.monotonic() + RETRY_FOR
    delay = 1.0
    while True:
        req = urllib.request.Request(url + PATH, json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.load(r), r.headers.get("Server-Timing", "")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            if e.code not in RETRY_STATUSES or time.monotonic() > deadline:
                raise SystemExit(f"decision model answered HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if time.monotonic() > deadline:
                raise SystemExit(f"decision model at {url} unreachable: {e}") from e
        time.sleep(delay)
        delay = min(delay * 2, 16)


def ask(url: str, questions: dict, states: list[str]) -> tuple[list[tuple[dict, str]], str]:
    """(answers, revision) per state, in order, and the Server-Timing. The first state rides
    top-level: the server refuses a `states` batch without one."""
    body = {"model": MODEL, "state": states[0], "questions": questions,
            "options": {"return_meta": True}}
    if len(states) > 1:
        body["states"] = {str(i): {"state": s, "questions": questions}
                          for i, s in enumerate(states[1:], 1)}
    resp, timing = post(url, body)
    revision = (resp.get("meta") or {}).get("revision", "")
    answers = [resp["answers"]] + [resp["states"][str(i)]["answers"] for i in range(1, len(states))]
    for a in answers:
        for qid, ans in a.items():
            if "error" in ans:  # never expected on systemone, which fails the request instead
                raise SystemExit(f"question {qid} failed: {ans}")
    return [(a, revision) for a in answers], timing


# ------------------------------------------------------------------- commands


def cmd_run(args) -> int:
    url = os.environ.get("DECISION_URL", "").strip().rstrip("/")
    if not url:
        print("DECISION_URL is not set: no decision model configured, nothing to do.")
        return 0
    dest = review.resolve_dest(args.dest)
    conn = review.connect(dest)
    fconn = review.load_findings().open_findings(dest)
    render, kind = RENDER[args.battery]
    bhash = battery_hash(args.battery)
    questions = BATTERIES[args.battery]

    sql = "SELECT id, harness, native_id FROM sessions WHERE 1 = 1"
    params: list = []
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    if args.since:
        sql += " AND started_at >= ?"
        params.append(args.since)
    sql += " ORDER BY started_at DESC"

    done = {(h, n, u) for h, n, u in fconn.execute(
        "SELECT harness, native_id, unit FROM decision_answers WHERE battery = ? AND battery_hash = ?",
        (args.battery, bhash))}
    reviewed = {tuple(r) for r in fconn.execute("SELECT DISTINCT harness, native_id FROM review_flags")}
    pending: list[tuple[str, str, str, str]] = []  # (harness, native_id, unit, state)
    sessions = [r for r in conn.execute(sql, params) if not args.reviewed or tuple(r[1:]) in reviewed]
    for session_id, harness, native_id in sessions[:args.limit]:
        for unit, state in render(conn, session_id, harness):
            if (harness, native_id, unit) not in done:
                pending.append((harness, native_id, unit, state))
    print(f"{args.battery} battery {bhash}: {len(pending)} states to ask")
    if not pending:
        return 0

    run_id = review.load_findings().start_run(fconn, SKILL, MODEL, {"battery": args.battery, "url": url})
    batches = [pending[i:i + STATES_PER_REQUEST] for i in range(0, len(pending), STATES_PER_REQUEST)]
    started, sent = time.monotonic(), 0
    for batch in batches:
        results, timing = ask(url, questions, [p[3] for p in batch])
        for (harness, native_id, unit, _), (answers, revision) in zip(batch, results):
            if args.battery == "session":  # one unit per session: a new one replaces the old
                fconn.execute("DELETE FROM decision_answers WHERE battery = ? AND harness = ?"
                              " AND native_id = ?", (args.battery, harness, native_id))
            fconn.executemany(
                "INSERT OR REPLACE INTO decision_answers (run_id, harness, native_id, battery,"
                " battery_hash, unit, qid, value, label, probabilities, revision, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(run_id, harness, native_id, args.battery, bhash, unit, qid,
                  a["noul"] if a["type"] == "noul" else a["confidence"], a.get("choice"),
                  json.dumps(a["probabilities"]) if "probabilities" in a else None,
                  revision, review.now_iso()) for qid, a in answers.items()],
            )
        fconn.commit()
        sent += len(batch)
        queue = re.search(r"queue;dur=([0-9.]+)", timing)
        print(f"  {sent}/{len(pending)} states, {time.monotonic() - started:.0f}s"
              f" (server queue {float(queue[1]) if queue else 0:.0f} ms)", file=sys.stderr)
    print(f"run {run_id}: {sent} states answered in {time.monotonic() - started:.0f}s; "
          f"store {review.findings_path(dest)}")
    return 0


def cmd_rollup(args) -> int:
    """Per question: how many answers, and how they split; a noul inside the FLOOR band is `unsure`."""
    dest = review.resolve_dest(args.dest)
    fconn = review.load_findings().open_findings(dest, readonly=True)
    bhash = battery_hash(args.battery)
    rows = []
    for qid in BATTERIES[args.battery]:
        if BATTERIES[args.battery][qid]["type"] == "noul":
            n, yes, no = fconn.execute(
                "SELECT count(*), sum(value >= ?), sum(value <= ?) FROM decision_answers"
                " WHERE battery = ? AND battery_hash = ? AND qid = ?",
                (FLOOR, 1 - FLOOR, args.battery, bhash, qid)).fetchone()
            rows.append([qid, n, f"yes {yes or 0}  no {no or 0}  unsure {n - (yes or 0) - (no or 0)}"])
        else:
            split = fconn.execute(
                "SELECT label, count(*) FROM decision_answers WHERE battery = ? AND battery_hash = ?"
                " AND qid = ? GROUP BY label ORDER BY 2 DESC",
                (args.battery, bhash, qid)).fetchall()
            rows.append([qid, sum(c for _, c in split), "  ".join(f"{k} {c}" for k, c in split)])
    print(f"{args.battery} battery {bhash}")
    print(review.render_table(["question", "answers", "split"], rows))
    return 0


def cmd_calibrate(args) -> int:
    """Agreement with the review's latest verdict per session, at each threshold.

    The review labels are themselves model output, so this measures agreement, not truth.
    """
    dest = review.resolve_dest(args.dest)
    fconn = review.load_findings().open_findings(dest, readonly=True)
    bhash = battery_hash(args.battery)
    for signal, category, sql in CALIBRATION[args.battery]:
        scores = {(h, n): v for h, n, v in fconn.execute(sql, (bhash,))}
        labels = {(h, n): p for h, n, p in fconn.execute(
            "SELECT harness, native_id, present FROM review_flags r WHERE category = ?"
            " AND created_at = (SELECT max(created_at) FROM review_flags"
            " WHERE harness = r.harness AND native_id = r.native_id AND category = r.category)",
            (category,))}
        both = [(scores[k], labels[k]) for k in scores.keys() & labels.keys()]
        positives = sum(p for _, p in both)
        print(f"\n{signal}  vs review {category}: {len(both)} sessions, {positives} labelled present")
        rows = []
        for t in THRESHOLDS:
            tp = sum(1 for s, p in both if s >= t and p)
            flagged = sum(1 for s, _ in both if s >= t)
            rows.append([t, flagged, tp, f"{tp / flagged:.2f}" if flagged else "-",
                         f"{tp / positives:.2f}" if positives else "-"])
        print(review.render_table(["threshold", "flagged", "agree", "precision", "recall"], rows))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dest", help="cache root (default: $AGENT_TRANSCRIPT_DIR or <cache>/agent-transcripts)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="ask a battery of every state not yet answered")
    r.add_argument("--battery", choices=BATTERIES, required=True)
    r.add_argument("--since", help="only sessions started at or after this ISO8601 time")
    r.add_argument("--limit", type=int, help="at most this many sessions, newest first")
    r.add_argument("--reviewed", action="store_true",
                   help="only sessions the review skill has labelled: the set `calibrate` scores")
    u = sub.add_parser("rollup", help="how each question's answers split")
    u.add_argument("--battery", choices=BATTERIES, required=True)
    c = sub.add_parser("calibrate", help="precision and recall against the review's labels")
    c.add_argument("--battery", choices=CALIBRATION, required=True)
    args = p.parse_args(argv)
    return {"run": cmd_run, "rollup": cmd_rollup, "calibrate": cmd_calibrate}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
