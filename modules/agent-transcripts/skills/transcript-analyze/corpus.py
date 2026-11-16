#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Size a set of sessions and plan a fan-out read of them.

`corpus.py sizes` prints how many characters the sessions hold, split into the parts that
matter for reading them: human turns, assistant prose, system rows, and tool traffic (call
arguments plus results). Percentiles first, so you can size a reading budget before
reading anything.

`corpus.py plan --run <name>` picks sessions to read, renders each with render.py into
`<cache>/work/<run>/sessions/`, and packs them into batches of at most `--budget`
characters, one batch per reader. It writes `<cache>/work/<run>/manifest.json`.

Selection, and why:
- **Scripted sessions are found by their opening, not by the `injected` flag.** A session
  whose first human message is a long template shared with at least two other sessions (a
  headless review round, a scheduled job) is scripted. Such a template counts as "user
  text", so it would otherwise top any ranking by how much the user typed. Scripted
  sessions sharing a project are one run; a run is never split across batches, so one
  reader sees the whole arc.
- **Interactive sessions are ranked by what the human typed**, boilerplate stripped by
  structure. The top of that ranking is where corrections live. A seeded random sample of
  the rest is the control, because issue yield is far higher in heavy-typing sessions.
- A session whose render does not fit one batch is listed as oversize, not dropped
  silently. Read it alone (see transcript-analyze, "A session longer than four pages").
"""

from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "transcript-query"))
from query import connect, resolve_dest  # noqa: E402
from render import clean_user, one, render_session, write_private  # noqa: E402

TEMPLATE_MIN_CHARS = 500  # a first message this long, shared by 3+ sessions, is a template
TEMPLATE_MIN_SESSIONS = 3

SIZE_SQL = """
SELECT s.id, s.native_id, s.kind, s.project_key, s.started_at,
  coalesce(sum(CASE WHEN m.role = 'user' THEN length(m.text) END), 0),
  coalesce(sum(CASE WHEN m.role = 'assistant' THEN length(m.text) END), 0),
  coalesce(sum(CASE WHEN m.role = 'system' THEN length(m.text) END), 0),
  coalesce(sum(CASE WHEN m.role = 'tool_result' THEN length(m.text) END), 0),
  (SELECT coalesce(sum(length(t.arguments)), 0) FROM tool_calls t
     JOIN messages m2 ON m2.id = t.message_id WHERE m2.session_id = s.id)
FROM sessions s LEFT JOIN messages m ON m.session_id = s.id
WHERE (:since IS NULL OR s.started_at >= :since) AND (:until IS NULL OR s.started_at < :until)
  AND (:kind IS NULL OR s.kind = :kind) AND (:harness IS NULL OR s.harness = :harness)
GROUP BY s.id
"""
COLUMNS = ("session_id", "kind", "project", "started_at", "user_chars", "assistant_chars",
           "system_chars", "tool_result_chars", "tool_arg_chars")


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


def first_and_typed(conn, db_id) -> tuple[str, int]:
    texts = [clean_user(t or "") for (t,) in conn.execute(
        "SELECT text FROM messages WHERE session_id = ? AND role = 'user' ORDER BY ord", (db_id,))]
    texts = [t for t in texts if t]
    return (texts[0] if texts else ""), sum(len(t) for t in texts)


def opening(first: str) -> str | None:
    """The template key of a first message, or None if it cannot be a template."""
    if len(first) < TEMPLATE_MIN_CHARS or first.startswith("/"):
        return None  # a human typing a slash command is not a script
    return re.sub(r"\d+", "#", one(first))[:120]


def classify(conn, rows):
    for r in rows:
        first, r["typed"] = first_and_typed(conn, r["db_id"])
        r["opening"] = opening(first)
    shared = collections.Counter(r["opening"] for r in rows if r["opening"])
    for r in rows:
        r["scripted"] = bool(r["opening"]) and shared[r["opening"]] >= TEMPLATE_MIN_SESSIONS
        r["group"] = f"run:{r['project']}" if r["scripted"] else r["session_id"]
    return rows


def pick(rows, top, n_random, n_scripted, min_chars, seed):
    rng = random.Random(seed)
    live = [r for r in rows if r["user_chars"] + r["assistant_chars"] >= min_chars]
    inter = sorted((r for r in live if not r["scripted"]), key=lambda r: -r["typed"])
    chosen = [dict(r, stratum="top_typing") for r in inter[:top]]
    rest = inter[top:]
    chosen += [dict(r, stratum="random") for r in rng.sample(rest, min(n_random, len(rest)))]
    runs = collections.defaultdict(list)
    for r in live:
        if r["scripted"]:
            runs[r["group"]].append(r)
    names = sorted(runs)
    rng.shuffle(names)
    taken = 0
    for name in names:
        if taken >= n_scripted:
            break
        chosen += [dict(r, stratum="scripted") for r in runs[name]]
        taken += len(runs[name])
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


def cmd_plan(conn, args) -> int:
    dest = resolve_dest(args.dest)
    work = dest / "work" / args.run
    rows = classify(conn, sized(conn, args.since, args.until, "main", args.harness))
    rows = [r for r in rows if not any(r["session_id"].startswith(x) for x in args.exclude)]
    n_scripted_all = sum(r["scripted"] for r in rows)
    chosen = pick(rows, args.top, args.random, args.scripted, args.min_chars, args.seed)

    units = collections.defaultdict(list)
    oversize = []
    for r in chosen:
        native_id, mode, text = render_session(conn, r["session_id"], "auto", args.budget)
        path = work / "sessions" / f"{native_id}.txt"
        write_private(path, text)
        entry = {"session_id": native_id, "path": str(path), "chars": len(text), "mode": mode,
                 "stratum": r["stratum"], "group": r["group"], "typed_chars": r["typed"]}
        if len(text) > args.budget:
            oversize.append(entry)
        else:
            units[r["group"]].append(entry)
    batches = pack(list(units.values()), args.budget)
    manifest = {"run": args.run, "since": args.since, "until": args.until, "budget": args.budget, "seed": args.seed,
                "strata": dict(collections.Counter(r["stratum"] for r in chosen)),
                "batches": batches, "oversize": oversize}
    write_private(work / "manifest.json", json.dumps(manifest, indent=1))

    print(f"plan: {len(rows)} main sessions since {args.since or 'the start'}, "
          f"{n_scripted_all} scripted; picked {len(chosen)} {manifest['strata']}")
    for i, b in enumerate(batches):
        print(f"  batch {i}: {len(b)} sessions, {sum(s['chars'] for s in b):,} chars")
    for o in oversize:
        print(f"  oversize (read alone): {o['session_id']} {o['chars']:,} chars")
    print(f"manifest: {work / 'manifest.json'}")
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
    p.add_argument("--scripted", type=int, default=12, help="scripted sessions, in whole runs")
    p.add_argument("--min-chars", type=int, default=3000, help="skip sessions with less chat")
    p.add_argument("--budget", type=int, default=350_000, help="max chars per batch (one reader)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--exclude", action="append", default=[], help="session id prefix to skip")
    args = ap.parse_args(argv)
    conn = connect(resolve_dest(args.dest))
    return cmd_sizes(conn, args) if args.cmd == "sizes" else cmd_plan(conn, args)


if __name__ == "__main__":
    raise SystemExit(main())
