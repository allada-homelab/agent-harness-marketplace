#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Size a set of sessions and plan a fan-out read of them.

`corpus.py sizes` prints how many characters the sessions hold, split into the parts that
matter for reading them: human turns, assistant prose, system rows, and tool traffic (call
arguments plus results). Percentiles first, so you can size a reading budget before
reading anything.

`corpus.py anchors` lists the moments a deep read should start from, across sessions: each
human correction and interrupt, each claim that tests pass or a fix works, and each push or
merge paired with the last thing the human said before it. `review.py read <session>
--around <ord>` opens one.

`corpus.py thread <term>` follows one PR, ticket or branch across sessions: every main
session that mentions it, oldest first, with its opening request and its commit and push count.

`corpus.py plan --run <name>` picks sessions to read, renders each with `review.py read --all --mode auto` into
`<cache>/work/<run>/sessions/`, and packs them into batches of at most `--budget`
characters, one batch per reader. It writes `<cache>/work/<run>/manifest.json`.

Selection, and why:
- **Scripted sessions are found by their opening, not by the `injected` flag.** A session
  whose first human message is a long template shared with at least two other sessions (a
  headless review round, a scheduled job) is scripted. Such a template counts as "user
  text", so it would otherwise top any ranking by how much the user typed. Scripted
  sessions sharing a project and an arc are one run; a run is never split across batches,
  so one reader sees all its rounds. `--scripted` counts runs, not sessions.
- **A session's arc is the PR or ticket its human turns name most.** Interactive sessions
  on the same arc are not independent samples, so only the one with the most typing is
  picked.
- **The running session is never picked** (on Claude Code, from `CLAUDE_CODE_SESSION_ID`):
  it is half written, and the reader would study the study.
- **Interactive sessions are ranked by what the human typed**, boilerplate stripped by
  structure. The top of that ranking is where corrections live. A seeded random sample of
  the rest is the control, because issue yield is far higher in heavy-typing sessions.
- A session whose render does not fit one batch, even as an outline, is split into parts at
  human-turn boundaries; each part carries the session header and a `PART k/n` line, and
  readers judge only their part. A single message too large for any part is listed as
  oversize, never dropped silently.
"""

from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "transcript-review"))
from review import (  # noqa: E402  review.py also puts transcript-ingest on sys.path
    GIT_ACTION, arg_field, capped, connect, git_actions, normalize, paginate, read_units,
    render_table, resolve_dest, resolve_session, whole_text)
from signals import SIGNAL_TEXT_MAX, correction_text, human_text  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "transcript-query"))
from search import quote_term, require_fresh_fts  # noqa: E402
from transcripts import assert_outside_worktree  # noqa: E402


def write_private(path: Path, text: str) -> None:
    """Derived transcript data stays on device: never inside a git worktree."""
    assert_outside_worktree(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


BARE_COMMAND = re.compile(r"/\S+$")  # /clear, /model
TEMPLATE_MIN_CHARS = 500  # a first message this long, shared by 3+ sessions, is a template
TEMPLATE_MIN_SESSIONS = 3
ARC_REF = re.compile(r"github\.com/[\w.-]+/[\w.-]+/pull/\d+|\b[A-Z][A-Z0-9]{1,9}-\d{2,}\b")

SIZE_SQL = """
SELECT s.id, s.native_id, s.kind, s.project_key, s.started_at,
  coalesce(sum(CASE WHEN m.role = 'user' THEN length(m.text) END), 0),
  coalesce(sum(CASE WHEN m.role = 'assistant' THEN length(m.text) END), 0),
  coalesce(sum(CASE WHEN m.role = 'system' THEN length(m.text) END), 0),
  coalesce(sum(CASE WHEN m.role = 'tool_result' THEN length(m.text) END), 0),
  (SELECT coalesce(sum(length(t.arguments)), 0) FROM tool_calls t
     JOIN messages m2 ON m2.id = t.message_id WHERE m2.session_id = s.id), s.harness
FROM sessions s LEFT JOIN messages m ON m.session_id = s.id
WHERE (:since IS NULL OR s.started_at >= :since) AND (:until IS NULL OR s.started_at < :until)
  AND (:kind IS NULL OR s.kind = :kind) AND (:harness IS NULL OR s.harness = :harness)
GROUP BY s.id
"""
COLUMNS = ("session_id", "kind", "project", "started_at", "user_chars", "assistant_chars",
           "system_chars", "tool_result_chars", "tool_arg_chars", "harness")


def sized(conn, since, until, kind, harness) -> list[dict]:
    params = {"since": since, "until": until, "kind": kind, "harness": harness}
    rows = conn.execute(SIZE_SQL, params).fetchall()
    return [dict(zip(("db_id",) + COLUMNS, r)) for r in rows]


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(p * len(values)))] if values else 0


def cmd_sizes(conn, args) -> int:
    rows = sized(conn, args.since, args.until, None, args.harness)
    measures = {
        "chat (user + assistant)": lambda r: r["user_chars"] + r["assistant_chars"],
        "  user": lambda r: r["user_chars"],
        "  assistant": lambda r: r["assistant_chars"],
        "system rows": lambda r: r["system_chars"],
        "tool traffic (args + results)": lambda r: r["tool_result_chars"] + r["tool_arg_chars"],
    }
    for kind in sorted({r["kind"] for r in rows}):
        group = [r for r in rows if r["kind"] == kind]
        print(f"--- {kind}: {len(group)} sessions")
        print(f"{'':32}{'total':>14}{'p50':>10}{'p90':>11}{'p99':>11}{'max':>12}")
        for label, f in measures.items():
            vals = [f(r) for r in group]
            print(f"{label:32}{sum(vals):>14,}{pct(vals, .5):>10,}{pct(vals, .9):>11,}"
                  f"{pct(vals, .99):>11,}{max(vals, default=0):>12,}")
    if args.csv:
        out, buf = Path(args.csv).expanduser(), io.StringIO()
        csv.writer(buf).writerows([COLUMNS] + [[r[c] for c in COLUMNS] for r in rows])
        write_private(out, buf.getvalue())
        print(f"csv: {out}")
    return 0


def human_texts(conn, db_id, harness) -> list[str]:
    texts = [human_text(t or "", harness) for (t,) in conn.execute(
        "SELECT text FROM messages WHERE session_id = ? AND role = 'user' ORDER BY ord", (db_id,))]
    return [t for t in texts if t]


def first_and_typed(texts: list[str]) -> tuple[str, int]:
    """(opening request, chars the human typed). A bare `/clear` is not what a session was for."""
    first = next((t for t in texts if not BARE_COMMAND.match(t)), "")
    return first, sum(len(t) for t in texts)


def arc(texts: list[str]) -> str | None:
    """The PR URL or ticket id the human named most; the first named wins a tie."""
    refs = collections.Counter(ref for t in texts for ref in ARC_REF.findall(t))
    return refs.most_common(1)[0][0] if refs else None


def opening(first: str) -> str | None:
    """The template key of a first message, or None if it cannot be a template."""
    if len(first) < TEMPLATE_MIN_CHARS or first.startswith("/"):
        return None  # a human typing a slash command is not a script
    return re.sub(r"\d+", "#", normalize(first))[:120]


def classify(conn, rows):
    for r in rows:
        texts = human_texts(conn, r["db_id"], r["harness"])
        first, r["typed"] = first_and_typed(texts)
        r["opening"], r["arc"] = opening(first), arc(texts)
    shared = collections.Counter(r["opening"] for r in rows if r["opening"])
    for r in rows:
        r["scripted"] = bool(r["opening"]) and shared[r["opening"]] >= TEMPLATE_MIN_SESSIONS
        run = f"run:{r['project']}" + (f":{r['arc']}" if r["arc"] else "")
        r["group"] = run if r["scripted"] else r["session_id"]
    return rows


def pick(rows, top, n_random, n_scripted, min_chars, seed):
    rng = random.Random(seed)
    live = [r for r in rows if r["user_chars"] + r["assistant_chars"] >= min_chars]
    by_arc = {}  # most typing first, so an arc keeps its heaviest session
    for r in sorted((r for r in live if not r["scripted"]), key=lambda r: -r["typed"]):
        by_arc.setdefault(r["arc"] or r["session_id"], r)
    inter = list(by_arc.values())
    chosen = [dict(r, stratum="top_typing") for r in inter[:top]]
    rest = inter[top:]
    chosen += [dict(r, stratum="random") for r in rng.sample(rest, min(n_random, len(rest)))]
    runs = collections.defaultdict(list)
    for r in live:
        if r["scripted"]:
            runs[r["group"]].append(r)
    names = sorted(runs)
    rng.shuffle(names)
    for name in names[:n_scripted]:
        chosen += [dict(r, stratum="scripted") for r in runs[name]]
    return chosen


def pack(units, budget):
    """First-fit decreasing; a unit (one session, or one whole scripted run) is never split."""
    bins: list[tuple[list, list[int]]] = []  # (sessions, [running size])
    for size, unit in sorted(((sum(s["chars"] for s in u), u) for u in units), key=lambda x: -x[0]):
        for sessions, total in bins:
            if total[0] + size <= budget:
                sessions.extend(unit)
                total[0] += size
                break
        else:
            bins.append((list(unit), [size]))
    return [sessions for sessions, _ in bins]


HEADER_ROOM = 10_000  # a part's header and line wrapping, so the part file stays under budget


def render_parts(conn, native_id: str, budget: int) -> tuple[str, list[str]]:
    """(mode, texts): the whole session, or numbered parts of it when it will not fit one
    reader even as an outline. Each part carries the session header."""
    session = resolve_session(conn, native_id)
    mode, shown, units = read_units(conn, session, mode="auto", budget=budget)
    parts = paginate(shown, budget - HEADER_ROOM) or [shown]
    if len(parts) == 1:
        return mode, [whole_text(conn, session, mode, shown, units)]
    texts = []
    for k, part in enumerate(parts, 1):
        banner = (f"PART {k}/{len(parts)} of session {native_id}, ords {part[0].ord}–"
                  f"{part[-1].ord}. Other readers have the other parts: judge only this one.\n")
        texts.append(banner + whole_text(conn, session, mode, part, units))
    return mode, texts


def cmd_plan(conn, args) -> int:
    dest = resolve_dest(args.dest)
    work = dest / "work" / args.run
    if work.exists():  # another run's manifest and findings live there; never mix two runs
        raise SystemExit(f"{work} already exists; pick a new --run")
    rows = classify(conn, sized(conn, args.since, args.until, "main", args.harness))
    running = os.environ.get("CLAUDE_CODE_SESSION_ID")
    exclude = args.exclude + ([running] if running else [])
    rows = [r for r in rows if not any(r["session_id"].startswith(x) for x in exclude)]
    n_scripted_all = sum(r["scripted"] for r in rows)
    chosen = pick(rows, args.top, args.random, args.scripted, args.min_chars, args.seed)

    units = collections.defaultdict(list)
    oversize = []
    for r in chosen:
        native_id = r["session_id"]
        mode, texts = render_parts(conn, native_id, args.budget)
        multi = len(texts) > 1
        for k, text in enumerate(texts, 1):
            name = f"{native_id}.part{k}" if multi else native_id
            path = work / "sessions" / f"{name}.txt"
            write_private(path, text)
            entry = {"session_id": native_id, "path": str(path), "chars": len(text), "mode": mode,
                     "stratum": r["stratum"], "group": r["group"], "typed_chars": r["typed"]}
            if multi:
                entry["part"] = f"{k}/{len(texts)}"
            if len(text) > args.budget:  # one message larger than a reader
                oversize.append(entry)
            else:  # a part goes to a reader of its own; a scripted run stays together
                units[name if multi else r["group"]].append(entry)
    batches = pack(list(units.values()), args.budget)
    manifest = {"run": args.run, "since": args.since, "until": args.until, "budget": args.budget, "seed": args.seed,
                "strata": dict(collections.Counter(r["stratum"] for r in chosen)),
                "batches": batches, "oversize": oversize}
    write_private(work / "manifest.json", json.dumps(manifest, indent=1))

    print(f"plan: {len(rows)} main sessions since {args.since or 'the start'}, "
          f"{n_scripted_all} scripted; picked {len(chosen)} {manifest['strata']}")
    for i, b in enumerate(batches):
        print(f"  batch {i}: {len(b)} files, {sum(s['chars'] for s in b):,} chars")
    for o in oversize:
        print(f"  oversize (read alone): {o['session_id']} {o['chars']:,} chars")
    print(f"manifest: {work / 'manifest.json'}")
    return 0


INTERRUPT = "[Request interrupted by user"
CLAIM = re.compile(r"\b(?:(?:all )?(?:\d+ )?tests? (?:all )?pass(?:ed|es)?|verified|works now|is fixed"
                   r"|(?:CI|checks?) (?:is |are )?green)\b", re.I)
ANCHOR_WIDTH = 120
PUSH = re.compile(r"git (?:-C \S+ )?push\b")  # a verb, not a word inside a commit message
ANCHOR_SQL = """
SELECT s.native_id, s.harness, m.ord, m.role,
  CASE WHEN m.role = 'assistant' THEN substr(m.text, -2000)
       WHEN length(m.text) <= :max THEN m.text END,
  CASE WHEN lower(t.name) = 'bash' THEN t.arguments END
FROM sessions s JOIN messages m ON m.session_id = s.id
LEFT JOIN tool_calls t ON t.message_id = m.id
WHERE s.kind = 'main' AND m.role IN ('user', 'assistant')
  AND (:since IS NULL OR s.started_at >= :since) AND (:until IS NULL OR s.started_at < :until)
ORDER BY s.started_at, s.id, m.ord, m.id
"""


def find_anchors(conn, since, until) -> list[tuple[str, int, str, str]]:
    """(session, ord, kind, what) for every correction, interrupt, claim and push or merge."""
    out, last_human, prev = [], {}, None
    for native_id, harness, ord_, role, text, bash in conn.execute(
            ANCHOR_SQL, {"max": SIGNAL_TEXT_MAX, "since": since, "until": until}):
        if role == "user" and text:
            if text.startswith(INTERRUPT):
                out.append((native_id, ord_, "interrupt", ""))
                continue
            said = human_text(text, harness)
            if correction_text(text, harness):
                out.append((native_id, ord_, "correction", said))
            if said:
                last_human[native_id] = (ord_, said)
        elif role == "assistant":
            claim = CLAIM.search(text or "") if (native_id, ord_) != prev else None
            prev = (native_id, ord_)  # one row per tool call: claim once per message
            if claim:
                out.append((native_id, ord_, "claim", text[max(0, claim.start() - 80):claim.end() + 40]))
            actions = GIT_ACTION.findall(arg_field(bash, "command")) if bash else []
            kinds = {"push" if PUSH.match(a) else "merge" for a in actions
                     if PUSH.match(a) or a.endswith("merge") or a.startswith("gh pr merge")}
            kind = "merge" if "merge" in kinds else "push" if kinds else None
            if kind:  # a commit or a PR opened is not the moment that needs an approval
                before = last_human.get(native_id)
                said = f"after [{before[0]}] {before[1]}" if before else "no human turn before it"
                out.append((native_id, ord_, kind, said))
    return out


def cmd_anchors(conn, args) -> int:
    found = [a for a in find_anchors(conn, args.since, args.until)
             if not args.kind or a[2] in args.kind]
    print(", ".join(f"{k} {n}" for k, n in collections.Counter(
        a[2] for a in found).most_common()) or "no anchors")
    rows = [[sid, ord_, kind, capped(what, ANCHOR_WIDTH)] for sid, ord_, kind, what in found[:args.limit]]
    if rows:
        print(render_table(["session", "ord", "kind", "what"], rows))
        print(f"\n{len(found)} anchors; `review.py read <session> --around <ord>` shows one in context")
    return 0


def cmd_thread(conn, args) -> int:
    require_fresh_fts(conn)
    hits = conn.execute(
        "SELECT s.id, s.native_id, s.harness, s.started_at, count(*), min(m.ord)"
        " FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid"
        " JOIN sessions s ON s.id = m.session_id"
        " WHERE messages_fts MATCH ? AND s.kind = 'main'"
        " GROUP BY s.id ORDER BY s.started_at, s.id LIMIT ?",
        (quote_term(args.term), args.limit)).fetchall()
    rows = []
    for db_id, native_id, harness, started_at, n, first in hits:
        shipped = sum(len(found) for _, found in git_actions(conn, db_id))
        rows.append([(started_at or "")[:16], native_id, n, first, shipped,
                     capped(first_and_typed(human_texts(conn, db_id, harness))[0], 100)])
    if not rows:
        print(f"no session mentions {args.term!r}")
        return 0
    print(render_table(["started", "session", "hits", "first", "git", "request"], rows))
    print("\n`review.py read <session> --around <first>` opens the first mention")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sizes", help="character counts per session, by part")
    s.add_argument("--since", help="ISO date or timestamp; sessions started at or after it")
    s.add_argument("--until", help="sessions started before it")
    s.add_argument("--harness")
    s.add_argument("--csv", help="also write one row per session to this file (not in a repo)")
    p = sub.add_parser("plan", help="pick, render and batch sessions for a fan-out read")
    p.add_argument("--run", required=True, help="work dir name under <cache>/work/")
    p.add_argument("--since")
    p.add_argument("--until", help="sessions started before it (for a before/after cohort)")
    p.add_argument("--harness")
    p.add_argument("--top", type=int, default=16, help="interactive sessions with the most typing")
    p.add_argument("--random", type=int, default=12, help="random interactive control sessions")
    p.add_argument("--scripted", type=int, default=6, help="scripted runs, each read whole")
    p.add_argument("--min-chars", type=int, default=3000, help="skip sessions with less chat")
    p.add_argument("--budget", type=int, default=350_000, help="max chars per batch (one reader)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--exclude", action="append", default=[], help="session id prefix to skip")
    a = sub.add_parser("anchors", help="corrections, interrupts, claims, pushes and merges")
    a.add_argument("--since")
    a.add_argument("--until")
    a.add_argument("--kind", action="append",
                   choices=("correction", "interrupt", "claim", "push", "merge"),
                   help="only these kinds (repeatable)")
    a.add_argument("--limit", type=int, default=200)
    t = sub.add_parser("thread", help="every session that mentions a PR, ticket or branch")
    t.add_argument("term", help="a PR number, ticket id, branch name or other phrase")
    t.add_argument("--limit", type=int, default=60)
    args = ap.parse_args(argv)
    conn = connect(resolve_dest(args.dest))
    return {"sizes": cmd_sizes, "plan": cmd_plan, "anchors": cmd_anchors,
            "thread": cmd_thread}[args.cmd](conn, args)


if __name__ == "__main__":
    raise SystemExit(main())
