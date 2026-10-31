#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Benchmark and acceptance checks for the agent-transcripts index. Not a pytest module.

    uv run --script bench_transcripts.py rebuild  --dest SCRATCH --raw RAW_DIR [--runs 3]
    uv run --script bench_transcripts.py review   --dest ROOT [--sessions 5] [--runs 3]
    uv run --script bench_transcripts.py golden capture|compare --dest ROOT --findings DB
    uv run --script bench_transcripts.py evidence --dest ROOT --findings DB

`--code-root` (default: this module) is the modules/agent-transcripts checkout whose
scripts are run, so the same commands measure an older version. `rebuild` only builds
into a scratch root whose `raw` is a symlink to RAW_DIR, never into a live cache.
`review`, `golden` and `evidence` only read the index and findings.db.

Output is numbers, session ids and counts only. Rendered transcript text goes only to
the golden files, under `<dest>/bench/golden/` unless `--golden` says otherwise.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import re
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MODULE = Path(__file__).resolve().parent.parent
GREP_PATTERN = "error|fail"
TIMING_RE = re.compile(r"(\w+)=([\d.]+)s\b")
COUNT_RE = re.compile(r"(\w+)=(\d+)\b")


def uv(code_root: Path, skill: str, name: str, *args: str) -> list[str]:
    return ["uv", "run", "--quiet", "--script", str(code_root / "skills" / skill / name), *args]


def run_timed(cmd: list[str]) -> dict:
    """Wall time and peak RSS (of the whole process tree, via /usr/bin/time -v)."""
    with tempfile.NamedTemporaryFile("r", suffix=".time") as report:
        t0 = time.monotonic()
        proc = subprocess.run(
            ["/usr/bin/time", "-v", "-o", report.name, *cmd], capture_output=True, text=True
        )
        wall = time.monotonic() - t0
        rss_kb = next(
            int(line.rsplit(":", 1)[1])
            for line in report.read().splitlines()
            if "Maximum resident set size" in line
        )
    return {"wall": wall, "rss_mb": rss_kb / 1024, "rc": proc.returncode,
            "out": proc.stdout, "err": proc.stderr}


def read_only(db: Path) -> sqlite3.Connection:
    if not db.exists():
        raise SystemExit(f"no database at {db}")
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def _stable_order(row: tuple) -> str:
    return hashlib.sha256(f"{row[0]}/{row[1]}".encode()).hexdigest()


def unique_sessions(conn: sqlite3.Connection) -> list[tuple[str, str, int]]:
    """(harness, native_id, messages) for every session `review.py view <native_id>` can
    open: its native_id is unique and not all digits (those resolve as a numeric id)."""
    rows = conn.execute(
        "SELECT s.harness, s.native_id,"
        " (SELECT count(*) FROM messages m WHERE m.session_id = s.id) FROM sessions s"
        " WHERE s.native_id IN"
        " (SELECT native_id FROM sessions GROUP BY native_id HAVING count(*) = 1)"
    ).fetchall()
    return [r for r in rows if not r[1].isdigit()]


def pick_sessions(conn: sqlite3.Connection, n: int) -> list[tuple[str, str, str, int]]:
    """The n largest sessions plus n others in a hash order that stays put as the index
    changes, as (kind, harness, native_id, messages)."""
    rows = sorted(unique_sessions(conn), key=lambda r: (-r[2], r[0], r[1]))
    sampled = sorted(rows[n:], key=_stable_order)[:n]
    return [("largest", *r) for r in rows[:n]] + [("sampled", *r) for r in sampled]


# ------------------------------------------------------------------ rebuild


def cmd_rebuild(a) -> int:
    dest, raw = a.dest.resolve(), a.raw.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    link = dest / "raw"
    if link.exists() and not link.is_symlink():
        raise SystemExit(f"{link} is a real directory: --dest must be a scratch root")
    if not link.is_symlink():
        link.symlink_to(raw)
    elif link.resolve() != raw:
        raise SystemExit(f"{link} points at another raw dir; use a fresh --dest")
    logs = dest / "bench"
    logs.mkdir(exist_ok=True)

    runs = []
    for i in range(1, a.runs + 1):
        r = run_timed(uv(a.code_root, "transcript-ingest", "transcripts.py",
                         "ingest", "--rebuild", "--dest", str(dest)))
        (logs / f"rebuild-{i}.stderr").write_text(r["err"])
        summary = [ln for ln in r["out"].splitlines() if ln.startswith("ingest:")]
        if not summary:  # rc alone cannot tell: before 0.9.0 it was the parse-error count
            print(f"run {i}: failed rc={r['rc']}; see {logs / f'rebuild-{i}.stderr'}")
            return 1
        phases = {k: float(v) for ln in r["err"].splitlines() if ln.startswith("timing:")
                  for k, v in TIMING_RE.findall(ln)}
        counts = " ".join(f"{k}={v}" for k, v in COUNT_RE.findall(summary[0]))
        print(f"run {i}: rc={r['rc']} wall={r['wall']:.1f}s peak_rss={r['rss_mb']:.0f}MB "
              + " ".join(f"{k}={v:.1f}s" for k, v in phases.items()) + f" {counts}")
        runs.append((r, phases))

    med = statistics.median
    print(f"median of {len(runs)}: wall={med(r['wall'] for r, _ in runs):.1f}s"
          f" peak_rss={med(r['rss_mb'] for r, _ in runs):.0f}MB "
          + " ".join(f"{k}={med(p.get(k, 0.0) for _, p in runs):.1f}s" for k in runs[-1][1]))

    db = dest / "transcripts.db"
    conn = read_only(db)
    sizes = conn.execute(
        "SELECT name, sum(pgsize) FROM dbstat GROUP BY name ORDER BY 2 DESC"
    ).fetchall()
    conn.close()
    print(f"database: {db.stat().st_size / 1e9:.3f} GB")
    for name, size in sizes:
        print(f"  {name}: {size / 1e6:.1f} MB")
    return 0


# ------------------------------------------------------------------- review


def cmd_review(a) -> int:
    dest = str(a.dest)
    conn = read_only(a.dest / "transcripts.db")
    picks = pick_sessions(conn, a.sessions)
    conn.close()

    def timed(cmd: list[str]) -> str:
        rs = [run_timed(cmd) for _ in range(a.runs)]
        return (f"{statistics.median(r['wall'] for r in rs):.2f}s"
                f" rss={max(r['rss_mb'] for r in rs):.0f}MB rc={rs[-1]['rc']}")

    print(f"queue: {timed(uv(a.code_root, 'transcript-review', 'review.py', '--dest', dest, 'queue', '--unreviewed', '--limit', '20'))}")
    print(f"sweep: {timed(uv(a.code_root, 'transcript-sweep', 'sweep.py', '--dest', dest, '--no-db'))}")
    for kind, harness, native_id, messages in picks:
        view = timed(uv(a.code_root, "transcript-review", "review.py", "--dest", dest,
                        "view", native_id))
        grep = timed(uv(a.code_root, "transcript-review", "review.py", "--dest", dest,
                        "grep", native_id, GREP_PATTERN))
        print(f"{kind} {harness}/{native_id} messages={messages} view={view} grep={grep}")
    return 0


# ------------------------------------------------------------------- golden


def _render(a, native_id: str) -> dict[str, str]:
    """`view` and `grep` output for one session, each prefixed by its exit code."""
    out = {}
    for what, args in (("view", ["view", native_id]),
                       ("grep", ["grep", native_id, GREP_PATTERN])):
        proc = subprocess.run(uv(a.code_root, "transcript-review", "review.py",
                                 "--dest", str(a.dest), *args), capture_output=True, text=True)
        out[what] = f"rc={proc.returncode}\n{proc.stdout}"
    return out


def cmd_golden(a) -> int:
    golden = a.golden or a.dest / "bench" / "golden"
    if a.action == "capture":
        conn = read_only(a.dest / "transcripts.db")
        viewable = {(h, n) for h, n, _ in unique_sessions(conn)}
        sample = [[kind, h, n] for kind, h, n, _ in pick_sessions(conn, a.sessions)]
        conn.close()
        fconn = read_only(a.findings)
        reviewed = [r for r in fconn.execute(
            "SELECT DISTINCT harness, native_id FROM review_flags WHERE present = 1"
        ) if r in viewable]
        fconn.close()
        sample += [["reviewed", h, n] for h, n in sorted(reviewed, key=_stable_order)[:a.sessions]]
        golden.mkdir(parents=True, exist_ok=True)
        (golden / "sample.json").write_text(json.dumps(sample, indent=1) + "\n")
        for i, (_, _, native_id) in enumerate(sample):
            for what, text in _render(a, native_id).items():
                (golden / f"{i:03d}.{what}.txt").write_text(text)
        print(f"golden capture: sessions={len(sample)} into {golden}")
        return 0

    sample = json.loads((golden / "sample.json").read_text())
    differing = 0
    for i, (kind, harness, native_id) in enumerate(sample):
        for what, now in _render(a, native_id).items():
            then = (golden / f"{i:03d}.{what}.txt").read_text()
            if now == then:
                continue
            differing += 1
            changed = sum(
                1 for ln in difflib.unified_diff(then.splitlines(), now.splitlines(),
                                                 lineterm="", n=0)
                if ln[:1] in "+-" and not ln.startswith(("+++", "---"))
            )
            print(f"differs: {kind} {harness}/{native_id} {what}"
                  f" golden_lines={len(then.splitlines())} now_lines={len(now.splitlines())}"
                  f" changed_lines={changed}")
    print(f"golden compare: sessions={len(sample)} differing_outputs={differing}")
    return 1 if differing else 0


# ----------------------------------------------------------------- evidence


def _load_review(code_root: Path):
    """review.py from the code root, so the check is the one `record` applies there."""
    path = code_root / "skills" / "transcript-review" / "review.py"
    spec = importlib.util.spec_from_file_location("bench_review", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cmd_evidence(a) -> int:
    review = _load_review(a.code_root)
    conn = read_only(a.dest / "transcripts.db")
    fconn = read_only(a.findings)
    checked = ok = failed = missing = ambiguous = 0
    for harness, native_id, category, ord_, quote in fconn.execute(
        "SELECT harness, native_id, category, evidence_ord, quote FROM review_flags"
        " WHERE present = 1 ORDER BY id"
    ):
        checked += 1
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM sessions WHERE harness = ? AND native_id = ?", (harness, native_id)
        )]
        if not ids:
            missing += 1
            print(f"missing: {harness}/{native_id} {category}")
            continue
        ambiguous += len(ids) > 1
        needle = review.quote_needle(quote or "")
        haystacks = [review.message_haystack(conn, sid, ord_, harness) for sid in ids]
        if any(h is not None and needle in review.normalize(h) for h in haystacks):
            ok += 1
        else:
            failed += 1
            print(f"failed: {harness}/{native_id} {category} ord={ord_}")
    print(f"evidence: checked={checked} ok={ok} failed={failed}"
          f" missing_session={missing} ambiguous_session={ambiguous}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dest", type=Path, required=True, help="cache root to use")
    common.add_argument("--code-root", type=Path, default=MODULE,
                        help="a modules/agent-transcripts directory (default: this one)")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    rb = sub.add_parser("rebuild", parents=[common], help="time full rebuilds into a scratch root")
    rb.add_argument("--raw", type=Path, required=True, help="the raw/ directory to index")
    rb.add_argument("--runs", type=int, default=3)
    rb.set_defaults(func=cmd_rebuild)

    rv = sub.add_parser("review", parents=[common], help="time queue, sweep, view and grep")
    rv.add_argument("--sessions", type=int, default=5, help="largest and sampled, each")
    rv.add_argument("--runs", type=int, default=3)
    rv.set_defaults(func=cmd_review)

    gd = sub.add_parser("golden", parents=[common], help="capture or compare view/grep output")
    gd.add_argument("action", choices=["capture", "compare"])
    gd.add_argument("--findings", type=Path, required=True, help="findings.db (read-only)")
    gd.add_argument("--sessions", type=int, default=10,
                    help="largest, sampled and reviewed sessions, each")
    gd.add_argument("--golden", type=Path, help="golden dir (default <dest>/bench/golden)")
    gd.set_defaults(func=cmd_golden)

    ev = sub.add_parser("evidence", parents=[common],
                        help="check every recorded quote still resolves at its ord")
    ev.add_argument("--findings", type=Path, required=True, help="findings.db (read-only)")
    ev.set_defaults(func=cmd_evidence)

    a = ap.parse_args(argv)
    a.code_root = a.code_root.resolve()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
