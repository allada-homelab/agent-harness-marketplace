#!/usr/bin/env bash
# Real dsh, throwaway $DSH_HOME: install a content module into a scratch
# profile. The skills bridge and hook runner it used to need are pi/dsh
# harness-side foundation now (the maintainer's harness layer), not installed
# from here, so this proves (a) the empty cordis.patch.yml convention inserts
# no spurious loader row and (b) every installed plugin that DOES ship code
# still APPLIES under a strict cordis-shaped ctx — the check that would have
# caught the shipped "no inject, registers nothing" bugs, kept generic for any
# future module.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
DSH_HOME=$(mktemp -d); export DSH_HOME; trap 'rm -rf "$DSH_HOME"' EXIT
profile=smoke
echo "== dsh plugin add"
dsh plugin --profile "$profile" add "file:$repo/modules/research" 2>&1 | grep -viE 'progress|^$' | tail -2 || true
echo "== dump-config"
cfg=$(dsh --profile "$profile" --dump-config 2>&1)
fail=0
check() { if eval "$2"; then echo "  ok   $1"; else echo "  FAIL $1"; fail=1; fi; }
check "an empty cordis.patch.yml inserts no loader row for research" '[[ "$cfg" != *"module-skills-research"* ]]'
pdir="$DSH_HOME/profiles/$profile"
check "research is installed as a bundle dependency" '[ -e "$pdir/node_modules/@allada-homelab/research/package.json" ]'
echo "== apply every installed plugin that ships code under a strict ctx"
node "$repo/tests/smoke/dsh-apply.mjs" "$pdir" || fail=1
[ "$fail" = 0 ] || { echo "--- dump-config"; echo "$cfg" | tail -40; exit 1; }
