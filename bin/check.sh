#!/usr/bin/env bash
# Everything this repo can verify about itself, in one command. CI runs exactly this.
#
#   bin/check.sh            # full gate
#   bin/check.sh --no-node  # skip the Node test suites (no pnpm on this box)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

fail=0
node_tests=1
[ "${1:-}" = "--no-node" ] && node_tests=0
step() { printf '\n== %s\n' "$1"; }
py() { uv run --with pyyaml --python 3.12 python "$@"; }

step "modules/index.yaml is current"
uv run --script bin/render-index.py --check || fail=1

step "every skill satisfies the portable contract"
uv run --script bin/lint-skills.py || fail=1

step "the contract rejects a deliberately non-portable skill"
# The lint is only worth trusting if it is known to bite. A fixture that breaks
# five rules at once must fail; if it passes, the gate is decorative.
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bad/skills/renamed" "$tmp/bad/skills/flat"
cat > "$tmp/bad/skills/renamed/SKILL.md" <<'EOF'
---
name: other-name
description: A skill that breaks the contract on purpose.
context: fork
allowed-tools: Bash
---
Run `${CLAUDE_PLUGIN_ROOT}/x.py` and read ~/.agents/lib/thing then ./missing.md
EOF
echo '# no frontmatter' > "$tmp/bad/skills/flat.md"
if uv run --script bin/lint-skills.py "$tmp/bad" >"$tmp/lint.out" 2>&1; then
    echo "  FAIL: lint accepted a non-portable fixture"; cat "$tmp/lint.out"; fail=1
else
    n=$(grep -c FAIL "$tmp/lint.out" || true)
    if [ "$n" -ge 5 ]; then echo "  ok ($n findings on the fixture)"; else echo "  FAIL: only $n findings"; cat "$tmp/lint.out"; fail=1; fi
fi

step "module versions agree (package.json, plugin.json, marketplace entry)"
py - <<'PY' || fail=1
import json, pathlib, sys
bad = 0
mp = json.load(open(".claude-plugin/marketplace.json"))
entries = {p["name"]: p for p in mp["plugins"]}
seen = set()
for mod in sorted(p for p in pathlib.Path("modules").iterdir() if p.is_dir()):
    pkg_path = mod / "package.json"
    if not pkg_path.exists():
        print(f"  FAIL {mod}: no package.json (every module needs one; it carries the version)"); bad += 1; continue
    pkg = json.load(open(pkg_path))
    ver = pkg.get("version")
    if pkg.get("name") != f"@allada-homelab/{mod.name}":
        print(f"  FAIL {mod}: package name {pkg.get('name')!r} != @allada-homelab/{mod.name}"); bad += 1
    if not ver:
        print(f"  FAIL {mod}: package.json has no version"); bad += 1
    plugin = mod / ".claude-plugin" / "plugin.json"
    entry = entries.get(mod.name)
    if plugin.exists():
        seen.add(mod.name)
        pj = json.load(open(plugin))
        if pj.get("name") != mod.name:
            print(f"  FAIL {mod}: plugin.json name {pj.get('name')!r} != {mod.name}"); bad += 1
        if pj.get("version") != ver:
            print(f"  FAIL {mod}: plugin.json version {pj.get('version')} != package.json {ver}"); bad += 1
        if entry is None:
            print(f"  FAIL {mod}: has plugin.json but no marketplace.json entry"); bad += 1
        else:
            if entry.get("version") != ver:
                print(f"  FAIL {mod}: marketplace version {entry.get('version')} != package.json {ver}"); bad += 1
            if entry.get("source") != f"./modules/{mod.name}":
                print(f"  FAIL {mod}: marketplace source {entry.get('source')!r}"); bad += 1
    elif entry is not None:
        print(f"  FAIL {mod}: marketplace entry exists but module has no .claude-plugin/plugin.json"); bad += 1
    if (mod / "cordis.patch.yml").exists() != ((mod / "skills").is_dir() or "dsh" in pkg):
        print(f"  FAIL {mod}: cordis.patch.yml presence does not match (skills or dsh plugin ⇒ needs one)"); bad += 1
for name in entries.keys() - seen:
    print(f"  FAIL marketplace entry {name!r} has no module directory"); bad += 1
print(f"  ok ({len(entries)} Claude plugins)" if not bad else f"  {bad} problem(s)")
sys.exit(1 if bad else 0)
PY

step "root pi manifest agrees with the skill scopes"
py - <<'PY' || fail=1
# pi installs the whole repo, so the root manifest decides what every pi user
# gets. A module whose skills are all scoped away from pi must be excluded there,
# and every extension module must be globbed in.
import json, pathlib, sys, yaml
pkg = json.load(open("package.json"))["pi"]
skills, exts = pkg.get("skills", []), pkg.get("extensions", [])
bad = 0
def fm(p):
    t = p.read_text(); e = t.find("\n---", 4)
    d = yaml.safe_load(t[4:e]) if t.startswith("---\n") and e != -1 else None
    return d if isinstance(d, dict) else {}
for mod in sorted(p for p in pathlib.Path("modules").iterdir() if p.is_dir()):
    sk = list(mod.glob("skills/*/SKILL.md"))
    if sk:
        scopes = [set([h] if isinstance(h, str) else h) if (h := fm(s).get("harness")) else {"claude","pi","dsh"} for s in sk]
        excluded = f"!modules/{mod.name}/**" in skills
        if all("pi" not in sc for sc in scopes) and not excluded:
            print(f"  FAIL {mod}: no skill applies to pi, but the root pi manifest does not exclude it"); bad += 1
        if any("pi" in sc for sc in scopes) and excluded:
            print(f"  FAIL {mod}: has pi-applicable skills but the root pi manifest excludes it"); bad += 1
    if list(mod.glob("extensions/*.ts")) and "modules/*/extensions/*.ts" not in exts:
        print(f"  FAIL {mod}: ships extensions but the root manifest does not glob modules/*/extensions/*.ts"); bad += 1
print("  ok" if not bad else f"  {bad} problem(s)")
sys.exit(1 if bad else 0)
PY

step "hook manifests parse and the contract corpus is consistent"
py - <<'PY' || fail=1
import json, pathlib, sys
bad = 0
for hj in sorted(pathlib.Path("modules").glob("*/hooks/hooks.json")):
    try:
        h = json.load(open(hj))["hooks"]
    except Exception as e:
        print(f"  FAIL {hj}: {e}"); bad += 1; continue
    for event, groups in h.items():
        for g in groups:
            for handler in g.get("hooks", []):
                if handler.get("type") != "command":
                    print(f"  WARN {hj}: {event} handler type {handler.get('type')!r} is Claude-only; pi/dsh runners skip it")
c = json.load(open("hook-contract/corpus.json"))
names = set()
for case in c["cases"]:
    if case["name"] in names: print(f"  FAIL corpus: duplicate case {case['name']}"); bad += 1
    names.add(case["name"])
    for groups in case["hooks"].values():
        for g in groups:
            for handler in g.get("hooks", []):
                cmd = handler.get("command", "")
                if "fixtures/" in cmd:
                    fx = cmd.split("fixtures/")[1].split('"')[0]
                    if not pathlib.Path("hook-contract/fixtures", fx).exists() and "does-not-exist" not in fx:
                        print(f"  FAIL corpus {case['name']}: fixture {fx} missing"); bad += 1
    for hz in case["harness"]:
        if hz not in case["native"]: print(f"  FAIL corpus {case['name']}: no native event for {hz}"); bad += 1
print(f"  ok ({len(names)} corpus cases)" if not bad else f"  {bad} problem(s)")
sys.exit(1 if bad else 0)
PY

step "nothing in a module points at a path only this machine has"
# /home/<user>/ is a private path; /home/vscode/ is the dev-container fixture path.
if grep -rnIE 'davidallada-developer-setup|~/\.agents/lib|/home/[a-z]+/' modules docs README.md --exclude-dir=node_modules --exclude-dir=__pycache__ --exclude=index.yaml | grep -v '/home/vscode/'; then
    echo "  FAIL: private or absolute path in publishable content"; fail=1
else
    echo "  ok"
fi

step "python tests"
if compgen -G "modules/*/test/test_*.py" >/dev/null; then
    uv run --with pytest --with pyyaml --python 3.12 pytest -q modules/*/test || fail=1
else
    echo "  (none)"
fi

step "node tests (every module with a test script)"
if [ "$node_tests" = 1 ]; then
    if command -v pnpm >/dev/null; then
        pnpm install --frozen-lockfile --silent >/dev/null || pnpm install --silent >/dev/null || { echo "  FAIL: pnpm install"; fail=1; }
        pnpm -r --if-present test || fail=1
    else
        echo "  FAIL: pnpm not found (pass --no-node to skip locally; CI never skips)"; fail=1
    fi
else
    echo "  skipped (--no-node)"
fi

printf '\n%s\n' "$([ "$fail" -eq 0 ] && echo 'ALL CHECKS PASSED' || echo 'CHECKS FAILED')"
exit "$fail"
