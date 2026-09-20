#!/usr/bin/env bash
# lint.sh — enforce best-practices library conventions.
#
# Checks:
#   1. Rule ID format            ^[A-Z]{2,7}-[0-9]{3,}$
#   2. Rule ID uniqueness        no duplicate (PREFIX, number) within a skill
#   3. Orphaned entries          ## RULE-NNN headers must be in SKILL.md index
#   4. Missing entries           SKILL.md index entries must have ## RULE-NNN
#   5. Dead local links          [text](relative-path) must resolve
#   6. Frontmatter               name + description present; description is third-person
#
# Exits non-zero on any failure. Run from any cwd.
#
# Usage:
#   tools/lint.sh             # check everything
#   tools/lint.sh --skill X   # check only one skill (by directory name)

set -uo pipefail

TOOLS_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$(dirname "$TOOLS_DIR")"
SKILLS_ROOT="${PLUGIN_ROOT}/skills"

ONLY_SKILL=""
if [[ ${1:-} == "--skill" ]]; then
  ONLY_SKILL="${2:-}"
  if [[ -z "$ONLY_SKILL" ]]; then
    echo "usage: $0 [--skill <name>]" >&2
    exit 2
  fi
fi

# Color output if attached to a TTY.
if [[ -t 1 ]]; then
  RED=$'\033[31m'
  YEL=$'\033[33m'
  GRN=$'\033[32m'
  CYAN=$'\033[36m'
  RESET=$'\033[0m'
else
  RED=""; YEL=""; GRN=""; CYAN=""; RESET=""
fi

errors=0
warnings=0

err() { printf "%s[ERROR]%s %s\n" "$RED" "$RESET" "$*" >&2; errors=$((errors + 1)); }
warn() { printf "%s[WARN]%s %s\n" "$YEL" "$RESET" "$*" >&2; warnings=$((warnings + 1)); }
ok() { printf "%s[ OK ]%s %s\n" "$GRN" "$RESET" "$*"; }
info() { printf "%s[info]%s %s\n" "$CYAN" "$RESET" "$*"; }

# strip_fences <file> — emit file contents with fenced code blocks (```…```)
# elided. Necessary because example snippets inside SKILL.md / references
# can contain rule-shaped placeholders and dead "link" patterns that must
# not be linted as live content.
strip_fences() {
  awk '
    /^```/ { in_block = !in_block; next }
    !in_block { print }
  ' "$1"
}

# Enumerate skills.
shopt -s nullglob
skills=()
for d in "$SKILLS_ROOT"/*/; do
  name="$(basename "$d")"
  if [[ -n "$ONLY_SKILL" && "$name" != "$ONLY_SKILL" ]]; then
    continue
  fi
  skills+=("$d")
done

if [[ ${#skills[@]} -eq 0 ]]; then
  err "no skills found under $SKILLS_ROOT"
  exit 1
fi

# Track all rule IDs across the entire library for cross-skill collision
# detection (warning only — same prefix in two skills is suspicious but
# allowed if intentional).
declare -A all_rule_ids_seen=()

for skill_dir in "${skills[@]}"; do
  skill_name="$(basename "$skill_dir")"
  skill_file="${skill_dir}SKILL.md"
  info "checking ${skill_name}"

  if [[ ! -f "$skill_file" ]]; then
    err "${skill_name}: SKILL.md missing"
    continue
  fi

  # ---- 6. Frontmatter checks ----
  if ! head -n 1 "$skill_file" | grep -q '^---$'; then
    err "${skill_name}: SKILL.md must start with YAML frontmatter (---)"
  fi

  # Extract frontmatter block (between first two --- lines).
  frontmatter="$(awk '/^---$/{c++; next} c==1' "$skill_file")"

  if ! grep -q "^name: ${skill_name}$" <<< "$frontmatter"; then
    err "${skill_name}: frontmatter 'name:' must match directory name '${skill_name}'"
  fi

  description="$(awk -F': ' '/^description: /{ sub(/^description: /, ""); print; exit }' <<< "$frontmatter")"
  if [[ -z "$description" ]]; then
    err "${skill_name}: frontmatter missing 'description:' field"
  else
    # Heuristic: description should not start with "I", "You", or "This skill"
    # (third-person rule from CONVENTIONS.md).
    case "$description" in
      "I "*|"You "*|"This skill "*|"This plugin "*)
        warn "${skill_name}: description should be third-person; starts with first/second person"
        ;;
    esac
    # Length guard — too short usually means no trigger keywords.
    desc_len=${#description}
    if (( desc_len < 80 )); then
      warn "${skill_name}: description is short (${desc_len} chars); add trigger keywords for better activation"
    fi
  fi

  # ---- 1, 2, 3, 4. Rule ID checks ----
  # All scans go through strip_fences so example snippets inside ```…```
  # blocks (which legitimately contain rule-shaped placeholders) don't
  # get treated as real index entries or rule headers.

  # Collect rule IDs from SKILL.md rule index (bullet form: "- **PREFIX-NNN** — ...").
  index_ids="$(strip_fences "$skill_file" | grep -oE '\*\*[A-Z]{2,7}-[0-9]{3,}\*\*' | tr -d '*' | sort -u || true)"

  # Collect rule IDs from references/*.md (heading form: "## PREFIX-NNN — ...").
  ref_ids=""
  if [[ -d "${skill_dir}references" ]]; then
    for ref in "${skill_dir}references/"*.md; do
      [[ -f "$ref" ]] || continue
      strip_fences "$ref"
    done > /tmp/lint-refs.$$ 2>/dev/null || true
    ref_ids="$(grep -oE '^## [A-Z]{2,7}-[0-9]{3,}' /tmp/lint-refs.$$ 2>/dev/null | sed 's/^## //' | sort -u || true)"
  fi

  # Format check: anything claiming to be a rule but not matching the format.
  bad_format=""
  if [[ -f /tmp/lint-refs.$$ ]]; then
    bad_format="$(grep -oE '^## [A-Z][A-Z0-9-]*' /tmp/lint-refs.$$ \
      | sed 's/^## //' \
      | grep -vE '^[A-Z]{2,7}-[0-9]{3,}$' \
      | grep -E '^[A-Z]+-' \
      || true)"
  fi
  if [[ -n "$bad_format" ]]; then
    while IFS= read -r bad; do
      err "${skill_name}: rule header '${bad}' does not match format ^[A-Z]{2,7}-[0-9]{3,}$"
    done <<< "$bad_format"
  fi

  # Duplicate check: same rule ID appears twice in references.
  dup=""
  if [[ -f /tmp/lint-refs.$$ ]]; then
    dup="$(grep -oE '^## [A-Z]{2,7}-[0-9]{3,}' /tmp/lint-refs.$$ \
      | sed 's/^## //' \
      | sort | uniq -d || true)"
  fi
  if [[ -n "$dup" ]]; then
    while IFS= read -r d_id; do
      err "${skill_name}: duplicate rule entry: ${d_id}"
    done <<< "$dup"
  fi

  # Strip-fenced SKILL.md content for orphan / missing checks.
  skill_stripped="$(strip_fences "$skill_file")"

  # Orphaned entry: ## header in references that's not in SKILL.md index.
  if [[ -n "$ref_ids" ]]; then
    while IFS= read -r rid; do
      if [[ -n "$rid" ]] && ! grep -qF "**${rid}**" <<< "$skill_stripped"; then
        err "${skill_name}: rule entry ${rid} exists in references but not in SKILL.md index"
      fi
    done <<< "$ref_ids"
  fi

  # Missing entry: index entry without a corresponding reference header.
  if [[ -n "$index_ids" ]] && [[ -f /tmp/lint-refs.$$ ]]; then
    while IFS= read -r iid; do
      if [[ -n "$iid" ]] && ! grep -qE "^## ${iid}( |$)" /tmp/lint-refs.$$; then
        err "${skill_name}: SKILL.md lists ${iid} but no ## ${iid} header in references/"
      fi
    done <<< "$index_ids"
  fi

  # Track for cross-skill collision warning.
  if [[ -n "$ref_ids" ]]; then
    while IFS= read -r rid; do
      [[ -z "$rid" ]] && continue
      if [[ -n "${all_rule_ids_seen[$rid]:-}" ]]; then
        warn "rule ID ${rid} appears in both ${all_rule_ids_seen[$rid]} and ${skill_name} (cross-skill collision)"
      else
        all_rule_ids_seen[$rid]="$skill_name"
      fi
    done <<< "$ref_ids"
  fi

  rm -f /tmp/lint-refs.$$

  # ---- 5. Dead link check ----
  # Find markdown links [text](path) where path is relative (no scheme).
  # Strip fences first so example links inside code blocks (e.g. illustrative
  # paths in the meta skill) don't get linted.
  for f in "$skill_file" "${skill_dir}references/"*.md; do
    [[ -f "$f" ]] || continue
    fdir="$(dirname "$f")"
    links="$(strip_fences "$f" | grep -oE '\]\([^)]+\)' | sed 's/^](//;s/)$//' || true)"
    while IFS= read -r link; do
      [[ -z "$link" ]] && continue
      case "$link" in
        http://*|https://*|mailto:*|//*) continue ;;
      esac
      path="${link%%#*}"
      [[ -z "$path" ]] && continue
      if [[ "$path" = /* ]]; then
        resolved="$path"
      else
        resolved="${fdir}/${path}"
      fi
      if [[ ! -e "$resolved" ]]; then
        err "${skill_name}: dead link in $(realpath --relative-to="$PLUGIN_ROOT" "$f"): ${link}"
      fi
    done <<< "$links"
  done
done

echo
if (( errors > 0 )); then
  printf "%sFAILED:%s %d error(s), %d warning(s)\n" "$RED" "$RESET" "$errors" "$warnings"
  exit 1
fi
if (( warnings > 0 )); then
  printf "%sPASSED with warnings:%s %d warning(s)\n" "$YEL" "$RESET" "$warnings"
  exit 0
fi
printf "%sPASSED:%s no issues\n" "$GRN" "$RESET"
exit 0
