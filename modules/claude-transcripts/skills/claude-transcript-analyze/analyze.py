#!/usr/bin/env python3
"""claude-transcript-analyze core: parse an export root into a metadata index,
per-turn flags, and an aggregate report — with zero prose ever entering context.

Input layout (produced by the claude-transcript-export skill):
    <root>/<source>/projects/<slug>/*.jsonl
where <source> is "host" or a docker volume name.

Two-layer design (see the design spec): this file is Layer 1 — deterministic
metadata only (the LENSES flag turns; the report aggregates counts/rates). Layer 2
(bounded excerpts + subagent labeling for TP/FP judgment) is driven by the
`excerpt` subcommand plus the orchestrating session (see SKILL.md).

Privacy: transcript-derived output never enters a git repo. `run_index` aborts
if the resolved output dir is inside a git worktree (worktree guard, duplicated
from the export skill so the two skills stay import-independent). Flag pointers
are 1-based line ranges into the source jsonl — never content.

Stdlib only. Python 3.11+.

Hook-feedback entry shape (verified empirically on this machine 2026-07-23 over
~/.claude/projects/*/*.jsonl — 8 sessions carrying each Stop-block marker):
A blocked Stop hook surfaces in TWO co-occurring entry shapes:
  1. user entry, isMeta=true, message.content is a STRING beginning
     "Stop hook feedback:\n[~/.claude/hooks/<hook>.py]: <block message>".
     This is the feedback injected back into the conversation and, per this
     module's own turn semantics, it STARTS the turn following the Stop.
  2. system entry, subtype "stop_hook_summary", top-level "hookErrors" (list[str]).
     Same message, attributed to the work turn that ended.
Detection keys ONLY on shape (1) — the injected user feedback string — because:
  - the design spec defines an actual fire as the block message "in the turn
    following a Stop", which is exactly this entry;
  - keying on both (1) and (2) would double-count one logical fire across two
    turns (they co-occur ~1:1);
  - a scan-everything approach false-positives on any session that reads/edits
    a hook's source OR this very file (both marker strings live in HOOK_MARKERS
    below), and on tool_result echoes of the same text. The "Stop hook feedback:"
    prefix is precise: a genuine human message won't carry it.
"""

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Callable, Iterator

EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
COMMIT_RE = re.compile(r"\bgit\s+commit\b")

# claude_md lens patterns (see lens_claude_md). CLAIM_RE is NOT redefined here —
# it is imported from the verify-claims hook so the two never drift.
BLANKET_GIT_ADD_RE = re.compile(r"\bgit\s+add\s+(?:-A\b|--all\b|\.(?:\s|$))")
FORCE_PUSH_RE = re.compile(r"\bpush\b[^\n|;&]*--force(?!-with-lease)")


def _load_hook(path: Path):
    """Import a repo hook module by file path (filenames carry dashes). We reuse
    the hooks' own analyze()/regexes rather than copy their logic."""
    # The hooks import their shared helper (_turn_window) as a plain top-level
    # module, which works when run as scripts because Python puts the script's
    # directory on sys.path. spec_from_file_location does NOT, so add it here or
    # the import fails on load.
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The hooks-replay lens reuses the regexes/analyze() from two Claude Code hooks —
# verify-claims.py and reflect-on-done.py — rather than re-implementing them, so
# it needs those hooks installed at Claude's config dir. They are optional: when
# either is missing the lens (and the claim-regex rule below) is skipped with one
# stderr line, so the other lenses still run on any Claude Code setup.
_CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
_HOOKS_DIR = _CLAUDE_DIR.expanduser().resolve() / "hooks"


def _optional_hook(name: str):
    path = _HOOKS_DIR / name
    if not path.exists():
        print(f"analyze: {path} not installed; hook-replay rules disabled", file=sys.stderr)
        return None
    return _load_hook(path)


_verify_claims = _optional_hook("verify-claims.py")
_reflect_on_done = _optional_hook("reflect-on-done.py")
HOOKS_AVAILABLE = _verify_claims is not None and _reflect_on_done is not None

# Literal Stop-hook block message fragment -> the hook that emits it.
HOOK_MARKERS = {
    "Unsupported verification claim": "verify-claims",
    "Work-closing turn detected": "reflect-on-done",
}

PROSE_CAP = 2000  # per-message prose cap for excerpts

# Lenses: Callable[[Session, Turn], list[Flag]] where Flag = {"rule", "match"}.
# Populated at the bottom of the file once the lens functions are defined.
LENSES: list[Callable] = []


def _blocks(message: dict) -> list:
    """Normalize a message's content to a list of blocks (mirrors the hooks)."""
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def _is_turn_start(entry: dict) -> bool:
    """A turn starts at a user entry with a real text block (not a tool_result
    echo). Replicates claude/hooks/verify-claims.py:analyze exactly."""
    if entry.get("type") != "user":
        return False
    return any(
        b.get("type") == "text" or isinstance(b.get("text"), str)
        for b in _blocks(entry.get("message", {}))
    )


def _hook_block_text(entry: dict) -> str:
    """Return the injected Stop-hook feedback string carried by this entry, or ""
    (see module docstring for why only this shape counts)."""
    if entry.get("type") == "user":
        content = entry.get("message", {}).get("content")
        if isinstance(content, str) and "Stop hook feedback:" in content:
            return content
    return ""


def _build_turn(turn_no: int, start_idx: int, end_idx: int, block: list) -> dict:
    start_entry = block[0]
    user_text = "\n".join(
        b.get("text", "")
        for b in _blocks(start_entry.get("message", {}))
        if b.get("type") == "text"
    )
    assistant_texts: list[str] = []
    tool_uses: list[dict] = []
    bash_exit_codes: list[int] = []
    tool_results = 0
    hook_feedback: list[str] = []

    for entry in block:
        etype = entry.get("type")
        blocks = _blocks(entry.get("message", {}))
        if etype == "assistant":
            for b in blocks:
                if b.get("type") == "text":
                    assistant_texts.append(b.get("text", ""))
                elif b.get("type") == "tool_use":
                    tool_uses.append(
                        {"name": b.get("name", ""), "input": b.get("input") or {}}
                    )
        elif etype == "user" and entry is not start_entry:
            for b in blocks:
                if b.get("type") == "tool_result":
                    tool_results += 1
                    # Transcripts expose no numeric exit code; is_error is the
                    # only failure signal, encoded 0 (ok) / 1 (error).
                    bash_exit_codes.append(1 if b.get("is_error") else 0)
        text = _hook_block_text(entry)
        if text:
            for marker, rule in HOOK_MARKERS.items():
                if marker in text and rule not in hook_feedback:
                    hook_feedback.append(rule)

    return {
        "turn": turn_no,
        "line_start": start_idx + 1,  # 1-based line pointer into source jsonl
        "line_end": end_idx + 1,
        # A Stop-hook injection is a user entry with string content, so
        # _is_turn_start (which must keep mirroring the hook's own segmentation)
        # necessarily opens a turn on it. That turn is an artifact of enforcement,
        # not work the user asked for, so report rates divide by real turns only.
        "hook_pseudo_turn": bool(_hook_block_text(start_entry)),
        # ISO8601 timestamp of the turn-start user entry (real transcripts carry
        # it; synthetic fixtures may not). Drives the report's by-week table.
        "timestamp": start_entry.get("timestamp"),
        "user_text": user_text,
        "assistant_texts": assistant_texts,
        "tool_uses": tool_uses,
        "tool_results": tool_results,
        "bash_exit_codes": bash_exit_codes,
        "hook_feedback": hook_feedback,
    }


def split_turns(entries: list[dict]) -> list[dict]:
    """Segment entries into turns. Entry index i maps to source line i+1, so
    iter_sessions must keep entries 1:1 with lines."""
    starts = [i for i, e in enumerate(entries) if _is_turn_start(e)]
    turns = []
    for n, si in enumerate(starts):
        ei = starts[n + 1] if n + 1 < len(starts) else len(entries)  # exclusive
        turns.append(_build_turn(n + 1, si, ei - 1, entries[si:ei]))
    return turns


def iter_sessions(root: Path) -> Iterator[dict]:
    """Yield one Session dict per transcript under <root>/*/projects/*/*.jsonl.
    Session = {source, project, session_id, path, entries}. A blank or
    unparseable line becomes an empty entry so index i stays == line i+1."""
    root = Path(root)
    for path in sorted(root.glob("*/projects/*/*.jsonl")):
        parts = path.relative_to(root).parts  # (source, "projects", slug, file)
        entries = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    entries.append({})
                    continue
                try:
                    entries.append(json.loads(stripped))
                except (json.JSONDecodeError, ValueError):
                    entries.append({})
        yield {
            "source": parts[0],
            "project": parts[2],
            "session_id": path.stem,
            "path": path,
            "entries": entries,
        }


def index_row(session: dict, turn: dict) -> dict:
    tools: dict[str, int] = {}
    for tu in turn["tool_uses"]:
        tools[tu["name"]] = tools.get(tu["name"], 0) + 1
    edited = any(tu["name"] in EDIT_TOOLS for tu in turn["tool_uses"])
    committed = any(
        tu["name"] == "Bash" and COMMIT_RE.search(str(tu["input"].get("command", "")))
        for tu in turn["tool_uses"]
    )
    return {
        "session": session["session_id"],
        "source": session["source"],
        "project": session["project"],
        "turn": turn["turn"],
        "timestamp": turn["timestamp"],
        "line_start": turn["line_start"],
        "line_end": turn["line_end"],
        "user_chars": len(turn["user_text"]),
        "assistant_chars": sum(len(t) for t in turn["assistant_texts"]),
        "tools": tools,
        "bash_fail": sum(1 for c in turn["bash_exit_codes"] if c),
        "edited": edited,
        "committed": committed,
        "hook_blocks": list(turn["hook_feedback"]),
        "hook_pseudo_turn": turn["hook_pseudo_turn"],
        "flags": [],  # filled by run_index after lenses run
    }


def write_flag(fh, session: dict, turn: dict, flag: dict) -> dict:
    """Write one flags.jsonl row. The pointer is a line range, never content."""
    row = {
        "flag_id": f"{session['session_id']}:{turn['turn']}:{flag['rule']}",
        "file": str(session["path"]),
        "session": session["session_id"],
        "source": session["source"],
        "turn": turn["turn"],
        "rule": flag["rule"],
        "match": flag["match"],
        "line_start": turn["line_start"],
        "line_end": turn["line_end"],
    }
    fh.write(json.dumps(row) + "\n")
    return row


INTERRUPT_MARKER = "Request interrupted by user"


def _interrupted_before_stop(session: dict, turn: dict) -> bool:
    """True if the user cut this turn off, so it never reached a Stop event.

    The interrupt marker is a user entry carrying a real text block, so by this
    module's own turn semantics it STARTS a turn — meaning it sits at exactly
    entries[line_end] (line_end is 1-based, so that index is the next entry) when
    it interrupted this turn. Checking only that one entry is deliberate: a marker
    further out belongs to a later turn and says nothing about this one. Substring
    match covers the "[... for tool use]" variant, which is equally a non-Stop."""
    entries = session["entries"]
    if turn["line_end"] >= len(entries):  # last turn in the session; nothing follows
        return False
    nxt = entries[turn["line_end"]]
    if nxt.get("type") != "user":
        return False
    return any(
        INTERRUPT_MARKER in (b.get("text") or "")
        for b in _blocks(nxt.get("message", {}))
    )


# --- Lenses (deterministic; each returns list[Flag] for one turn) --------------
# Invariant honored by every lens: AT MOST ONE flag per (rule, turn). flag_id is
# session:turn:rule and is the excerpt lookup key, so a duplicate rule in one turn
# would collide. Rules are namespaced per lens, so only within-lens duplicates are
# possible; each lens below emits any given rule at most once (first match wins).


def lens_hooks_replay(session: dict, turn: dict) -> list[dict]:
    """Hooks lens: actual fires (from Task 2's hook_blocks detection) plus
    would-fires (replay the repo's own hook analyze() over a single-turn slice).
    Would-fires exclude turns the user interrupted before Stop (see
    _interrupted_before_stop); recorded fires are never excluded."""
    flags: list[dict] = []
    if "verify-claims" in turn["hook_feedback"]:
        flags.append(
            {"rule": "hooks.verify_claims_fired", "match": "verify-claims Stop block"}
        )
    if "reflect-on-done" in turn["hook_feedback"]:
        flags.append(
            {"rule": "hooks.reflect_fired", "match": "reflect-on-done Stop block"}
        )

    # Replay only from here down: no Stop, no would-fire. The flags above are
    # observed Stop blocks, so an interrupt later in the turn can't invalidate them.
    if _interrupted_before_stop(session, turn):
        return flags

    # The hooks segment "the last real user message" themselves, so a single-turn
    # slice satisfies their turn model. final_text mirrors the live Stop payload
    # (the final assistant message the hooks receive via stdin); re-passing prose
    # already in the slice is idempotent for the regex/tool predicates.
    if not HOOKS_AVAILABLE:
        return flags
    entries = session["entries"][turn["line_start"] - 1 : turn["line_end"]]
    final_text = "\n".join(turn["assistant_texts"])
    with tempfile.TemporaryDirectory() as td:
        tf = Path(td) / "turn.jsonl"
        tf.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
        claim = _verify_claims.analyze(str(tf), final_text)
        if claim:
            flags.append({"rule": "hooks.verify_claims_would_fire", "match": claim})
        if _reflect_on_done.analyze(str(tf), final_text):
            flags.append(
                {
                    "rule": "hooks.reflect_would_fire",
                    "match": "work-closing turn without status-line close",
                }
            )
    return flags


def lens_claude_md(session: dict, turn: dict) -> list[dict]:
    """Mechanically-checkable CLAUDE.md rules (superset of the hooks)."""
    flags: list[dict] = []
    seen: set[str] = set()

    def add(rule: str, match: str) -> None:
        if rule not in seen:  # first match wins; one flag per (rule, turn)
            seen.add(rule)
            flags.append({"rule": rule, "match": match})

    prose = "\n".join(turn["assistant_texts"])
    claim = _verify_claims.CLAIM_RE.search(prose) if _verify_claims else None
    if claim and turn["tool_uses"]:
        # Claim + tools present: the hook would NOT fire (benefit of the doubt);
        # this captures the population for miss estimation. Deliberately NOT
        # interrupt-filtered like hooks.*_would_fire — this is a population count,
        # not a Stop prediction, so a cut-off turn still made the claim.
        add("claude_md.claim_with_tools", claim.group(0).strip())

    for tu in turn["tool_uses"]:
        if tu["name"] != "Bash":
            continue
        cmd = str(tu["input"].get("command", ""))
        ga = BLANKET_GIT_ADD_RE.search(cmd)
        if ga:
            add("claude_md.blanket_git_add", ga.group(0))
        fp = FORCE_PUSH_RE.search(cmd)
        if fp:
            add("claude_md.force_push", fp.group(0))
    return flags


LENSES = [lens_hooks_replay, lens_claude_md]


def assert_outside_worktree(path: Path) -> None:
    """Abort if `path` (or its nearest existing ancestor) is inside a git
    worktree — transcript-derived output must never enter a repo. Duplicated
    from the export skill so the two skills stay import-independent."""
    probe = Path(path).resolve()
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(probe), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return  # git absent -> nothing to guard against
    if result.returncode == 0 and result.stdout.strip() == "true":
        raise SystemExit(
            f"refusing to write analysis output inside a git worktree: {path}\n"
            "transcript-derived content must never enter a repo "
            "(set --out / $CLAUDE_TRANSCRIPT_DIR outside any checkout)."
        )


_HOOK_RULES = (
    "hooks.verify_claims_fired",
    "hooks.verify_claims_would_fire",
    "hooks.reflect_fired",
    "hooks.reflect_would_fire",
)


def _iso_week(ts) -> str:
    """ISO year-week bucket for a row timestamp; 'unknown' when absent/unparseable
    (synthetic fixtures carry no timestamp)."""
    if not isinstance(ts, str) or not ts:
        return "unknown"
    try:
        y, w, _ = date.fromisoformat(ts[:10]).isocalendar()
    except ValueError:
        return "unknown"
    return f"{y}-W{w:02d}"


def _write_report(out: Path, rows: list[dict]) -> None:
    """Aggregates ONLY — counts, rates, session ids, weeks. No message content,
    no match strings, no file paths ever enter report.md (privacy invariant)."""
    source_turns: Counter = Counter()
    source_rule: dict[str, Counter] = defaultdict(Counter)
    week_hooks: dict[str, Counter] = defaultdict(Counter)
    session_flags: Counter = Counter()
    rules: set[str] = set()

    pseudo = sum(1 for r in rows if r.get("hook_pseudo_turn"))
    for row in rows:
        src = row["source"]
        if not row.get("hook_pseudo_turn"):
            source_turns[src] += 1
        for rule in row["flags"]:
            rules.add(rule)
            source_rule[src][rule] += 1
            session_flags[row["session"]] += 1
            if rule in _HOOK_RULES:
                week_hooks[_iso_week(row.get("timestamp"))][rule] += 1

    real = len(rows) - pseudo
    lines = [
        "# Transcript analysis report",
        "",
        f"Turns indexed: {len(rows)} ({real} real, {pseudo} Stop-hook pseudo-turns)",
        "",
        "Rates below divide by REAL turns. A Stop-hook feedback injection opens a "
        "turn of its own (see `_build_turn`), and counting those as work turns "
        "dilutes every rate, unevenly across months. Caveat: `hooks.*_fired` is "
        "anchored to the injection turn by design, so its numerator can include "
        "turns excluded from the denominator.",
        "",
    ]

    lines += ["## Flag rates per source", ""]
    if rules:
        lines += ["| source | rule | flagged turns | rate |", "|---|---|---|---|"]
        # union: a source with flags but zero real turns must still appear
        for src in sorted(set(source_turns) | set(source_rule)):
            total = source_turns[src]
            for rule in sorted(rules):
                n = source_rule[src].get(rule, 0)
                if n:
                    rate = f"{n / total:.1%}" if total else "n/a"
                    lines.append(f"| {src} | {rule} | {n} | {rate} |")
    else:
        lines.append("_No flags raised._")
    lines.append("")

    lines += ["## Hook fires vs would-fires by ISO week", ""]
    lines += [
        "| week | verify_claims_fired | verify_claims_would_fire "
        "| reflect_fired | reflect_would_fire |",
        "|---|---|---|---|---|",
    ]
    for week in sorted(week_hooks):
        c = week_hooks[week]
        lines.append(
            f"| {week} | {c['hooks.verify_claims_fired']} "
            f"| {c['hooks.verify_claims_would_fire']} "
            f"| {c['hooks.reflect_fired']} | {c['hooks.reflect_would_fire']} |"
        )
    if not week_hooks:
        lines.append("| _(none)_ | 0 | 0 | 0 | 0 |")
    lines.append("")

    lines += ["## Top flagged sessions (by id)", ""]
    lines += ["| session | flags |", "|---|---|"]
    for sid, n in session_flags.most_common(10):
        lines.append(f"| {sid} | {n} |")
    if not session_flags:
        lines.append("| _(none)_ | 0 |")
    lines.append("")

    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")


def run_index(root: Path, out: Path) -> list[dict]:
    root, out = Path(root), Path(out)
    assert_outside_worktree(out)
    out.mkdir(parents=True, exist_ok=True)
    # Any pre-generated excerpt cache belongs to the index we are about to replace.
    # Excerpts are keyed by flag_id and resolved from flags.jsonl on demand, so a
    # leftover dir is pure staleness: in the 2026-08-10 audit a Jul-23 cache sat
    # beside a freshly rebuilt index, and labelers silently read the old excerpts
    # (or found none). Drop it -- every excerpt regenerates in milliseconds.
    stale = out / "excerpts"
    if stale.is_dir():
        shutil.rmtree(stale)
        print(f"dropped stale excerpt cache: {stale}", file=sys.stderr)
    rows: list[dict] = []
    with (
        open(out / "index.jsonl", "w", encoding="utf-8") as ifh,
        open(out / "flags.jsonl", "w", encoding="utf-8") as ffh,
    ):
        for session in iter_sessions(root):
            for turn in split_turns(session["entries"]):
                row = index_row(session, turn)
                flags: list[dict] = []
                for lens in LENSES:
                    flags.extend(lens(session, turn))
                row["flags"] = [f["rule"] for f in flags]
                for flag in flags:
                    write_flag(ffh, session, turn, flag)
                ifh.write(json.dumps(row) + "\n")
                rows.append(row)
    _write_report(out, rows)
    return rows


def _cap(text: str) -> str:
    return text if len(text) <= PROSE_CAP else text[:PROSE_CAP] + "…[truncated]"


def _render_entry(entry: dict) -> str:
    parts = []
    for b in _blocks(entry.get("message", {})):
        bt = b.get("type")
        if bt == "text":
            parts.append(_cap(b.get("text", "")))
        elif bt == "tool_use":
            parts.append(f"[tool_use {b.get('name', '')}]")
        elif bt == "tool_result":
            parts.append(
                "[tool_result error]" if b.get("is_error") else "[tool_result]"
            )
    text = _hook_block_text(entry)
    if text:
        parts.append(_cap(text))
    return ("\n  " + "\n  ".join(parts)) if parts else ""


# Emitted immediately after the Stop-block entry in an excerpt. A hooks.*_fired
# flag anchors to the INJECTION turn, so the excerpt necessarily contains the
# assistant's post-block correction -- which carries a status line precisely
# because the hook demanded one. The 2026-08-10 audit found labelers citing that
# correction as proof the hook misfired, scoring reflect_fired at 95% FP against a
# true 40%. The boundary is marked structurally so it cannot be missed again.
_BANNER_RULE = "=" * 78
BLOCK_BOUNDARY_BANNER = "\n".join(
    [
        _BANNER_RULE,
        "^^^ ABOVE = the turn that was BLOCKED. Judge ONLY this turn.",
        "vvv BELOW = the assistant's POST-BLOCK CORRECTION. A status line here is the",
        "    hook working as intended -- it is NEVER evidence the hook misfired.",
        _BANNER_RULE,
    ]
)
_STOP_BLOCK_MARKER = "Stop hook feedback:"


def render_excerpt(path: Path, line_start: int, line_end: int, context: int = 2) -> str:
    """Bounded excerpt: ±`context` lines around [line_start, line_end], each
    message's prose capped at PROSE_CAP, tool results elided to name/error.
    A Stop-block entry is followed by BLOCK_BOUNDARY_BANNER (see above)."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    lo = max(1, line_start - context)
    hi = min(len(lines), line_end + context)
    out = []
    banner_emitted = False
    for ln in range(lo, hi + 1):
        raw = lines[ln - 1].strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        rendered = _render_entry(entry)
        out.append(f"L{ln} [{entry.get('type', '?')}]" + rendered)
        if not banner_emitted and _STOP_BLOCK_MARKER in rendered:
            out.append(BLOCK_BOUNDARY_BANNER)
            banner_emitted = True
    return "\n".join(out)


def run_excerpt(out_dir: Path, flag_id: str, context: int = 2) -> str:
    flags_path = Path(out_dir) / "flags.jsonl"
    if not flags_path.exists():
        raise SystemExit(f"no flags.jsonl in {out_dir}; run `analyze.py index` first")
    for line in flags_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["flag_id"] == flag_id:
            return render_excerpt(
                Path(row["file"]), row["line_start"], row["line_end"], context
            )
    raise SystemExit(f"flag_id not found: {flag_id}")


def run_report(out_dir: Path) -> list[dict]:
    out = Path(out_dir)
    index_path = out / "index.jsonl"
    if not index_path.exists():
        raise SystemExit(f"no index.jsonl in {out}; run `analyze.py index` first")
    rows = [
        json.loads(line)
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    _write_report(out, rows)
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_index = sub.add_parser(
        "index", help="build index.jsonl + flags.jsonl + report.md"
    )
    p_index.add_argument("root")
    p_index.add_argument("--out", default=None, help="default <root>/analysis/")

    p_excerpt = sub.add_parser("excerpt", help="bounded excerpt for a flag_id")
    p_excerpt.add_argument("out_dir")
    p_excerpt.add_argument("flag_id")
    p_excerpt.add_argument("--context", type=int, default=2)

    p_report = sub.add_parser("report", help="(re)write report.md from index.jsonl")
    p_report.add_argument("out_dir")

    args = parser.parse_args(argv)
    if args.cmd == "index":
        out = Path(args.out) if args.out else Path(args.root) / "analysis"
        rows = run_index(args.root, out)
        print(f"indexed {len(rows)} turns -> {out}")
    elif args.cmd == "excerpt":
        print(run_excerpt(args.out_dir, args.flag_id, args.context))
    elif args.cmd == "report":
        run_report(args.out_dir)
        print(f"report -> {Path(args.out_dir) / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
