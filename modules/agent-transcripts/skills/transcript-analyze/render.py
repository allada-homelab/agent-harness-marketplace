#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Re-create one session as a single text file a reviewer agent can read end to end.

`render.py <session>` writes the file and prints one summary line. `render.py expand <id>`
prints the full text behind one `#id` in that file: a message's text, or for a tool call
the call's arguments (a `StructuredOutput` final report lives there, not in message text).

What the file keeps, and why (each choice was tested against probe questions on real
sessions; see the transcript-analyze skill):

- Every human turn, in full up to 4,000 chars, with its timestamp. Harness boilerplate is
  stripped by structure (`<system-reminder>` blocks and the like), never by the index's
  `injected` flag, which also marks common short replies such as "yes" or "go".
- Assistant prose; a turn over 3,000 chars keeps its first and last 1,500, because decision
  menus sit at the end. The session's last assistant text is never cut.
- Every tool call as one line (arguments cut at 200 chars; an Agent brief at 1,500; a
  `StructuredOutput` or `SubagentHandback` final report never cut).
- Tool results hidden behind their size, except: errors (first 300 chars), a Bash result's
  last line (test counts live there), a Grep result's first line and line count, and a
  synchronous subagent's report.
- System rows by kind: a skill load is one line (skill reloads can be most of a session's
  characters), a compaction is a marked boundary with the summary's "current work", a
  background subagent's report is shown (its "launched" tool result is collapsed).
- A header with start and last activity, counts, the compaction index, the commit / push /
  PR timeline and any slash command repeated three or more times.

`--mode auto` (the default) renders in full when that fits `--budget` characters and as an
outline otherwise. The outline keeps every human turn and the agent's last message after
it, summarizes the work between as tool counts plus errors, and folds runs of scripted
turns (a slash command or a long template repeated three or more times, never a short
human reply) into one block that lists each distinct outcome once.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "transcript-query"))
from query import connect, resolve_dest  # noqa: E402

USER_CAP, ASST_CAP, ARGS_CAP, BRIEF_CAP = 4000, 3000, 200, 1500
ERR_CAP, HINT_CAP, REPORT_CAP, PEER_CAP, OTHER_SYS_CAP = 300, 160, 3000, 1000, 300
GIST_CAP, LINE_WRAP, DEFAULT_BUDGET, EXPAND_CHARS = 700, 1500, 350_000, 6000
DISPATCH = ("Agent", "Task")
FINAL_REPORT_TOOLS = ("StructuredOutput", "SubagentHandback")
LOOP_MIN = 3  # a scripted prompt seen this many times is a loop
SCRIPTED_MIN_CHARS = 200  # a non-command turn this long and repeated is a template

BOILERPLATE = re.compile(
    r"<(system-reminder|local-command-stdout|local-command-caveat)>.*?</\1>", re.S)
GIT_ACT = re.compile(
    r"(git (?:-C \S+ )?(?:commit|push)[^&;|\n]{0,90}|pr-flow (?:-C \S+ )?(?:open|watch --merge)"
    r"|gh pr (?:create|merge)[^&;|\n]{0,40})")
USER_PREFIX = re.compile(r"^\nUSER \[#\d+\] \([^)]*\): ")


def one(text: str | None) -> str:
    return " ".join((text or "").split())


def cap(text: str | None, n: int, mid: int | None = None) -> str:
    flat = one(text)
    if len(flat) <= n:
        return flat
    where = f"; expand #{mid}" if mid else ""
    return f"{flat[:n]} …[{len(flat):,} chars{where}]"


def clean_user(text: str) -> str:
    """Drop harness blocks by structure; show a slash command as `/name args`."""
    text = BOILERPLATE.sub("", text)
    cmd = re.search(r"<command-name>(.*?)</command-name>", text)
    if cmd:
        args = re.search(r"<command-args>(.*?)</command-args>", text, re.S)
        text = f"{cmd.group(1)} {(args.group(1) if args else '').strip()}"
    return re.sub(r"</?bash-input>", "", text).strip()


def system_kind(text: str) -> tuple[str, str]:
    if text.startswith("Base directory for this skill:"):
        m = re.search(r"skills/([^/\s]+)", text.split("\n", 1)[0])
        return "skill", m.group(1) if m else "?"
    if text.startswith("This session is being continued from a previous"):
        return "compaction", ""
    head = text[:600]
    if "[Subagent hand-back]" in head or text.startswith("<agent-message"):
        return "report", ""
    if text.startswith("Another Claude session sent a message"):
        return "peer", ""
    if text.startswith("<task-notification>"):
        return "notify", ""
    if text.startswith("switchboard:") or "SessionStart" in text[:200]:
        return "context", ""
    return "other", ""


def load(conn, session: str):
    row = conn.execute(
        "SELECT id, native_id, project_key, started_at FROM sessions WHERE native_id LIKE ?"
        " ORDER BY kind = 'main' DESC LIMIT 2", (session + "%",)).fetchall()
    if not row:
        raise SystemExit(f"no session matches {session!r}")
    if len(row) > 1 and len(session) < 36:
        raise SystemExit(f"{session!r} matches more than one session; give more of the id")
    return row[0]


def subagent_links(conn, native_id: str) -> dict[str, tuple[int, str]]:
    """A subagent's first user message is the brief its parent's Agent call sent."""
    links = {}
    for sid, nid, first in conn.execute(
            "SELECT s.id, s.native_id, (SELECT text FROM messages WHERE session_id = s.id"
            " AND role = 'user' ORDER BY ord LIMIT 1) FROM sessions s WHERE s.parent_native_id = ?",
            (native_id,)):
        if first:
            links[one(first)[:200]] = (sid, nid)
    return links


def subagent_digest(conn, sid: int, nid: str) -> str:
    rows = conn.execute(
        "SELECT t.name, t.is_error FROM tool_calls t JOIN messages m ON m.id = t.message_id"
        " WHERE m.session_id = ?", (sid,)).fetchall()
    by = collections.Counter(r[0] for r in rows)
    tools = ", ".join(f"{k} {v}" for k, v in by.most_common(4))
    return f"⤷ subagent {nid}: {len(rows)} calls ({tools}), {sum(r[1] or 0 for r in rows)} errors"


def result_line(name: str, mid: int, text: str, is_error: int) -> str:
    if is_error:
        return f"  ← ERROR {name} [#{mid}] {cap(text, ERR_CAP)}"
    if name in DISPATCH and text.startswith("Async agent launched"):
        return f"  ← {name} [#{mid}] (launched in background; its report arrives later as SUBAGENT REPORT)"
    if name in DISPATCH:
        return f"  ← {name} [#{mid}] {cap(text, REPORT_CAP, mid)}"
    if name == "Bash":
        tail = next((ln for ln in reversed(text.strip().splitlines()) if ln.strip()), "")
        return f"  ← Bash [#{mid}] ok, {len(text):,} chars; last line: {cap(tail, HINT_CAP)}"
    if name == "Grep":
        lines = text.splitlines()
        first = cap(lines[0] if lines else "", 100)
        return f"  ← Grep [#{mid}] ok, {len(lines)} lines; first: {first}"
    return f"  ← {name} [#{mid}] ok, {len(text):,} chars"


def system_line(mid: int, text: str, n_compaction: int) -> tuple[str, str]:
    kind, extra = system_kind(text)
    if kind == "skill":
        return "sys", f"[#{mid}] skill loaded: {extra} ({len(text):,} chars)"
    if kind == "compaction":
        work = re.search(r"Current Work:?(.*?)(?:\n\s*\d+\.\s+\w[^\n]*:|\Z)", text, re.S)
        gist = cap(work.group(1) if work else text[-GIST_CAP:], GIST_CAP)
        return "compaction", (
            f"\n════ CONTEXT COMPACTION {n_compaction} [#{mid}] ════ the agent's memory of "
            f"everything above was replaced by a {len(text):,}-char summary (expand #{mid}). "
            f"From here it only knows what that summary kept. Its 'current work': {gist}\n")
    if kind == "report":
        who = re.search(r'agent-message from="([^"]+)"', text)
        body = text.split("The report follows:", 1)[-1].split("</agent-message>", 1)[0]
        return "sys", (f"\nSUBAGENT REPORT from agent-{who.group(1) if who else '?'} [#{mid}]: "
                       f"{cap(body, REPORT_CAP, mid)}")
    if kind == "peer":
        return "sys", f"\nPEER SESSION MESSAGE [#{mid}]: {cap(text, PEER_CAP, mid)}"
    if kind == "notify":
        return "sys", f"[#{mid}] task notification: {cap(text, HINT_CAP)}"
    if kind == "context":
        return "sys", f"[#{mid}] harness context ({len(text):,} chars)"
    return "sys", f"[#{mid}] system: {cap(text, OTHER_SYS_CAP, mid)}"


def events(conn, sid: int, native_id: str):
    """One event per rendered line: (kind, text, tool, args-key, is_error)."""
    links = subagent_links(conn, native_id)
    calls: dict[int, list] = {}
    results: dict[int, tuple] = {}
    for mid, name, args, err, rid in conn.execute(
            "SELECT t.message_id, t.name, t.arguments, t.is_error, t.result_message_id"
            " FROM tool_calls t JOIN messages m ON m.id = t.message_id WHERE m.session_id = ?"
            " ORDER BY t.id", (sid,)):
        calls.setdefault(mid, []).append((name, args or "", err))
        if rid:
            results[rid] = (name, err)
    msgs = conn.execute(
        "SELECT id, role, text, ts FROM messages WHERE session_id = ? ORDER BY ord, id",
        (sid,)).fetchall()
    last_text = max((m[0] for m in msgs if m[1] == "assistant" and (m[2] or "").strip()),
                    default=None)
    ev, n_compaction = [], 0
    for mid, role, text, ts in msgs:
        text = text or ""
        if role == "user":
            clean = clean_user(text)
            if not clean:
                continue
            if len(clean) > USER_CAP:
                clean = clean[:USER_CAP] + f" …[{len(clean):,} chars; expand #{mid}]"
            when = (ts or "")[:16].replace("T", " ")
            ev.append(("user", f"\nUSER [#{mid}] ({when}): {clean}", None, None, False))
        elif role == "assistant":
            body = text.strip()
            if body:
                if mid != last_text and len(body) > ASST_CAP:
                    half = ASST_CAP // 2
                    body = (f"{body[:half]} …[{len(body) - ASST_CAP:,} chars omitted; "
                            f"expand #{mid}]… {body[-half:]}")
                ev.append(("asst", f"\nASSISTANT [#{mid}]: {body}", None, None, False))
            for name, args, err in calls.get(mid, []):
                if name in DISPATCH:
                    try:
                        brief = json.loads(args).get("prompt", args)
                    except (ValueError, AttributeError):
                        brief = args
                    line = f"  → {name} [#{mid}] {cap(brief, BRIEF_CAP)}"
                    link = links.get(one(brief)[:200])
                    if link:
                        line += "\n    " + subagent_digest(conn, *link)
                elif name in FINAL_REPORT_TOOLS:
                    line = f"  → {name} [#{mid}] {one(args)}"
                else:
                    line = f"  → {name} [#{mid}] {cap(args, ARGS_CAP)}"
                ev.append(("call", line, name, one(args)[:ARGS_CAP], bool(err)))
        elif role == "tool_result":
            name, err = results.get(mid, ("?", 0))
            ev.append(("err" if err else "result", result_line(name, mid, text, err),
                       name, None, bool(err)))
        else:
            kind, line = system_line(mid, text, n_compaction + 1)
            n_compaction += kind == "compaction"
            ev.append((kind, line, None, None, False))
    return ev, calls, msgs


def collapse_repeats(ev) -> list[str]:
    """Consecutive identical calls (tool, argument head, error state) become one line ×N."""
    out, i = [], 0
    while i < len(ev):
        e = ev[i]
        if e[0] == "call":
            j, n = i + 1, 1
            while (j + 1 < len(ev) and ev[j][0] in ("result", "err") and ev[j + 1][0] == "call"
                   and ev[j + 1][2:5] == e[2:5]):
                n, j = n + 1, j + 2
            if n > 1:
                out.append(f"{e[1]}   ×{n} identical calls in a row")
                if j < len(ev) and ev[j][0] in ("result", "err"):
                    out.append(ev[j][1])
                i = j + 1
                continue
        out.append(e[1])
        i += 1
    return out


def user_body(line: str) -> str:
    return USER_PREFIX.sub("", line)


def is_scripted(line: str) -> bool:
    body = user_body(line)
    return body.startswith("/") or len(body) >= SCRIPTED_MIN_CHARS


def outline(ev) -> list[str]:
    key = lambda line: one(user_body(line))[:300]  # noqa: E731
    counts = collections.Counter(key(e[1]) for e in ev if e[0] == "user" and is_scripted(e[1]))
    groups, cur, seg = [], None, []
    for e in ev:
        if e[0] == "user":
            groups.append((cur, seg))
            cur, seg = e, []
        else:
            seg.append(e)
    groups.append((cur, seg))

    def last_text(seg):
        texts = [e[1] for e in seg if e[0] == "asst"]
        return re.sub(r"^\nASSISTANT \[#\d+\]: ", "", texts[-1]) if texts else "(no text)"

    def is_loop(g):
        return g[0] is not None and is_scripted(g[0][1]) and counts[key(g[0][1])] >= LOOP_MIN

    body, i, done = [], 0, 0
    while i < len(groups):
        user, seg = groups[i]
        if is_loop(groups[i]):
            j, n_calls, n_errs = i, 0, 0
            prompts, outcomes = collections.Counter(), {}
            while j < len(groups) and is_loop(groups[j]):
                g_seg = groups[j][1]
                n_calls += sum(1 for e in g_seg if e[0] == "call")
                n_errs += sum(1 for e in g_seg if e[0] == "err")
                prompts[cap(user_body(groups[j][0][1]), 60)] += 1
                last = last_text(g_seg)
                sig = re.sub(r"\d+", "#", one(last)[:120])
                m = re.search(r"\[#(\d+)\]", groups[j][0][1])
                first_id = m.group(1) if m else "?"
                outcomes.setdefault(sig, (first_id, last))
                j += 1
            n = j - i
            done += n
            kinds = ", ".join(f"{p} ×{k}" for p, k in prompts.most_common())
            body.append(f"\n↻ LOOP iterations {done - n + 1}–{done} ({n} scripted turns: {kinds}): "
                        f"{n_calls} calls, {n_errs} errors. Distinct outcomes:")
            for first_id, last in list(outcomes.values())[:10]:
                body.append(f"   • (first at #{first_id}) {cap(last, 300)}")
            if len(outcomes) > 10:
                body.append(f"   • … {len(outcomes) - 10} more distinct outcomes")
            body += ["  " + e[1].strip()[:200] for k in range(i, j) for e in groups[k][1]
                     if e[0] == "err"]
            i = j
            continue
        if user is not None:
            body.append(user[1])
        if seg:
            by_tool = collections.Counter(e[2] for e in seg if e[0] == "call")
            ids = [int(x) for e in seg for x in re.findall(r"\[#(\d+)\]", e[1])]
            if by_tool:
                span = f"#{min(ids)}–#{max(ids)}" if ids else ""
                tools = ", ".join(f"{k} {v}" for k, v in by_tool.most_common(6))
                body.append(f"  [agent work {span}: {sum(by_tool.values())} calls — {tools}]")
            errs = [e[1].strip() for e in seg if e[0] == "err"]
            body += ["  " + e[:260] for e in errs[:5]]
            if len(errs) > 5:
                body.append(f"  … {len(errs) - 5} more errors")
            for e in seg:
                if e[0] == "compaction" or (e[0] == "sys" and "SUBAGENT REPORT" in e[1]):
                    body.append(e[1][:1200])
                elif e[0] == "call" and e[2] in FINAL_REPORT_TOOLS:
                    body.append(e[1])
                elif e[0] == "call" and e[2] in DISPATCH:
                    body.append(e[1][:900])
            texts = [e[1] for e in seg if e[0] == "asst"]
            if len(texts) > 1:
                body.append(f"  [{len(texts) - 1} earlier assistant messages omitted; "
                            f"first: {cap(texts[0], 300)}]")
            if texts:
                body.append(texts[-1])
        i += 1
    return body


def render_session(conn, session: str, mode: str = "auto",
                   budget: int = DEFAULT_BUDGET) -> tuple[str, str, str]:
    """(native_id, mode actually used, rendered text)."""
    sid, native_id, project, started = load(conn, session)
    ev, calls, msgs = events(conn, sid, native_id)
    full = collapse_repeats(ev)
    if mode == "auto":
        mode = "full" if len("\n".join(full)) <= budget else "outline"
    body = full if mode == "full" else outline(ev)

    last = max((m[3] for m in msgs if m[3]), default="")
    git = [f"#{mid}: " + " + ".join(dict.fromkeys(a.strip() for a in GIT_ACT.findall(
               json.loads(args).get("command", "") if args.startswith("{") else args)))
           for mid, cl in sorted(calls.items()) for name, args, _ in cl
           if name == "Bash" and GIT_ACT.search(args)]
    compactions = re.findall(r"CONTEXT COMPACTION \d+ \[#(\d+)\]", "\n".join(
        e[1] for e in ev if e[0] == "compaction"))
    commands = collections.Counter(
        user_body(e[1])[:60] for e in ev if e[0] == "user" and user_body(e[1]).startswith("/"))
    repeated = sorted(((k, v) for k, v in commands.items() if v >= LOOP_MIN), key=lambda kv: -kv[1])
    n = collections.Counter(e[0] for e in ev)
    header = [
        f"# SESSION {native_id}  project={project}  started={started}  last activity={last}",
        f"# render mode: {mode}",
        f"# {n['user']} user turns · {n['call']} tool calls · {n['err']} errors · "
        f"{n['compaction']} compactions · {len(subagent_links(conn, native_id))} subagents",
    ]
    if repeated:
        header.append("# repeated slash-command turns: "
                      + "; ".join(f"{k} ×{v}" for k, v in repeated))
    header += [
        "# compactions at: " + (", ".join(f"#{x}" for x in compactions) or "none"),
        "# commits / pushes / PR actions: " + ("; ".join(git[:25])
                                               + (f"; … {len(git) - 25} more" if len(git) > 25 else "")
                                               if git else "none"),
        "# → tool call (args cut at 200) · ← result (hidden or hinted) · ← ERROR first 300 chars"
        " · `render.py expand <id>` shows the full text behind any #id",
        "",
    ]
    wrapped = []
    for line in "\n".join(header + body).split("\n"):
        while len(line) > LINE_WRAP:  # long lines can be cut by file readers; wrapping loses nothing
            wrapped.append(line[:LINE_WRAP])
            line = "    ↪ " + line[LINE_WRAP:]
        wrapped.append(line)
    return native_id, mode, "\n".join(wrapped) + "\n"


def expand(conn, message_id: int, offset: int = 0, size: int = EXPAND_CHARS) -> str:
    """Full text behind one #id: the message text, then the arguments of any call it made."""
    row = conn.execute("SELECT role, text FROM messages WHERE id = ?", (message_id,)).fetchone()
    if row is None:
        raise SystemExit(f"no message #{message_id}")
    parts = [f"[{row[0]}] {row[1] or ''}".rstrip()]
    for name, args in conn.execute(
            "SELECT name, arguments FROM tool_calls WHERE message_id = ? ORDER BY id", (message_id,)):
        parts.append(f"[call {name}] {args or ''}")
    full = "\n".join(parts)
    chunk = full[offset:offset + size]
    more = len(full) - offset - len(chunk)
    return chunk + (f"\n…[{more:,} more chars; --offset {offset + size}]" if more > 0 else "")


def inside_git_worktree(path: Path) -> bool:
    anchor = path
    while not anchor.exists() and anchor != anchor.parent:
        anchor = anchor.parent
    proc = subprocess.run(["git", "-C", str(anchor), "rev-parse", "--is-inside-work-tree"],
                          capture_output=True, text=True)
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def write_private(path: Path, text: str) -> None:
    """Rendered sessions quote private transcripts: never inside a git checkout."""
    if inside_git_worktree(path.parent):
        raise SystemExit(f"refusing to write {path}: it is inside a git worktree")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["expand"]:
        ap = argparse.ArgumentParser(prog="render.py expand")
        ap.add_argument("message_id", type=int)
        ap.add_argument("--offset", type=int, default=0)
        ap.add_argument("--dest")
        args = ap.parse_args(argv[1:])
        print(expand(connect(resolve_dest(args.dest)), args.message_id, args.offset))
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", help="native session id, or a unique prefix of it")
    ap.add_argument("--mode", choices=("auto", "full", "outline"), default="auto")
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET,
                    help="auto mode renders in full up to this many chars (default 350000)")
    ap.add_argument("--out", help="output file (default <cache>/work/render/<session>.txt)")
    ap.add_argument("--dest")
    args = ap.parse_args(argv)
    dest = resolve_dest(args.dest)
    native_id, mode, text = render_session(connect(dest), args.session, args.mode, args.budget)
    out = Path(args.out).expanduser() if args.out else dest / "work" / "render" / f"{native_id}.txt"
    write_private(out, text)
    print(f"render: {native_id} mode={mode} chars={len(text):,} lines={text.count(chr(10)):,} out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
