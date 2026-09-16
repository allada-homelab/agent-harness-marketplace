#!/usr/bin/env bash
# Advisory only: compare this checkout against the fleet's declaration of which
# marketplace modules it consumes (the maintainer's dotfiles repo,
# agents/modules.tsv). It never fails the gate — CI has no copy of that file —
# it tells the person working here what the paired dotfiles change will be.
# The six pairing cases are listed in CLAUDE.md → "Pairing with the fleet".
#
#   FLEET_MODULES_TSV=/path/to/modules.tsv bin/fleet-pairing.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

tsv="${FLEET_MODULES_TSV:-$HOME/.davidallada-developer-setup/agents/modules.tsv}"
if [ ! -f "$tsv" ]; then
    echo "  skipped (no fleet declaration at $tsv; set FLEET_MODULES_TSV)"
    exit 0
fi
settings="$(dirname "$tsv")/../claude/settings.json"
repo_re='allada-homelab/agent-harness-marketplace'
warn=0
w() { echo "  WARN $*"; warn=1; }

# rows for this repo: ref<TAB>module
rows=$(grep -v '^[[:space:]]*#' "$tsv" | grep -E "^[^	]*$repo_re" | awk -F'\t' '{print $2"\t"$3}' || true)
declare -A fleet_ref
while IFS=$'\t' read -r ref mod; do
    [ -n "${mod:-}" ] || continue
    fleet_ref["$mod"]="$ref"
done <<< "$rows"

latest=$(git tag --list 'v*' --sort=-v:refname | head -1)
for mod in $(ls -d modules/*/ | xargs -n1 basename); do
    if [ -z "${fleet_ref[$mod]:-}" ]; then
        w "modules/$mod has no row in the fleet declaration — the fleet will not install it (case 1)"
    elif [ -n "$latest" ] && [ "${fleet_ref[$mod]}" != "$latest" ]; then
        w "modules/$mod is consumed at ${fleet_ref[$mod]}; latest tag here is $latest (case 2)"
    fi
    if [ -f "$settings" ] && grep -qE "\"$mod@claude-plugins-official\": *true" "$settings"; then
        w "$mod@claude-plugins-official is still enabled in the fleet's claude/settings.json (case 3)"
    fi
done
for mod in "${!fleet_ref[@]}"; do
    [ -d "modules/$mod" ] && continue
    w "fleet row for $mod points at a module this checkout no longer has — delete the row (case 4)"
done

[ "$warn" = 0 ] && echo "  ok (fleet declaration matches this checkout)"
echo "  (advisory: pair the change in the dotfiles repo — see CLAUDE.md → Pairing with the fleet)"
exit 0
