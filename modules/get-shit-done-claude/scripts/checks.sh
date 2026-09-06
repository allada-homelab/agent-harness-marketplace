#!/usr/bin/env bash
# Static conformance checks for the get-shit-done plugin.
# Behavioral fan-out (the spine actually spawning subagents) can't be exercised offline — it needs a
# live Workflow engine — so this gate covers what IS deterministic: manifests parse, the spine is valid
# JS, the detector compiles and behaves, and no live hooks.json ships (the auto-trigger is disabled).
# Run: bash plugins/get-shit-done/scripts/checks.sh   → expects "PASS" and exit 0.
set -u
here="$(cd "$(dirname "$0")/.." && pwd)"   # plugin root
root="$(cd "$here/../.." && pwd)"          # repo root
fail=0
incomplete=0   # a non-failing skip ran (e.g. node missing) — PASS is not a full green
ok()   { echo "ok:   $1"; }
bad()  { echo "FAIL: $1"; fail=1; }

# 1. JSON manifests parse.
for f in "$here/.claude-plugin/plugin.json" "$here/hooks/auto-trigger.example.json" "$root/.claude-plugin/marketplace.json"; do
  if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$f" 2>/dev/null; then ok "json parses: ${f#$root/}"; else bad "json invalid: ${f#$root/}"; fi
done

# 2. Spine is valid JS (needs node; skip-with-note if absent rather than false-fail).
if command -v node >/dev/null 2>&1; then
  if node --check "$here/workflows/gsd.workflow.js" 2>/dev/null; then ok "spine parses (node --check)"; else bad "spine has a JS syntax error"; fi
else
  echo "skip: node not installed — cannot syntax-check gsd.workflow.js"
  incomplete=1
fi

# 3. Detector compiles and behaves (nudges on fan-out intent, silent on chat).
if python3 -m py_compile "$here/scripts/gsd_autotrigger.py" 2>/dev/null; then ok "detector compiles"; else bad "detector has a syntax error"; fi
nudge=$(echo '{"prompt":"implement a payments feature end-to-end across the billing service"}' | python3 "$here/scripts/gsd_autotrigger.py")
[ -n "$nudge" ] && ok "detector nudges on fan-out prompt" || bad "detector should have nudged"
silent=$(echo '{"prompt":"thanks, what time is it?"}' | python3 "$here/scripts/gsd_autotrigger.py")
[ -z "$silent" ] && ok "detector silent on casual prompt" || bad "detector should have stayed silent"

# 4. Auto-trigger ships DISABLED: no live hooks.json in the plugin.
if [ -e "$here/hooks/hooks.json" ]; then bad "hooks/hooks.json exists — auto-trigger should ship disabled"; else ok "no live hooks.json (auto-trigger disabled by default)"; fi

# 5. Plugin is registered in the marketplace.
if python3 -c "import json,sys; m=json.load(open(sys.argv[1])); sys.exit(0 if any(p.get('name')=='get-shit-done' for p in m.get('plugins',[])) else 1)" "$root/.claude-plugin/marketplace.json"; then ok "registered in marketplace.json"; else bad "not registered in marketplace.json"; fi

# 6. Spine pure-logic unit tests (extracted from the fenced region; needs node).
if command -v node >/dev/null 2>&1; then
  if node "$here/scripts/spine_logic_test.mjs"; then ok "spine pure-logic tests pass"; else bad "spine pure-logic tests failed"; fi
else
  echo "skip: node not installed — cannot run spine_logic_test.mjs"
  incomplete=1
fi

echo
if [ "$fail" -ne 0 ]; then
  echo "FAILED"
elif [ "$incomplete" -ne 0 ]; then
  echo "PASS (incomplete: node missing — spine not syntax-checked, logic tests not run)"
else
  echo "PASS"
fi
exit "$fail"
