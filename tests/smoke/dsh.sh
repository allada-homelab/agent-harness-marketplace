#!/usr/bin/env bash
# Real dsh, throwaway $DSH_HOME: install the bridge, the hook runner and a
# content module into a scratch profile, then prove (a) dsh composes a row for
# each (dump-config) and (b) every installed plugin actually APPLIES under a
# strict cordis-shaped ctx — the check that would have caught the shipped
# "no inject, registers nothing" bugs. Also proves the bridge serves the content
# module's skill from the installed copy.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
DSH_HOME=$(mktemp -d); export DSH_HOME; trap 'rm -rf "$DSH_HOME"' EXIT
profile=smoke
echo "== dsh plugin add"
for m in dsh-module-skills hook-runner-dsh research; do
  dsh plugin --profile "$profile" add "file:$repo/modules/$m" 2>&1 | grep -viE 'progress|^$' | tail -2 || true
done
echo "== dump-config"
cfg=$(dsh --profile "$profile" --dump-config 2>&1)
fail=0
check() { if eval "$2"; then echo "  ok   $1"; else echo "  FAIL $1"; fail=1; fi; }
check "dsh-module-skills row composes" '[[ "$cfg" == *"@allada-homelab/dsh-module-skills"* ]]'
check "hook-runner-dsh row composes" '[[ "$cfg" == *"@allada-homelab/hook-runner-dsh"* ]]'
check "research row scopes the bridge to its own package" '[[ "$cfg" == *"providerName: module-skills-research"* ]]'
pdir="$DSH_HOME/profiles/$profile"
echo "== apply every installed plugin under a strict ctx"
node "$repo/tests/smoke/dsh-apply.mjs" "$pdir" || fail=1
[ "$fail" = 0 ] || { echo "--- dump-config"; echo "$cfg" | tail -40; exit 1; }
