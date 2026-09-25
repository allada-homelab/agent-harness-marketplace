#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Queue, render and record semantic review of one transcript session at a time.

The deterministic sweep finds what SQL can see. This script does everything mechanical
around what it cannot: it picks candidate sessions, renders ONE capped, boilerplate-stripped
view of a session for a model to read, validates the verdict the model writes (every quote
must really appear in that session — the guard against a small model inventing evidence) and
rolls the recorded findings up. The model never opens a raw transcript and never writes SQL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DEST_NAME = "agent-transcripts"
SKILL = "transcript-review"
QUOTE_MAX = 200
SHORT_USER = 300  # a correction is a short turn; a long one is a new instruction
CONFIDENCES = ("low", "medium", "high")
# A session's final report is what an unverified_claim is judged against, and a subagent
# delivers it as tool-call arguments — the 60-char args cap turned justified reports into
# "claims with no evidence". It gets its own cap and is always kept by the budget.
FINAL_REPORT_TOOLS = ("SubagentHandback",)
FINAL_REPORT_CHARS = 6000
GREP_LIMIT = 20
GREP_CONTEXT = 160

# One line each: this is what the model answers, and the whole closed list must be answered.
RUBRIC = {
    "repeat_failing_approach":
        "The same approach was retried after it had already failed, instead of changing tack.",
    "tool_misuse":
        "A tool was called wrongly: bad arguments, the wrong tool, or against its contract.",
    "tool_contract_friction":
        "The tool worked as documented but its interface fought the task (unclear error, "
        "missing option, output that had to be worked around).",
    "user_correction":
        "The user had to correct, interrupt or redirect the assistant.",
    "unrequested_scope":
        "Work was done that the user did not ask for.",
    "stopped_short":
        "The assistant stopped before the requested work was done, without saying it was blocked.",
    "unverified_claim":
        "Something was claimed done, tested or working with no evidence of it in the session.",
    "ignored_instruction":
        "An explicit instruction given earlier in the session was ignored or contradicted.",
    "boundary_workaround":
        "A permission, sandbox or policy boundary was worked around instead of reported.",
    "wasted_exploration":
        "Long reading or searching that did not inform the outcome.",
    "unnecessary_question":
        "The user was asked something the session already answered or the assistant could "
        "have determined itself.",
    "unresolved_end":
        "The session ends unresolved: an open question, a failing command, or a user turn "
        "with no reply.",
    "secret_exposure":
        "A secret, token, key or credential appears in a command, a file or an output.",
}
CATEGORIES = tuple(RUBRIC)

# A finding that fits no category is stored under this category and is never counted in
# the category rates — it is a cue for the next category, not a category itself.
UNCLASSIFIED = "__unclassified__"

# Injected text that is not the user talking. Learned by reading the live index: on claude
# and dsh roughly half of all "user" characters are one of these. Each entry is
# (label, harness or "*", regex); a match is replaced by `[stripped: <label>]`.
# Block forms come first; the `.*` forms run to the end of the message, which is how the
# harness appends them. Tune here, not in the renderer.
BOILERPLATE = (
    ("system-reminder", "*", re.compile(r"<system-reminder>.*?</system-reminder>", re.S)),
    ("system-reminder", "*", re.compile(r"<system-reminder>.*", re.S)),  # truncated block
    ("task-notification", "claude",
     re.compile(r"<task-notification>.*?</task-notification>", re.S)),
    ("task-notification", "claude", re.compile(r"<task-notification>.*", re.S)),
    ("slash-command", "claude",
     re.compile(r"<command-(name|message|args)>.*?</command-\1>", re.S)),
    ("local-command-output", "claude",
     re.compile(r"<local-command-(stdout|stderr|caveat)>.*?</local-command-\1>", re.S)),
    ("skill-body", "claude", re.compile(r"^Base directory for this skill:.*", re.S | re.M)),
    ("hook-output", "claude", re.compile(
        r"^(?:Stop|SubagentStop|PreToolUse|PostToolUse|PreCompact|SessionStart|SessionEnd|"
        r"UserPromptSubmit|Notification)\s+hook\s+(?:feedback|error|success|output|blocked)\b.*",
        re.S | re.M)),
    ("background-task", "claude",
     re.compile(r"^\[SYSTEM NOTIFICATION - NOT USER INPUT\].*", re.S | re.M)),
    ("compact-summary", "claude",
     re.compile(r"^This session is being continued from a previous conversation.*", re.S | re.M)),
    ("runtime-context", "dsh", re.compile(r"^Current runtime context\..*", re.S | re.M)),
    ("checkpoint", "dsh",
     re.compile(r"^This is an automatically generated checkpoint.*", re.S | re.M)),
    ("background-subagent", "dsh",
     re.compile(r"^Background subagent \S+ (?:finished|reported)\b.*", re.S | re.M)),
    ("background-job", "dsh", re.compile(r"^background job \S+ .*", re.S | re.M)),
    ("goal-blocked", "dsh", re.compile(r"<goal_blocked>.*?</goal_blocked>", re.S)),
)

# A short user turn that matches this is the user pulling the reins.
CORRECTION_RE = re.compile(
    r"\bno,|\bstop\b|\bwrong\b|\bagain\b|\bI said\b|\bdon['’]t\b|\bundo\b|\brevert\b",
    re.I,
)


# ------------------------------------------------------------------- plumbing


def resolve_dest(cli_dest: str | None) -> Path:
    """--dest > $AGENT_TRANSCRIPT_DIR > <user cache dir>/agent-transcripts."""
    if cli_dest:
        return Path(cli_dest).expanduser()
    if os.environ.get("AGENT_TRANSCRIPT_DIR"):
        return Path(os.environ["AGENT_TRANSCRIPT_DIR"]).expanduser()
    cache = os.environ.get("XDG_CACHE_HOME")
    root = Path(cache).expanduser() if cache else Path.home() / ".cache"
    return root / DEFAULT_DEST_NAME


def connect(dest_root: Path) -> sqlite3.Connection:
    """Read-only: a review can never lock or corrupt an index an ingest is writing."""
    db = dest_root / "transcripts.db"
    if not db.exists():
        raise SystemExit(f"no index at {db}; run the transcript-ingest skill first")
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def load_findings():
    """The findings.db helper ships beside the sweep; both skills write the same database."""
    sibling = Path(__file__).resolve().parent.parent / "transcript-sweep"
    if str(sibling) not in sys.path:
        sys.path.insert(0, str(sibling))
    try:
        import findings  # noqa: PLC0415
    except ImportError as exc:  # fail loud: a silent skip would lose every recorded finding
        raise SystemExit(
            f"cannot import findings.py from {sibling} ({exc}); the transcript-sweep skill "
            "ships it and this skill writes the same findings.db"
        ) from exc
    return findings


def findings_path(dest_root: Path) -> Path:
    return dest_root / "findings.db"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def render_table(headers: list[str], rows: list[list]) -> str:
    cells = [[("" if v is None else str(v)) for v in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in cells:
        widths = [max(w, len(c)) for w, c in zip(widths, row)]
    out = ["  ".join(h.ljust(w) for h, w in zip(headers, widths)).rstrip()]
    out += ["  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip() for row in cells]
    return "\n".join(out)


def one_line(text: str, limit: int) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def normalize(text: str) -> str:
    return " ".join((text or "").split())


# -------------------------------------------------------------- boilerplate


def human_text(text: str, harness: str) -> str:
    """What is left of a user turn once the harness's injected blocks are removed."""
    clean, _ = strip_boilerplate(text or "", harness)
    return re.sub(r"\[stripped: [^\]]+\]", "", clean).strip()


def strip_boilerplate(text: str, harness: str) -> tuple[str, int]:
    """Replace injected blocks with `[stripped: label]`. Returns (text, blocks stripped)."""
    stripped = 0
    for label, scope, pattern in BOILERPLATE:
        if scope not in ("*", harness):
            continue
        text, n = pattern.subn(f"[stripped: {label}]", text or "")
        stripped += n
    return text, stripped


# ----------------------------------------------------------------- sessions


def resolve_session(conn: sqlite3.Connection, ident: str) -> sqlite3.Row:
    """A session by native_id or numeric id; ambiguity is an error, not a guess."""
    rows = conn.execute(
        "SELECT id, harness, native_id, cwd, project_key, kind, started_at, model"
        " FROM sessions WHERE native_id = ? OR id = ?",
        (ident, int(ident) if ident.isdigit() else -1),
    ).fetchall()
    if not rows:
        raise SystemExit(f"no session {ident!r} in the index")
    if len(rows) > 1:
        seen = ", ".join(f"{r[1]}/{r[2]} (id {r[0]})" for r in rows)
        raise SystemExit(f"{ident!r} matches several sessions: {seen}; pass the numeric id")
    return rows[0]


def sweep_kinds(dest: Path, harness: str, native_id: str) -> list[tuple[str, int, str]]:
    """(kind, count, severity) the sweep already recorded for this session, if any."""
    db = findings_path(dest)
    if not db.exists():
        return []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT kind, count, severity FROM sweep_flags WHERE harness = ? AND native_id = ?"
            " ORDER BY kind",
            (harness, native_id),
        ).fetchall()
    finally:
        conn.close()


# -------------------------------------------------------------------- queue


def sampled(seed: int, harness: str, native_id: str, fraction: float) -> bool:
    """Deterministic: the same seed picks the same sessions on every run, in any order."""
    if fraction <= 0:
        return False
    digest = hashlib.sha1(f"{seed}\0{harness}\0{native_id}".encode(), usedforsecurity=False)
    return int.from_bytes(digest.digest()[:8], "big") / 2**64 < fraction


def queue_candidates(conn, dest, *, threshold, sample, seed, harnesses, since, unreviewed):
    where, params = ["s.kind = 'main'"], []
    if since:
        where.append("s.started_at >= ?")
        params.append(since)
    if harnesses:
        where.append("s.harness IN (%s)" % ",".join("?" for _ in harnesses))
        params += list(harnesses)
    clause = " AND ".join(where)

    sessions = conn.execute(
        f"SELECT s.id, s.harness, s.native_id, s.started_at FROM sessions s WHERE {clause}"
        " ORDER BY s.id",
        params,
    ).fetchall()
    by_id = {row[0]: row for row in sessions}
    if not by_id:
        return []

    counts = dict(conn.execute(
        f"SELECT m.session_id, count(*) FROM messages m JOIN sessions s ON s.id = m.session_id"
        f" WHERE {clause} GROUP BY m.session_id",
        params,
    ).fetchall())

    # "ends on the user" means the user said something last, not that the harness appended a
    # system-reminder to the session; strip first and require a non-empty remainder.
    ends_on_user: set[int] = set()
    for session_id, role, text in conn.execute(
        f"SELECT m.session_id, m.role, m.text FROM messages m"
        f" JOIN sessions s ON s.id = m.session_id"
        f" JOIN (SELECT session_id, max(ord) AS mo FROM messages GROUP BY session_id) x"
        f"   ON x.session_id = m.session_id AND x.mo = m.ord"
        f" WHERE {clause}",
        params,
    ):
        if role == "user" and human_text(text or "", by_id[session_id][1]):
            ends_on_user.add(session_id)

    # Short user turns only: a correction is a sentence, not a briefing. The length bound
    # keeps this from pulling whole transcripts into memory; boilerplate is stripped first
    # because a two-word correction can arrive glued to a 4 KB system-reminder.
    corrections: dict[int, str] = {}
    for session_id, text in conn.execute(
        f"SELECT m.session_id, m.text FROM messages m JOIN sessions s ON s.id = m.session_id"
        f" WHERE {clause} AND m.role = 'user' AND length(m.text) <= 8000",
        params,
    ):
        if session_id in corrections:
            continue
        clean = human_text(text or "", by_id[session_id][1])
        if clean and len(clean) < SHORT_USER and CORRECTION_RE.search(clean):
            corrections[session_id] = one_line(clean, 60)

    issues: Counter = Counter()
    reviewed: set[tuple[str, str]] = set()
    fdb = findings_path(dest)
    if fdb.exists():
        fconn = sqlite3.connect(f"file:{fdb}?mode=ro", uri=True)
        try:
            for harness, native_id, total in fconn.execute(
                "SELECT harness, native_id, sum(count) FROM sweep_flags"
                " WHERE severity = 'issue' GROUP BY harness, native_id"
            ):
                issues[(harness, native_id)] = total or 0
            reviewed = {
                (h, n) for h, n in fconn.execute(
                    "SELECT DISTINCT harness, native_id FROM review_flags"
                )
            }
        finally:
            fconn.close()
    else:
        print(
            f"warning: no findings.db at {fdb}; run the transcript-sweep skill first — "
            "the issue-count criterion is skipped",
            file=sys.stderr,
        )

    out = []
    for session_id, harness, native_id, started_at in sessions:
        if unreviewed and (harness, native_id) in reviewed:
            continue
        why, detail = [], {}
        issue_count = issues.get((harness, native_id), 0)
        if issue_count > threshold:
            why.append(f"issues={issue_count}")
        if session_id in ends_on_user:
            why.append("ends-on-user")
        if session_id in corrections:
            why.append("correction")
            detail["correction"] = corrections[session_id]
        if not why and sampled(seed, harness, native_id, sample):
            why.append("sample")
        if not why:
            continue
        out.append({
            "harness": harness,
            "native_id": native_id,
            "started_at": started_at,
            "messages": counts.get(session_id, 0),
            "issues": issue_count,
            "why": ",".join(why),
            **detail,
        })
    out.sort(key=lambda r: (-r["issues"], r["started_at"] or "", r["native_id"]))
    return out


def cmd_queue(args) -> int:
    dest = resolve_dest(args.dest)
    conn = connect(dest)
    rows = queue_candidates(
        conn, dest,
        threshold=args.issue_threshold, sample=args.sample, seed=args.seed,
        harnesses=args.harness, since=args.since, unreviewed=args.unreviewed,
    )[: args.limit]
    if args.json:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
        return 0
    if not rows:
        print("no candidate sessions")
        return 0
    print(render_table(
        ["harness", "native_id", "started_at", "messages", "why"],
        [[r["harness"], r["native_id"], r["started_at"], r["messages"], r["why"]] for r in rows],
    ))
    print(f"\n{len(rows)} candidates; review them one at a time with `view`")
    return 0


# --------------------------------------------------------------------- view


class Unit:
    """One message's rendered lines, plus the pair key that lets a run of them collapse."""

    def __init__(self, lines: list[str], messages: int = 1, key: tuple | None = None,
                 ord_: int | None = None):
        self.lines = lines
        self.messages = messages
        self.key = key
        self.ord = ord_
        self.repeats = 1
        self.final = False  # part of the final report: fit_budget always keeps it

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def size(self) -> int:
        return len(self.text) + 1


def user_lines(ord_: int, text: str, cap: int) -> list[str]:
    """`[ord] USER …`, capped at `cap` characters; continuation lines are indented.

    The cap is what makes --budget a bound: a pasted 600-line log is a single user message,
    and without it one turn can outweigh the whole session.
    """
    if len(text) > cap:
        text = text[:cap].rstrip() + " …[+%d chars]" % (len(text) - cap)
    lines = text.split("\n")
    return [f"[{ord_}] USER {lines[0]}"] + ["    " + line for line in lines[1:]]


def build_units(conn, session, *, assistant_chars, args_chars, result_chars, user_chars):
    """One Unit per message, in ord order; returns (units, stripped block count)."""
    session_id, harness = session[0], session[1]
    cap = max(assistant_chars, result_chars) + 1
    messages = conn.execute(
        "SELECT id, ord, role, CASE WHEN role = 'user' THEN text ELSE substr(text, 1, ?) END"
        " FROM messages WHERE session_id = ? ORDER BY ord, id",
        (cap, session_id),
    ).fetchall()
    calls: dict[int, list] = {}
    for call_id, message_id, name, arguments, is_error in conn.execute(
        "SELECT t.id, t.message_id, t.name, substr(t.arguments, 1, ?), t.is_error"
        " FROM tool_calls t JOIN messages m ON m.id = t.message_id WHERE m.session_id = ?"
        " ORDER BY t.id",
        (args_chars + 1, session_id),
    ):
        calls.setdefault(message_id, []).append((call_id, name, arguments, is_error))

    # The final report, uncapped by the per-unit limits: the last assistant text and the
    # last final-report tool call's arguments.
    final_text = conn.execute(
        "SELECT id, substr(text, 1, ?) FROM messages WHERE session_id = ? AND role = 'assistant'"
        " AND trim(coalesce(text, '')) != '' ORDER BY ord DESC, id DESC LIMIT 1",
        (FINAL_REPORT_CHARS + 1, session_id),
    ).fetchone()
    final_call = conn.execute(
        "SELECT t.id, substr(t.arguments, 1, ?) FROM tool_calls t"
        " JOIN messages m ON m.id = t.message_id WHERE m.session_id = ? AND t.name IN (%s)"
        " ORDER BY m.ord DESC, t.id DESC LIMIT 1" % ",".join("?" for _ in FINAL_REPORT_TOOLS),
        (FINAL_REPORT_CHARS + 1, session_id, *FINAL_REPORT_TOOLS),
    ).fetchone()

    units: list[Unit] = []
    stripped_blocks = 0
    for message_id, ord_, role, text in messages:
        text = text or ""
        if role == "user":
            clean, n = strip_boilerplate(text, harness)
            stripped_blocks += n
            clean = clean.strip() or "[empty]"
            units.append(Unit(user_lines(ord_, clean, user_chars), ord_=ord_))
        elif role == "assistant":
            lines = []
            final = False
            if final_text and final_text[0] == message_id:
                text, final = final_text[1] or "", True
                lines.append(f"[{ord_}] ASSISTANT {one_line(text, FINAL_REPORT_CHARS)}")
            elif text.strip():
                lines.append(f"[{ord_}] ASSISTANT {one_line(text, assistant_chars)}")
            key = None
            for call_id, name, arguments, is_error in calls.get(message_id, []):
                if final_call and final_call[0] == call_id:
                    snippet, final = one_line(final_call[1] or "", FINAL_REPORT_CHARS), True
                else:
                    snippet = one_line(arguments or "", args_chars)
                err = " ERR" if is_error else ""
                lines.append(f"[{ord_}] CALL {name} {snippet}{err}")
                key = (name, bool(is_error), snippet)
            if not lines:
                continue
            unit = Unit(lines, key=key if len(lines) == 1 and not final else None, ord_=ord_)
            unit.final = final
            units.append(unit)
        elif role == "tool_result":
            units.append(Unit([f"[{ord_}] RESULT {one_line(text, result_chars)}"], ord_=ord_))
        else:
            if text.strip():
                units.append(Unit([f"[{ord_}] {role.upper()} {one_line(text, assistant_chars)}"],
                                  ord_=ord_))
    return collapse(units), stripped_blocks


def body_of(unit: Unit) -> str:
    """A unit's first line without its `[ord] ` prefix — what two repeats have to share."""
    return unit.lines[0].split("] ", 1)[1]


def collapse(units: list[Unit]) -> list[Unit]:
    """Fold consecutive identical call/result pairs into one, marked ×N.

    The result is half the key: three identical calls answered "refused", "refused", "OK"
    are three different events and collapsing them would hide the one that worked.
    """
    out: list[Unit] = []
    i = 0
    while i < len(units):
        unit = units[i]
        follows_result = (
            unit.key is not None
            and i + 1 < len(units)
            and body_of(units[i + 1]).startswith("RESULT ")
        )
        if not follows_result:
            out.append(unit)
            i += 1
            continue
        result = units[i + 1]
        result_body = body_of(result)
        n, j = 1, i + 2
        while (
            j + 1 < len(units)
            and units[j].key == unit.key
            and body_of(units[j + 1]).startswith("RESULT ")
            and body_of(units[j + 1]) == result_body
        ):
            n += 1
            j += 2
        if n > 1:
            merged = Unit(
                [unit.lines[0] + f" ×{n}", result.lines[0] + f" ×{n}"], messages=2 * n,
                ord_=unit.ord,
            )
            out.append(merged)
        else:
            out += [unit, result]
        i = j
    return out


ELISION = "... [elided %d messages] ..."
ANCHOR_KINDS = ("error_streak", "retry_same_input_after_error", "tool_error")
ANCHOR_MAX = 8  # a session with fifty flagged errors still has to fit the budget
ANCHOR_WINDOW = 3  # messages kept either side of an anchor: the call, its result, the reply


def anchor_ords(conn, dest: Path, session_id: int, harness: str, native_id: str,
                limit: int = ANCHOR_MAX) -> list[int]:
    """Ords the sweep's issue evidence points at — the lines the elision must not cut.

    Without this a 12k-message session renders its first and last fifty messages and the
    judge never sees the errors the sweep flagged it for.
    """
    db = findings_path(dest)
    if not db.exists():
        return []
    fconn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        flags = fconn.execute(
            "SELECT kind, evidence FROM sweep_flags"
            " WHERE harness = ? AND native_id = ? AND severity = 'issue'",
            (harness, native_id),
        ).fetchall()
    finally:
        fconn.close()

    def rank(kind: str) -> int:
        return ANCHOR_KINDS.index(kind) if kind in ANCHOR_KINDS else len(ANCHOR_KINDS)

    message_ids: list[int] = []
    for _kind, evidence in sorted(flags, key=lambda f: (rank(f[0]), f[0])):
        try:
            items = json.loads(evidence) if evidence else []
        except ValueError:
            continue
        for item in items if isinstance(items, list) else []:
            mid = item.get("message_id") if isinstance(item, dict) else None
            if isinstance(mid, int) and mid not in message_ids:
                message_ids.append(mid)
    message_ids = message_ids[:limit]
    if not message_ids:
        return []
    # An index rebuild renumbers message ids, so an evidence id that no longer exists is
    # simply not an anchor.
    found = dict(conn.execute(
        "SELECT id, ord FROM messages WHERE session_id = ? AND id IN (%s)"
        % ",".join("?" for _ in message_ids),
        [session_id, *message_ids],
    ).fetchall())
    return sorted({found[mid] for mid in message_ids if mid in found})


def fit_budget(units: list[Unit], budget: int, anchors=()) -> list[int]:
    """Choose the unit indices to show: the head, the tail and a window around each anchor.

    Returns the kept indices in order; the caller marks every gap between them. The first
    unit is the opening user turn and the final report is what the session claims — the
    two things a reviewer cannot judge it without — so both are kept even over budget.
    """
    if not units:
        return []
    if sum(u.size() for u in units) <= budget:
        return list(range(len(units)))
    reserve = len(ELISION) + 8
    final = {i for i, u in enumerate(units) if u.final and i != 0}
    keep = {0} | final
    used = units[0].size() + sum(units[i].size() + reserve for i in final)
    for anchor in anchors:
        window = [
            i for i, u in enumerate(units)
            if u.ord is not None and abs(u.ord - anchor) <= ANCHOR_WINDOW and i not in keep
        ]
        cost = sum(units[i].size() for i in window) + reserve
        if not window or used + cost > budget:
            continue
        keep.update(window)
        used += cost
    lo, hi = 1, len(units) - 1
    take_front = True
    while lo <= hi:
        i = lo if take_front else hi
        if i not in keep:
            if used + units[i].size() + reserve > budget:
                break
            keep.add(i)
            used += units[i].size()
        if take_front:
            lo += 1
        else:
            hi -= 1
        take_front = not take_front
    return sorted(keep)


def cmd_view(args) -> int:
    dest = resolve_dest(args.dest)
    conn = connect(dest)
    session = resolve_session(conn, args.session)
    _id, harness, native_id, cwd, _project, kind, started_at, model = session

    units, stripped_blocks = build_units(
        conn, session,
        assistant_chars=args.assistant_chars,
        args_chars=args.args_chars,
        result_chars=args.result_chars,
        user_chars=args.user_chars,
    )
    anchors = anchor_ords(conn, dest, _id, harness, native_id)
    kept = fit_budget(units, args.budget, anchors)

    header = [
        f"session {native_id}  harness={harness}  kind={kind}  started={started_at}",
        f"model={model}  cwd={cwd}  messages={sum(u.messages for u in units)}",
    ]
    flags = sweep_kinds(dest, harness, native_id)
    if flags:
        header.append("sweep: " + "  ".join(f"{k}={c}({s})" for k, c, s in flags))
    if anchors:
        header.append("anchors (sweep evidence, ±%d messages kept): %s"
                      % (ANCHOR_WINDOW, ", ".join(str(a) for a in anchors)))

    body: list[str] = []
    previous = -1
    for i in kept:
        gap = sum(u.messages for u in units[previous + 1:i])
        if gap:
            body.append(ELISION % gap)
        body.append(units[i].text)
        previous = i
    trailing = sum(u.messages for u in units[previous + 1:])
    if trailing:
        body.append(ELISION % trailing)

    out = "\n".join(header + [""] + body)
    print(out)
    print(
        f"\nview: {len(out)} chars, {sum(units[i].messages for i in kept)} messages shown, "
        f"{stripped_blocks} stripped blocks"
    )
    return 0


# --------------------------------------------------------------------- grep


def cmd_grep(args) -> int:
    """Search one whole session — elided messages included — for a claim's evidence.

    Prints `[ord] ROLE snippet`, one line per matching message or call, capped. It exists
    so an unverified_claim can be checked against what the view elided, not to read the
    session: the snippets are as short as the view's own lines.
    """
    dest = resolve_dest(args.dest)
    conn = connect(dest)
    session = resolve_session(conn, args.session)
    session_id, harness = session[0], session[1]
    try:
        pattern = re.compile(args.pattern, re.I)
    except re.error as exc:
        print(f"bad pattern {args.pattern!r}: {exc}", file=sys.stderr)
        return 2

    def fields():
        for message_id, ord_, role, text in conn.execute(
            "SELECT id, ord, role, text FROM messages WHERE session_id = ? ORDER BY ord, id",
            (session_id,),
        ):
            if role == "user":  # the same stripping as the view and the quote check
                text = strip_boilerplate(text or "", harness)[0]
            yield ord_, role.upper(), text or ""
            for name, arguments in conn.execute(
                "SELECT name, arguments FROM tool_calls WHERE message_id = ? ORDER BY id",
                (message_id,),
            ):
                yield ord_, f"CALL {name}", arguments or ""

    shown = total = 0
    for ord_, label, text in fields():
        flat = normalize(text)
        match = pattern.search(flat)
        if not match:
            continue
        total += 1
        if shown >= args.limit:
            continue
        start = max(0, match.start() - args.context_chars // 2)
        snippet = flat[start:start + args.context_chars]
        print(f"[{ord_}] {label} {'…' if start else ''}{snippet}"
              f"{'…' if start + args.context_chars < len(flat) else ''}")
        shown += 1
    if not total:
        print("no matches")
    elif total > shown:
        print(f"... {total - shown} more matches not shown (raise --limit or narrow the pattern)")
    return 0


# ------------------------------------------------------------------- record


class Invalid(Exception):
    """A verdict the model wrote that this script refuses to store."""


def message_haystack(conn, session_id: int, ord_: int, harness: str) -> str | None:
    """Everything a quote for this ord may legitimately come from, or None if no such ord.

    User turns are stripped exactly as the view strips them: text the model never saw —
    a system-reminder the view rendered as `[stripped: …]` — is not evidence it read.
    """
    rows = conn.execute(
        "SELECT id, role, text FROM messages WHERE session_id = ? AND ord = ?",
        (session_id, ord_),
    ).fetchall()
    if not rows:
        return None
    parts = [
        strip_boilerplate(text or "", harness)[0] if role == "user" else (text or "")
        for _, role, text in rows
    ]
    for message_id, _role, _text in rows:
        for arguments, result_text in conn.execute(
            "SELECT t.arguments, r.text FROM tool_calls t"
            " LEFT JOIN messages r ON r.id = t.result_message_id WHERE t.message_id = ?",
            (message_id,),
        ):
            parts += [arguments or "", result_text or ""]
        for arguments, in conn.execute(
            "SELECT arguments FROM tool_calls WHERE result_message_id = ?", (message_id,)
        ):
            parts.append(arguments or "")
    return "\n".join(parts)


def quote_needle(quote: str) -> str:
    """The quote as it must appear in the message: a trailing truncation ellipsis is not text."""
    needle = normalize(quote)
    for tail in ("…", "..."):
        if needle.endswith(tail):
            return needle[: -len(tail)].strip()
    return needle


def validate(verdict, conn, session_id: int, harness: str) -> tuple[list[dict], dict | None]:
    if not isinstance(verdict, dict) or not isinstance(verdict.get("findings"), list):
        raise Invalid('verdict must be a JSON object with a "findings" list')
    seen: set[str] = set()
    rows = []
    for i, finding in enumerate(verdict["findings"]):
        where = f"findings[{i}]"
        if not isinstance(finding, dict):
            raise Invalid(f"{where}: must be an object")
        category = finding.get("category")
        if category not in RUBRIC:
            raise Invalid(f"{where}: unknown category {category!r}; run `review.py rubric`")
        if category in seen:
            raise Invalid(f"{where}: category {category!r} appears more than once")
        seen.add(category)
        present = finding.get("present")
        if present not in (0, 1):
            raise Invalid(f"{where} ({category}): present must be 0 or 1, got {present!r}")
        confidence = finding.get("confidence")
        if confidence not in CONFIDENCES:
            raise Invalid(
                f"{where} ({category}): confidence must be one of {'/'.join(CONFIDENCES)}"
            )
        ord_, quote = finding.get("evidence_ord"), finding.get("quote")
        if present == 1:
            if not isinstance(ord_, int) or isinstance(ord_, bool):
                raise Invalid(f"{where} ({category}): present=1 needs an integer evidence_ord")
            if not isinstance(quote, str) or not quote_needle(quote):
                raise Invalid(f"{where} ({category}): present=1 needs a quote from the view")
            if len(quote) > QUOTE_MAX:
                raise Invalid(
                    f"{where} ({category}): quote is {len(quote)} chars, the cap is {QUOTE_MAX}"
                )
            haystack = message_haystack(conn, session_id, ord_, harness)
            if haystack is None:
                raise Invalid(f"{where} ({category}): no message with ord {ord_} in this session")
            if quote_needle(quote) not in normalize(haystack):
                raise Invalid(
                    f"{where} ({category}): quote is not in message {ord_}; copy it verbatim "
                    "from the view"
                )
        elif ord_ is not None or quote is not None:
            raise Invalid(
                f"{where} ({category}): present=0 must have evidence_ord and quote null"
            )
        rows.append({
            "category": category,
            "present": present,
            "confidence": confidence,
            "evidence_ord": ord_,
            "quote": quote,
            "note": finding.get("note") or "",
        })
    missing = [c for c in CATEGORIES if c not in seen]
    if missing:
        raise Invalid(
            "every category must be answered, including the negatives; missing: "
            + ", ".join(missing)
        )

    # The optional escape hatch: a real finding that fits no category. It carries the same
    # evidence discipline as a present=1 category — a verbatim quote the recorder can find
    # in the session — but is stored separately and never counted in the category rates.
    unclassified = verdict.get("unclassified")
    if unclassified is not None:
        if not isinstance(unclassified, dict):
            raise Invalid(
                '"unclassified" must be an object with confidence, evidence_ord and a quote'
            )
        where = "unclassified"
        confidence = unclassified.get("confidence")
        if confidence not in CONFIDENCES:
            raise Invalid(f"{where}: confidence must be one of {'/'.join(CONFIDENCES)}")
        ord_ = unclassified.get("evidence_ord")
        if not isinstance(ord_, int) or isinstance(ord_, bool):
            raise Invalid(f"{where}: needs an integer evidence_ord")
        quote = unclassified.get("quote")
        if not isinstance(quote, str) or not quote_needle(quote):
            raise Invalid(f"{where}: needs a quote copied verbatim from the view")
        if len(quote) > QUOTE_MAX:
            raise Invalid(f"{where}: quote is {len(quote)} chars, the cap is {QUOTE_MAX}")
        haystack = message_haystack(conn, session_id, ord_, harness)
        if haystack is None:
            raise Invalid(f"{where}: no message with ord {ord_} in this session")
        if quote_needle(quote) not in normalize(haystack):
            raise Invalid(
                f"{where}: quote is not in message {ord_}; copy it verbatim from the view"
            )
        unclassified = {
            "confidence": confidence,
            "evidence_ord": ord_,
            "quote": quote,
            "note": unclassified.get("note") or "",
        }
    return rows, unclassified


def cmd_record(args) -> int:
    dest = resolve_dest(args.dest)
    findings = load_findings()
    fconn = findings.open_findings(dest)

    run_id = args.run_id
    if args.new_run:
        if not args.model:
            print("--new-run needs --model", file=sys.stderr)
            return 2
        run_id = findings.start_run(fconn, SKILL, args.model, json.dumps(vars(args), default=str))
        if not args.session:
            print(run_id)
            return 0
    if run_id is None:
        print("pass --run-id (or --new-run --model NAME to start one)", file=sys.stderr)
        return 2
    if not args.session:
        print("pass a session (native id or numeric id) to record against", file=sys.stderr)
        return 2
    if args.model and not args.new_run:
        row = fconn.execute("SELECT model FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            print(f"no run {run_id} in findings.db", file=sys.stderr)
            return 2
        if row[0] != args.model:
            print(f"run {run_id} was started by model {row[0]!r}, not {args.model!r}",
                  file=sys.stderr)
            return 2

    conn = connect(dest)
    session = resolve_session(conn, args.session)
    session_id, harness, native_id = session[0], session[1], session[2]

    raw = Path(args.file).expanduser().read_text(encoding="utf-8") if args.file else sys.stdin.read()
    try:
        verdict = json.loads(raw)
    except ValueError as exc:
        print(f"verdict is not valid JSON: {exc}", file=sys.stderr)
        return 2
    try:
        rows, unclassified = validate(verdict, conn, session_id, harness)
    except Invalid as exc:
        print(f"invalid verdict: {exc}", file=sys.stderr)
        return 2

    stamp = now_iso()
    # Delete and insert share one transaction: a re-recorded session is replaced, never
    # duplicated and never left half-written.
    fconn.execute(
        "DELETE FROM review_flags WHERE run_id = ? AND harness = ? AND native_id = ?",
        (run_id, harness, native_id),
    )
    fconn.executemany(
        "INSERT INTO review_flags (run_id, harness, native_id, category, present, confidence,"
        " evidence_ord, quote, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(run_id, harness, native_id, r["category"], r["present"], r["confidence"],
          r["evidence_ord"], r["quote"], r["note"], stamp) for r in rows],
    )
    if unclassified:
        fconn.execute(
            "INSERT INTO review_flags (run_id, harness, native_id, category, present,"
            " confidence, evidence_ord, quote, note, created_at)"
            " VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
            (run_id, harness, native_id, UNCLASSIFIED, unclassified["confidence"],
             unclassified["evidence_ord"], unclassified["quote"], unclassified["note"], stamp),
        )
    fconn.commit()
    present = sum(r["present"] for r in rows)
    suffix = " + 1 unclassified" if unclassified else ""
    print(
        f"recorded {len(rows)} findings ({present} present){suffix} for {harness}/{native_id} "
        f"in run {run_id}"
    )
    return 0


# ------------------------------------------------------------------ rollup


def session_meta(conn, keys: set[tuple[str, str]]) -> dict[tuple[str, str], tuple]:
    """(project_key, started_at, cwd) for the reviewed sessions only — a small set."""
    meta = {}
    for harness, native_id in keys:
        row = conn.execute(
            "SELECT project_key, started_at, cwd FROM sessions"
            " WHERE harness = ? AND native_id = ? ORDER BY id LIMIT 1",
            (harness, native_id),
        ).fetchone()
        meta[(harness, native_id)] = row or (None, None, None)
    return meta


def tool_for(conn, fconn, harness: str, native_id: str, ord_) -> str:
    """The tool a finding points at: the call in its evidence message, else the sweep's."""
    if ord_ is not None:
        row = conn.execute(
            "SELECT t.name FROM tool_calls t JOIN messages m ON m.id = t.message_id"
            " JOIN sessions s ON s.id = m.session_id"
            " WHERE s.harness = ? AND s.native_id = ? AND m.ord = ? LIMIT 1",
            (harness, native_id, ord_),
        ).fetchone()
        if row and row[0]:
            return row[0]
        row = conn.execute(
            "SELECT t.name FROM tool_calls t JOIN messages r ON r.id = t.result_message_id"
            " JOIN sessions s ON s.id = r.session_id"
            " WHERE s.harness = ? AND s.native_id = ? AND r.ord = ? LIMIT 1",
            (harness, native_id, ord_),
        ).fetchone()
        if row and row[0]:
            return row[0]
    names: Counter = Counter()
    for (evidence,) in fconn.execute(
        "SELECT evidence FROM sweep_flags WHERE harness = ? AND native_id = ?",
        (harness, native_id),
    ):
        try:
            items = json.loads(evidence) if evidence else []
        except ValueError:
            continue
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and item.get("name"):
                names[item["name"]] += 1
    return names.most_common(1)[0][0] if names else "(unknown)"


def cmd_rollup(args) -> int:
    dest = resolve_dest(args.dest)
    fconn = load_findings().open_findings(dest, readonly=True)
    conn = connect(dest)

    rows = fconn.execute(
        "SELECT harness, native_id, category, present, evidence_ord FROM review_flags"
    ).fetchall()
    if args.harness:
        rows = [r for r in rows if r[0] in args.harness]
    meta = session_meta(conn, {(r[0], r[1]) for r in rows})
    if args.since:
        rows = [r for r in rows if (meta[(r[0], r[1])][1] or "") >= args.since]
    if not rows:
        print("no recorded findings in this scope")
        return 0

    reviewed = {(r[0], r[1]) for r in rows}
    present_rows = [r for r in rows if r[3] == 1 and r[2] != UNCLASSIFIED]

    def bucket(row) -> str:
        harness, native_id, category, _present, ord_ = row
        if args.by == "category":
            return category
        if args.by == "tool":
            return tool_for(conn, fconn, harness, native_id, ord_)
        if args.by == "project":
            return meta[(harness, native_id)][0] or "(none)"
        started = meta[(harness, native_id)][1] or ""
        try:
            date = datetime.strptime(started[:10], "%Y-%m-%d")
        except ValueError:
            return "(undated)"
        return "%d-W%02d" % date.isocalendar()[:2]

    counts: Counter = Counter()
    sessions: dict[tuple[str, str], set] = {}
    for row in present_rows:
        key = (bucket(row), row[0])
        counts[key] += 1
        sessions.setdefault(key, set()).add((row[0], row[1]))

    table = [
        [key[0], key[1], count, len(sessions[key])]
        for key, count in counts.most_common()
        if count >= args.min
    ]
    print(render_table([args.by, "harness", "findings", "sessions"], table) if table
          else f"no {args.by} reached --min {args.min}")

    per_category: dict[str, set] = {}
    for harness, native_id, category, _present, _ord in present_rows:
        per_category.setdefault(category, set()).add((harness, native_id))
    rates = [
        [c, len(per_category.get(c, ())), f"{len(per_category.get(c, ())) / len(reviewed):.0%}"]
        for c in CATEGORIES
    ]
    print(f"\nsessions reviewed: {len(reviewed)}")
    print(render_table(["category", "sessions present", "rate"], rates))

    unclassified_sessions = {(r[0], r[1]) for r in rows if r[2] == UNCLASSIFIED}
    if unclassified_sessions:
        print(f"\nunclassified: {len(unclassified_sessions)} session(s) flagged as fitting "
              "no category — a cue for a new category, never a category rate")
    return 0


# ------------------------------------------------------------------- rubric


# The one copy of the example: SKILL.md shows it, `rubric` prints it, and a test records it.
# A two-entry sample would be a verdict `record` refuses — every category must be answered.
EXAMPLE_VERDICT = {
    "findings": [
        {"category": "repeat_failing_approach", "present": 1, "confidence": "high",
         "evidence_ord": 88, "quote": "npm ERR! peer dep missing",
         "note": "same install rerun four times unchanged"},
        {"category": "tool_misuse", "present": 0, "confidence": "high",
         "evidence_ord": None, "quote": None, "note": ""},
        {"category": "tool_contract_friction", "present": 0, "confidence": "low",
         "evidence_ord": None, "quote": None, "note": ""},
        {"category": "user_correction", "present": 1, "confidence": "high",
         "evidence_ord": 91, "quote": "no, stop reinstalling and read the lockfile",
         "note": "user had to interrupt"},
        {"category": "unrequested_scope", "present": 0, "confidence": "medium",
         "evidence_ord": None, "quote": None, "note": ""},
        {"category": "stopped_short", "present": 0, "confidence": "low",
         "evidence_ord": None, "quote": None, "note": ""},
        {"category": "unverified_claim", "present": 0, "confidence": "low",
         "evidence_ord": None, "quote": None, "note": ""},
        {"category": "ignored_instruction", "present": 0, "confidence": "medium",
         "evidence_ord": None, "quote": None, "note": ""},
        {"category": "boundary_workaround", "present": 0, "confidence": "high",
         "evidence_ord": None, "quote": None, "note": ""},
        {"category": "wasted_exploration", "present": 0, "confidence": "low",
         "evidence_ord": None, "quote": None, "note": ""},
        {"category": "unnecessary_question", "present": 0, "confidence": "low",
         "evidence_ord": None, "quote": None, "note": ""},
        {"category": "unresolved_end", "present": 0, "confidence": "medium",
         "evidence_ord": None, "quote": None, "note": ""},
        {"category": "secret_exposure", "present": 0, "confidence": "high",
         "evidence_ord": None, "quote": None, "note": ""},
    ]
}


def cmd_rubric(args) -> int:
    print("categories — answer every one, present 0 or 1:\n")
    print(render_table(["category", "means"], [[c, RUBRIC[c]] for c in CATEGORIES]))
    print("\nverdict JSON (one entry per category, all 13):\n")
    print(json.dumps(EXAMPLE_VERDICT, indent=2))
    print(
        "\npresent=1 requires evidence_ord (an ord printed in the view) and a quote of at most "
        f"{QUOTE_MAX} characters copied verbatim from that message; present=0 requires both "
        "of them to be null."
    )
    print(
        "\noptional escape hatch: when a real problem fits no category, add an \"unclassified\""
        " object with the same evidence discipline — it is recorded but never counted in the"
        " category rates, and is a cue for the next category:"
    )
    print(json.dumps({
        "unclassified": {
            "confidence": "high",
            "evidence_ord": 88,
            "quote": "npm ERR! peer dep missing",
            "note": "a failure mode none of the 13 categories names",
        }
    }, indent=2))
    return 0


# --------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dest", help="cache root (same resolution as the other transcript skills)")
    sub = ap.add_subparsers(dest="command", required=True)

    q = sub.add_parser("queue", help="candidate sessions worth reviewing")
    q.add_argument("--issue-threshold", type=int, default=5)
    q.add_argument("--sample", type=float, default=0.05,
                   help="fraction of the remaining sessions to sample (default 0.05)")
    q.add_argument("--seed", type=int, default=0, help="sampling seed; same seed, same sample")
    q.add_argument("--limit", type=int, default=200)
    q.add_argument("--harness", action="append", choices=["claude", "pi", "dsh"])
    q.add_argument("--since", help="only sessions started at or after this ISO8601 timestamp")
    q.add_argument("--unreviewed", action="store_true",
                   help="skip sessions that already have review findings")
    q.add_argument("--json", action="store_true", help="JSONL instead of a table")
    q.set_defaults(func=cmd_queue)

    v = sub.add_parser("view", help="one capped session view, for a model to read")
    v.add_argument("session", help="native id or numeric id")
    v.add_argument("--budget", type=int, default=8000, help="max characters (default 8000)")
    v.add_argument("--user-chars", type=int, default=2000,
                   help="max characters of one user turn (default 2000)")
    v.add_argument("--assistant-chars", type=int, default=400)
    v.add_argument("--args-chars", type=int, default=60)
    v.add_argument("--result-chars", type=int, default=160)
    v.set_defaults(func=cmd_view)

    g = sub.add_parser("grep", help="search one whole session, elided messages included")
    g.add_argument("session", help="native id or numeric id")
    g.add_argument("pattern", help="regular expression, case-insensitive")
    g.add_argument("--limit", type=int, default=GREP_LIMIT,
                   help=f"max lines printed (default {GREP_LIMIT})")
    g.add_argument("--context-chars", type=int, default=GREP_CONTEXT,
                   help=f"characters shown around each match (default {GREP_CONTEXT})")
    g.set_defaults(func=cmd_grep)

    r = sub.add_parser("record", help="validate a verdict and store it in findings.db")
    r.add_argument("session", nargs="?", help="native id or numeric id")
    r.add_argument("--run-id", type=int)
    r.add_argument("--new-run", action="store_true", help="start a run; prints its id")
    r.add_argument("--model", help="the model answering the rubric")
    r.add_argument("--file", help="verdict JSON (default: stdin)")
    r.set_defaults(func=cmd_record)

    u = sub.add_parser("rollup", help="count recorded findings")
    u.add_argument("--since")
    u.add_argument("--harness", action="append", choices=["claude", "pi", "dsh"])
    u.add_argument("--by", choices=["category", "tool", "project", "week"], default="category")
    u.add_argument("--min", type=int, default=2)
    u.set_defaults(func=cmd_rollup)

    b = sub.add_parser("rubric", help="print the categories and the verdict shape")
    b.set_defaults(func=cmd_rubric)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
