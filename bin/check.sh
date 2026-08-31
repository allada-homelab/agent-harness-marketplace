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

step "policy regexes compile under BOTH engines"
uv run --python 3.12 python - <<'PY' || fail=1
import json, re
d = json.load(open("policy/secrets.json"))
for p in d["deny_read_paths"]: re.compile(p["pattern"], re.I)
for p in d["redaction"]["shape_patterns"]: re.compile(p["pattern"])
re.compile(d["redaction"]["named_assignment"]["pattern"], re.I)
re.compile(d["redaction"]["benign_value"]["pattern"], re.I)
print("  python: ok")
PY
node -e '
const d = require("./policy/secrets.json");
for (const p of d.deny_read_paths) new RegExp(p.pattern, "i");
for (const p of d.redaction.shape_patterns) new RegExp(p.pattern, "g");
new RegExp(d.redaction.named_assignment.pattern, "gi");
new RegExp(d.redaction.benign_value.pattern, "i");
console.log("  node: ok");' || fail=1

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
