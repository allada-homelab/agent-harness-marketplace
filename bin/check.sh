#!/usr/bin/env bash
# Everything this repo can verify about itself, in one command.
#
# It exists because the tree's own tests were orphaned when they moved here: the
# setup repo's runner only collects tests/test_*.sh, so nothing was running these.
#
# Run from the repo root: bin/check.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

fail=0
step() { printf '\n== %s\n' "$1"; }

step "index.yaml is current"
uv run --script bin/agents-index.py --check || fail=1

step "every skill satisfies the strictest parser (dsh: name AND description required)"
uv run --with pyyaml --python 3.12 python - <<'PY' || fail=1
import pathlib, re, sys, yaml
bad = 0
for f in sorted(pathlib.Path("skills").glob("*/SKILL.md")):
    fm = yaml.safe_load(f.read_text().split("---")[1]) or {}
    name, desc = fm.get("name"), fm.get("description", "")
    for problem in (
        None if name else "missing name (dsh has no dirname fallback)",
        None if name and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) else f"invalid name {name!r}",
        None if name == f.parent.name else f"name {name!r} != directory {f.parent.name!r}",
        None if desc else "missing description (every harness drops it)",
        None if len(desc) <= 1024 else f"description {len(desc)} > 1024 (pi warns)",
    ):
        if problem:
            print(f"  FAIL {f}: {problem}"); bad += 1
print("  ok" if not bad else f"  {bad} problem(s)")
sys.exit(1 if bad else 0)
PY

step "every policy regex compiles under BOTH engines"
# Both, every time: a pattern only one engine accepts would silently disable
# the guard on the harnesses using the other.
uv run --python 3.12 python - <<'PYCHK' || fail=1
import json, re
s = json.load(open("policy/secrets.json"))
for d in s["deny_read_paths"]: re.compile(d["pattern"], re.I)
for r in s["redaction"]["rules"]:
    re.compile(r["pattern"])
    assert r["keywords"], f"{r['id']}: no keyword prefilter — it would run on every scan"
re.compile(s["redaction"]["named_assignment"]["pattern"], re.I)
re.compile(s["redaction"]["benign_value"]["pattern"], re.I)
b = json.load(open("policy/bash.json"))
for r in b["deny_bash"]: re.compile(r["pattern"])
print(f"  python: ok ({len(s['redaction']['rules'])} secret rules, {len(b['deny_bash'])} bash rules)")
PYCHK
node -e '
const s = require("./policy/secrets.json");
for (const d of s.deny_read_paths) new RegExp(d.pattern, "i");
for (const r of s.redaction.rules) new RegExp(r.pattern, "g");
new RegExp(s.redaction.named_assignment.pattern, "gi");
new RegExp(s.redaction.benign_value.pattern, "i");
const b = require("./policy/bash.json");
b.deny_bash.forEach((r) => new RegExp(r.pattern));
console.log(`  node: ok (${s.redaction.rules.length} secret rules, ${b.deny_bash.length} bash rules)`);' || fail=1

step "the conformance corpus is internally consistent"
uv run --python 3.12 python - <<'PYCOR' || fail=1
import json
c = json.load(open("policy/testcases.json"))
ids = {r["id"] for r in json.load(open("policy/secrets.json"))["redaction"]["rules"]}
bad = 0
for case in c["redact"]:
    if case["rule"] not in ids:
        print(f"  FAIL redact case names unknown rule {case['rule']!r}"); bad += 1
redact_inputs = {case["input"] for case in c["redact"]}
for case in c["allow"]:
    if case["input"] in redact_inputs:
        print(f"  FAIL {case['input'][:40]!r} is in BOTH redact and allow"); bad += 1
    if not case.get("why"):
        print(f"  FAIL allow case has no stated reason: {case['input'][:40]!r}"); bad += 1
print(f"  ok ({len(c['redact'])} redact, {len(c['allow'])} allow)" if not bad else f"  {bad} problem(s)")
raise SystemExit(1 if bad else 0)
PYCOR

step "skill unit tests"
uv run --with pytest --python 3.12 pytest -q tests/ || fail=1

step "no global skill points at a path only the setup repo has"
if grep -rnoE '`(pi|claude|evals|scripts|vscode)/[A-Za-z0-9/_.-]+`' skills/ commands/; then
    echo "  FAIL: repo-relative reference in a globally-scoped artifact (prefix it with ~/.davidallada-developer-setup/)"
    fail=1
else
    echo "  ok"
fi

printf '\n%s\n' "$([ "$fail" -eq 0 ] && echo 'ALL CHECKS PASSED' || echo 'CHECKS FAILED')"
exit "$fail"
