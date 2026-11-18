#!/usr/bin/env python3
"""repo-sweep — the ledger and the work queue behind the repo-sweep skills.

Stdlib only. One sqlite database per repository, kept outside the checkout, holds every
finding and its status across runs. `next` hands out work as brief files, and `record`
refuses a finding or a proof whose quoted code is not in the file, so a model cannot
report code it did not read. REPO_SWEEP_GH overrides the gh binary for tests.
Final stdout line is a stable interface:  repo-sweep: <verb> <summary>
"""
import argparse
import bisect
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

GH = os.environ.get("REPO_SWEEP_GH", "gh")
# What a brief tells a child to run: the short name where a harness put bin/ on PATH, else this file.
CMD = "repo-sweep" if shutil.which("repo-sweep") else f"python3 {Path(__file__).resolve()}"
LENSES = {
    "simplify": "code that can be deleted, inlined, or replaced by something this repository or the "
                "standard library already has, with no change in behaviour",
    "cleanliness": "dead code, names or comments that mislead, duplicated logic, one thing done two ways",
    "bugs": "behaviour that is wrong on a normal input: a wrong condition, an unhandled failure, a leaked "
            "resource, a race",
    "edge-cases": "an input or state the code does not handle: empty, missing, very large, malformed, "
                  "concurrent, a boundary value",
    "performance": "work that is wasteful on a realistic input: repeated I/O, a quadratic loop, a needless "
                   "subprocess or copy",
}
SEVERITIES = ("high", "medium", "low")
VERDICTS = ("confirmed", "rejected", "unproven", "fixed")
STATUSES = ("candidate", "confirmed", "rejected", "unproven", "recheck", "pr-open", "fixed", "needs-human",
            "wontfix")
AGENTS = {"find": "repo-sweep:finder", "validate": "repo-sweep:validator", "fix": "repo-sweep:fixer"}
LOCKFILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "Cargo.lock", "go.sum", "poetry.lock", "uv.lock"}
MIN_QUOTE = 12
MAX_ATTEMPTS = 2
SCHEMA = """
CREATE TABLE IF NOT EXISTS parts(name TEXT PRIMARY KEY, files TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS units(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, part TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, findings TEXT);
CREATE TABLE IF NOT EXISTS findings(id INTEGER PRIMARY KEY AUTOINCREMENT, file TEXT NOT NULL, line INTEGER NOT NULL,
  quote TEXT NOT NULL, lens TEXT NOT NULL, severity TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL,
  status TEXT NOT NULL, proof TEXT, pr TEXT, note TEXT, first_seen TEXT NOT NULL, updated TEXT NOT NULL);
"""


def out(verb, msg):
    print(f"repo-sweep: {verb} {msg}")


def git(*args, check=True):
    return subprocess.run(["git", *args], text=True, capture_output=True, check=check).stdout


def locate():
    """(checkout root, this repository's state directory). Worktrees and clones of one origin share it."""
    root = Path(git("rev-parse", "--show-toplevel").strip())
    ident = git("remote", "get-url", "origin", check=False).strip() or \
        git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    name = "-".join(p for p in re.split(r"[/:]", re.sub(r"(/?\.git)?/?$", "", ident))[-2:] if p)
    key = re.sub(r"[^A-Za-z0-9._-]+", "-", name) + "-" + hashlib.sha1(ident.encode()).hexdigest()[:8]
    home = os.environ.get("REPO_SWEEP_HOME") or \
        Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "repo-sweep"
    return root, Path(home) / key


def norm(text):
    return " ".join(str(text).split())


def find_quote(path, quote):
    """1-based line where the whitespace-normalized quote starts, or None."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    text, starts = "", []
    for line in lines:
        starts.append(len(text))
        if line.strip():
            text += norm(line) + " "
    at = text.find(quote)
    return bisect.bisect_right(starts, at) if at >= 0 else None


def anchor(root, file, quote):
    """(line, None) when the quote is in the file, else (None, the reason to show the model)."""
    quote, path = norm(quote), root / str(file)
    if len(quote) < MIN_QUOTE:
        return None, f"quote is shorter than {MIN_QUOTE} characters"
    if not file or not path.resolve().is_relative_to(root) or not path.is_file():
        return None, f"no file '{file}' under the repository root (give the path relative to it)"
    line = find_quote(path, quote)
    if line is None:
        return None, f"quote is not in {file}: copy the code exactly, do not retype or shorten it"
    return line, None


def set_status(db, fid, status, **cols):
    cols.update(status=status, updated=date.today().isoformat())
    db.execute(f"UPDATE findings SET {', '.join(c + '=?' for c in cols)} WHERE id=?", (*cols.values(), fid))


def part_files(db, part):
    row = db.execute("SELECT files FROM parts WHERE name=?", (part,)).fetchone()
    return json.loads(row["files"]) if row else []


def part_of(db):
    return {f: p["name"] for p in db.execute("SELECT * FROM parts") for f in json.loads(p["files"])}


def open_in(db, files):
    """Findings in these files that still need a verdict."""
    rows, files = db.execute("SELECT * FROM findings WHERE status IN ('candidate','recheck') ORDER BY id"), set(files)
    return [r for r in rows if r["file"] in files]


def line_of(f):
    return f"#{f['id']} [{f['status']}] {f['severity']} {f['lens']} {f['file']}:{f['line']} - {f['title']}"


# ---- sync: bring the ledger up to date with merged PRs and the code as it is now

def sync(db, root):
    db.execute("DELETE FROM units")  # the queue belongs to one run; the findings are what persists
    for (pr,) in db.execute("SELECT DISTINCT pr FROM findings WHERE status='pr-open'").fetchall():
        r = subprocess.run([GH, "pr", "view", pr, "--json", "state", "-q", ".state"], text=True, capture_output=True)
        state = r.stdout.strip()
        if r.returncode:
            print(f"warning: could not read {pr}: {r.stderr.strip()}", file=sys.stderr)
        for (fid,) in db.execute("SELECT id FROM findings WHERE status='pr-open' AND pr=?", (pr,)).fetchall():
            if state == "MERGED":
                set_status(db, fid, "fixed")
            elif state == "CLOSED":
                set_status(db, fid, "confirmed", pr=None, note=f"PR closed without merging: {pr}")
    for f in db.execute("SELECT * FROM findings WHERE status IN ('candidate','confirmed','unproven')").fetchall():
        line = find_quote(root / f["file"], f["quote"])
        if not (root / f["file"]).is_file():  # no part will ever hold it, so no validator could settle it
            set_status(db, f["id"], "fixed" if f["status"] == "confirmed" else "rejected", note="its file was removed")
        elif line is None:
            set_status(db, f["id"], "recheck", note="its quoted code is no longer in the file")
        elif line != f["line"]:
            db.execute("UPDATE findings SET line=? WHERE id=?", (line, f["id"]))


def counts(db):
    rows = db.execute("SELECT status, COUNT(*) n FROM findings GROUP BY status").fetchall()
    return ", ".join(f"{r['n']} {r['status']}" for r in rows) or "no findings"


def cmd_sync(a, db, root, work):
    sync(db, root)
    out("sync", counts(db))


# ---- plan: split the repository into parts and queue one find unit per part

def scan(root, paths):
    """{path: characters} for every tracked text file, and the paths left out."""
    sizes, skipped = {}, []
    for rel in filter(None, git("ls-files", "-z", "--", *paths).split("\0")):
        path = root / rel
        text = None
        if not path.is_symlink() and path.name not in LOCKFILES:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                pass
        if text is None or "\0" in text:
            skipped.append(rel)
        elif text:
            sizes[rel] = len(text)
    return sizes, skipped


def split(files, sizes, budget, depth=0):
    """Group sorted paths into parts of at most `budget` characters, keeping a directory together
    when it fits and merging small neighbours. A single file over the budget is a part by itself."""
    def size(part):
        return sum(sizes[f] for f in part)
    if len(files) == 1 or size(files) <= budget:
        return [files]
    groups = {}
    for f in files:
        groups.setdefault(f.split("/")[depth], []).append(f)
    parts = [p for g in groups.values() for p in split(g, sizes, budget, depth + 1)]
    merged = [parts[0]]
    for p in parts[1:]:
        if size(merged[-1]) + size(p) <= budget:
            merged[-1] = merged[-1] + p
        else:
            merged.append(p)
    return merged


def cmd_plan(a, db, root, work):
    sync(db, root)
    sizes, skipped = scan(root, a.paths)
    if not sizes:
        sys.exit("repo-sweep: plan found no tracked text files")
    db.execute("DELETE FROM parts")
    seen = {}
    for files in split(sorted(sizes), sizes, a.chars):
        name = (os.path.commonpath(files) if len(files) > 1 else files[0]) or "."
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            name = f"{name}#{seen[name]}"
        db.execute("INSERT INTO parts VALUES (?,?)", (name, json.dumps(files)))
        db.execute("INSERT INTO units(kind, part) VALUES ('find', ?)", (name,))
        print(f"part {name}: {len(files)} files, {sum(sizes[f] for f in files)} chars")
    n = db.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
    out("plan", f"{n} parts, {len(sizes)} files, {len(skipped)} skipped (binary, lockfile or unreadable); "
                f"ledger: {counts(db)}")


# ---- next: claim pending units and write a brief file for each

RETRY = """`record` prints `accepted`, `duplicate` or `rejected: <reason>` for each entry. Its last line is
`repo-sweep: record unit {id} done` or `repo-sweep: record unit {id} still open`. While it says still open,
correct the rejected entries and run `record` again with all of your entries (repeats are harmless). If an
entry is rejected twice, leave it out. Your work is finished only when the last line says `done`."""


def brief_find(db, root, unit):
    files = part_files(db, unit["part"])
    here = set(files)
    known = [f for f in db.execute("SELECT * FROM findings ORDER BY id") if f["file"] in here]
    return f"""# repo-sweep unit {unit['id']}: find issues in part `{unit['part']}`

Repository root: {root}
Review exactly these {len(files)} files. Paths are relative to the root.

{chr(10).join('- ' + f for f in files)}

## Passes

Make one pass per lens, in this order. Finish one pass before you start the next.

{chr(10).join(f'- `{k}`: {v}' for k, v in LENSES.items())}

## Already in the ledger: do not report these again

{chr(10).join('- ' + line_of(f) for f in known) or 'Nothing yet.'}

## Report

Run this from the repository root. Use one object per finding, or `"findings": []` when there are none.

```
{CMD} record {unit['id']} <<'REPO_SWEEP_JSON'
{{"findings": [
  {{"file": "path/from/the/root.py",
    "quote": "one line of the code at fault, copied exactly from the file ({MIN_QUOTE} characters or more)",
    "lens": "bugs",
    "severity": "high, medium or low",
    "title": "one sentence that says what is wrong",
    "detail": "why it is wrong, and the input or state that shows it"}}
]}}
REPO_SWEEP_JSON
```

{RETRY.format(id=unit['id'])}
"""


def describe(f):
    return f"""### {line_of(f)}

- Quoted code: `{f['quote']}`
- Claim: {f['detail']}
{'- Proof: ' + f['proof'] if f['proof'] else ''}
{'- Note: ' + f['note'] if f['note'] else ''}""".rstrip()


def brief_validate(root, unit, findings):
    return f"""# repo-sweep unit {unit['id']}: validate findings in part `{unit['part']}`

Repository root: {root}
Each finding below is a claim, not a fact. Decide every one yourself from the code.
A finding marked `[recheck]` was valid earlier, but its quoted code is no longer in the file: find out
whether the issue was fixed (`fixed`) or the code only moved or changed shape (`confirmed`, with the new code
as the first evidence entry).

{chr(10).join(describe(f) + chr(10) for f in findings)}
## Report

Run this from the repository root, with one verdict for every finding above.

```
{CMD} record {unit['id']} <<'REPO_SWEEP_JSON'
{{"verdicts": [
  {{"id": {findings[0]['id']},
    "verdict": "confirmed, rejected, unproven or fixed",
    "proof": "what you did and what it showed",
    "evidence": [{{"file": "path/from/the/root.py", "quote": "code copied exactly from the file"}}],
    "command": "the exact command you ran, when you ran one",
    "output": "the part of its output that proves the point"}}
]}}
REPO_SWEEP_JSON
```

`confirmed` needs proof a reader can check: at least one `evidence` entry, or a `command` with its `output`.
`evidence`, `command` and `output` are optional for the other verdicts. `fixed` is only for a `[recheck]` finding.

{RETRY.format(id=unit['id'])}
"""


def brief_fix(unit, findings):
    return f"""# repo-sweep unit {unit['id']}: fix confirmed findings in part `{unit['part']}`

Work only in the worktree named in your prompt. File paths below are relative to its root.
Each finding was validated with the proof shown. Fix each one, or skip it and say why.

{chr(10).join(describe(f) + chr(10) for f in findings)}
## Report

After you commit, run this from the worktree, with one result for every finding above.

```
{CMD} record {unit['id']} <<'REPO_SWEEP_JSON'
{{"results": [
  {{"id": {findings[0]['id']},
    "outcome": "fixed or skipped",
    "note": "what you changed and how you checked it, or why you skipped it"}}
]}}
REPO_SWEEP_JSON
```

{RETRY.format(id=unit['id'])}
"""


def queue_fixes(db):
    """One pending fix unit per part for confirmed findings that no fix unit of this run holds yet."""
    held = {i for u in db.execute("SELECT findings FROM units WHERE kind='fix'") for i in json.loads(u["findings"])}
    home, groups = part_of(db), {}
    for f in db.execute("SELECT id, file FROM findings WHERE status='confirmed' ORDER BY id"):
        if f["id"] not in held:
            groups.setdefault(home.get(f["file"]) or os.path.dirname(f["file"]) or ".", []).append(f["id"])
    for part, ids in groups.items():
        db.execute("INSERT INTO units(kind, part, findings) VALUES ('fix', ?, ?)", (part, json.dumps(ids)))


def cmd_next(a, db, root, work):
    if a.fix:
        queue_fixes(db)
    kinds = "('fix')" if a.fix else "('find','validate')"
    (work / "briefs").mkdir(parents=True, exist_ok=True)
    claimed = 0
    for unit in db.execute(f"SELECT * FROM units WHERE state='pending' AND kind IN {kinds} ORDER BY id").fetchall():
        if claimed == a.n:
            break
        if unit["kind"] == "find":
            text, extra = brief_find(db, root, unit), ""
        else:
            ids = json.loads(unit["findings"]) if unit["findings"] else \
                [f["id"] for f in open_in(db, part_files(db, unit["part"]))]
            marks = ",".join("?" * len(ids))
            findings = db.execute(f"SELECT * FROM findings WHERE id IN ({marks}) ORDER BY id", ids).fetchall()
            db.execute("UPDATE units SET findings=? WHERE id=?", (json.dumps(ids), unit["id"]))
            if unit["kind"] == "validate":
                text, extra = brief_validate(root, unit, findings), ""
            else:
                slug = re.sub(r"[^a-z0-9]+", "-", unit["part"].lower()).strip("-") or "root"
                text, extra = brief_fix(unit, findings), f" branch=sweep-{slug}-u{unit['id']}"
        path = work / "briefs" / f"unit-{unit['id']}.md"
        path.write_text(text, encoding="utf-8")
        db.execute("UPDATE units SET state='claimed', attempts=attempts+1 WHERE id=?", (unit["id"],))
        print(f"unit {unit['id']} {unit['kind']} agent={AGENTS[unit['kind']]} brief={path}{extra}")
        claimed += 1
    left = dict(db.execute(f"SELECT state, COUNT(*) FROM units WHERE kind IN {kinds} GROUP BY state").fetchall())
    pending, running = left.get("pending", 0), left.get("claimed", 0)
    failed = f", {left['failed']} failed" if left.get("failed") else ""
    out("next", f"done{failed}" if not pending and not running else
        f"claimed {claimed}, {pending} pending, {running} running{failed}")


# ---- record: a child agent's report, checked before it is believed

def record_find(db, root, unit, entries):
    files, problems, today = set(part_files(db, unit["part"])), [], date.today().isoformat()
    for i, f in enumerate(entries, 1):
        line, err = None, None
        missing = [k for k in ("file", "quote", "lens", "severity", "title", "detail") if not norm(f.get(k) or "")]
        if missing:
            err = "missing " + ", ".join(missing)
        elif f["lens"] not in LENSES:
            err = f"lens must be one of {', '.join(LENSES)}"
        elif f["severity"] not in SEVERITIES:
            err = f"severity must be one of {', '.join(SEVERITIES)}"
        elif f["file"] not in files:
            err = f"{f['file']} is not in this unit's file list"
        else:
            line, err = anchor(root, f["file"], f["quote"])
        if err:
            problems.append(f"finding {i}: {err}")
            continue
        key = (f["file"], norm(f["quote"]), f["lens"])
        dup = db.execute("SELECT id FROM findings WHERE file=? AND quote=? AND lens=?", key).fetchone()
        if dup:
            print(f"duplicate: finding {i} is already #{dup['id']}")
            continue
        cur = db.execute(
            "INSERT INTO findings(file, quote, lens, line, severity, title, detail, status, first_seen, updated) "
            "VALUES (?,?,?,?,?,?,?,'candidate',?,?)",
            (*key, line, f["severity"], norm(f["title"]), norm(f["detail"]), today, today))
        print(f"accepted: #{cur.lastrowid} {norm(f['title'])}")
    return problems


def record_validate(db, root, unit, entries):
    ids = json.loads(unit["findings"])
    todo = {f["id"]: f for f in db.execute("SELECT * FROM findings WHERE status IN ('candidate','recheck')")
            if f["id"] in ids}
    problems, missing = [], set(todo)
    for v in entries:
        f = todo.get(v.get("id"))
        missing.discard(v.get("id"))
        if not f and v.get("id") in ids:
            print(f"duplicate: #{v['id']} already has its verdict")  # a retry resends every entry
            continue
        if not f:
            problems.append(f"verdict for #{v.get('id')}: not a finding of this unit")
            continue
        verdict, proof, err, anchors = v.get("verdict"), [norm(v.get("proof") or "")], None, []
        if verdict not in VERDICTS:
            err = f"verdict must be one of {', '.join(VERDICTS)}"
        elif not proof[0]:
            err = "proof is empty"
        elif verdict == "fixed" and f["status"] != "recheck":
            err = "fixed is only for a [recheck] finding; use rejected when the claim is wrong"
        for e in v.get("evidence") or []:
            e = e if isinstance(e, dict) else {}
            line, e_err = anchor(root, e.get("file"), e.get("quote"))
            err = err or (e_err and f"evidence: {e_err}")
            if line:
                anchors.append((e["file"], line, norm(e["quote"])))
                proof.append(f"evidence: {e['file']}:{line} `{norm(e['quote'])}`")
        ran = norm(v.get("command") or "") and norm(v.get("output") or "")
        if ran:
            proof.append(f"command: {norm(v['command'])}\noutput: {str(v['output']).strip()}")
        cols = {"proof": "\n".join(proof), "note": None}
        if verdict == "confirmed" and not err:
            if not anchors and not ran:
                err = "confirmed needs an evidence entry (file and exact quote) or a command with its output"
            elif f["status"] == "recheck" and not anchors:
                err = "a confirmed [recheck] finding needs an evidence entry showing where the issue is now"
            elif f["status"] == "recheck":
                cols["file"], cols["line"], cols["quote"] = anchors[0]
        if err:
            problems.append(f"verdict for #{f['id']}: {err}")
            continue
        set_status(db, f["id"], verdict, **cols)
        del todo[f["id"]]  # a second verdict for one finding in the same report is rejected above
        print(f"accepted: #{f['id']} {verdict}")
    return problems + [f"no verdict for #{i}" for i in sorted(missing)]


def record_fix(db, root, unit, entries):
    ids, results, problems = json.loads(unit["findings"]), {}, []
    for r in entries:
        if r.get("id") not in ids:
            problems.append(f"result for #{r.get('id')}: not a finding of this unit")
        elif r.get("outcome") not in ("fixed", "skipped") or not norm(r.get("note") or ""):
            problems.append(f"result for #{r['id']}: needs outcome fixed or skipped, and a note")
        else:
            results[r["id"]] = r
    problems += [f"no result for #{i}" for i in ids if i not in results]
    if problems:
        return problems
    for i, r in results.items():
        if r["outcome"] == "skipped":
            set_status(db, i, "needs-human", note="fixer skipped it: " + norm(r["note"]))
        else:
            db.execute("UPDATE findings SET note=? WHERE id=?", (norm(r["note"]), i))
        print(f"accepted: #{i} {r['outcome']}")
    return []


def cmd_record(a, db, root, work):
    unit = db.execute("SELECT * FROM units WHERE id=?", (a.unit,)).fetchone()
    if not unit or unit["state"] != "claimed":
        sys.exit(f"repo-sweep: unit {a.unit} is not open ({unit['state'] if unit else 'no such unit'})")
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        sys.exit(f"repo-sweep: record got invalid JSON ({e}); correct it and run record again")
    key, check = {"find": ("findings", record_find), "validate": ("verdicts", record_validate),
                  "fix": ("results", record_fix)}[unit["kind"]]
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        sys.exit(f'repo-sweep: record for unit {a.unit} needs a JSON object with a "{key}" list, as the brief shows')
    problems = check(db, root, unit, [e if isinstance(e, dict) else {} for e in data[key]])
    for p in problems:
        print(f"rejected: {p}")
    if problems:
        out("record", f"unit {a.unit} still open: {len(problems)} rejected")
        return 1
    db.execute("UPDATE units SET state='done' WHERE id=?", (a.unit,))
    if unit["kind"] == "find" and open_in(db, part_files(db, unit["part"])):
        db.execute("INSERT INTO units(kind, part) VALUES ('validate', ?)", (unit["part"],))
    out("record", f"unit {a.unit} done")


def cmd_release(a, db, root, work):
    unit = db.execute("SELECT * FROM units WHERE id=?", (a.unit,)).fetchone()
    if not unit:
        sys.exit(f"repo-sweep: no unit {a.unit}")
    if unit["state"] != "claimed":
        return out("release", f"unit {a.unit} is {unit['state']}; nothing to do")
    state = "failed" if unit["attempts"] >= MAX_ATTEMPTS else "pending"
    db.execute("UPDATE units SET state=? WHERE id=?", (state, a.unit))
    out("release", f"unit {a.unit} {'failed after ' + str(MAX_ATTEMPTS) + ' attempts' if state == 'failed' else 'queued again'}")


def cmd_pr(a, db, root, work):
    unit = db.execute("SELECT * FROM units WHERE id=? AND kind='fix' AND state='done'", (a.unit,)).fetchone()
    if not unit:
        sys.exit(f"repo-sweep: unit {a.unit} is not a finished fix unit")
    marks = ",".join("?" * len(json.loads(unit["findings"])))  # skipped or reverted ones are needs-human by now
    ids = [f["id"] for f in db.execute(f"SELECT id FROM findings WHERE status='confirmed' AND id IN ({marks})",
                                       json.loads(unit["findings"])).fetchall()]
    for i in ids:
        set_status(db, i, "pr-open", pr=a.url)
    out("pr", f"{len(ids)} findings now pr-open at {a.url}")


def cmd_set(a, db, root, work):
    if not db.execute("SELECT 1 FROM findings WHERE id=?", (a.id,)).fetchone():
        sys.exit(f"repo-sweep: no finding #{a.id}")
    set_status(db, a.id, a.status, note=a.note)
    out("set", f"#{a.id} {a.status}")


# ---- status and report

def cmd_status(a, db, root, work):
    print(f"ledger: {work / 'sweep.db'}")
    for u in db.execute("SELECT * FROM units WHERE state IN ('claimed','failed') ORDER BY id"):
        print(f"unit {u['id']} {u['kind']} {u['state']} part={u['part']}")
    units = db.execute("SELECT kind, state, COUNT(*) n FROM units GROUP BY kind, state").fetchall()
    print("units: " + (", ".join(f"{u['n']} {u['kind']} {u['state']}" for u in units) or "none queued"))
    out("status", counts(db))


def cmd_report(a, db, root, work):
    home, sections = part_of(db), {}
    for f in db.execute("SELECT * FROM findings ORDER BY file, line"):
        text = describe(f) + f"\n- First seen {f['first_seen']}, updated {f['updated']}" + \
            (f"\n- PR: {f['pr']}" if f["pr"] else "") + "\n"
        sections.setdefault(home.get(f["file"], "(not in the current plan)"), []).append(text)
    summary = f"# repo-sweep report\n\n{counts(db)}\n"
    if not a.out:
        print(summary + "".join(f"\n## {part}\n\n" + "\n".join(texts) for part, texts in sections.items()))
        return out("report", counts(db))
    a.out.mkdir(parents=True, exist_ok=True)
    for part, texts in sections.items():
        name = (re.sub(r"[^A-Za-z0-9]+", "-", part).strip("-") or "root") + ".md"
        (a.out / name).write_text(f"# {part}\n\n" + "\n".join(texts), encoding="utf-8")
        summary += f"\n- [{part}](./{name}): {len(texts)} findings"
    (a.out / "index.md").write_text(summary + "\n", encoding="utf-8")
    out("report", f"{len(sections)} part files and index.md in {a.out}")


def main():
    ap = argparse.ArgumentParser(prog="repo-sweep", description="The ledger and the work queue behind the repo-sweep skills.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="sync, split the repository into parts, queue one find unit per part")
    p.add_argument("paths", nargs="*", help="limit the sweep to these paths")
    p.add_argument("--chars", type=int, default=120_000, help="most characters of code in one part")
    sub.add_parser("sync", help="start a run without a sweep: clear the queue, update findings from merged PRs and the current code")
    p = sub.add_parser("next", help="claim pending units and write their briefs")
    p.add_argument("-n", type=int, default=1, help="how many units to claim")
    p.add_argument("--fix", action="store_true", help="hand out fix units instead of find and validate units")
    p = sub.add_parser("record", help="a child's report for one unit, as JSON on stdin")
    p.add_argument("unit", type=int)
    p = sub.add_parser("release", help="call when a child returns: queues its unit again unless it is done")
    p.add_argument("unit", type=int)
    p = sub.add_parser("pr", help="record the pull request that carries a finished fix unit")
    p.add_argument("unit", type=int)
    p.add_argument("url")
    p = sub.add_parser("set", help="set one finding's status by hand")
    p.add_argument("id", type=int)
    p.add_argument("status", choices=STATUSES)
    p.add_argument("--note")
    sub.add_parser("status", help="the ledger path, open units and finding counts")
    p = sub.add_parser("report", help="every finding as Markdown")
    p.add_argument("--out", type=Path, help="write index.md and one file per part here instead of stdout")
    a = ap.parse_args()

    root, work = locate()
    work.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(work / "sweep.db", timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    db.execute("BEGIN IMMEDIATE")  # children record concurrently; one writer at a time keeps claims exact
    code = globals()[f"cmd_{a.cmd}"](a, db, root, work)
    db.execute("COMMIT")
    sys.exit(code or 0)


if __name__ == "__main__":
    main()
