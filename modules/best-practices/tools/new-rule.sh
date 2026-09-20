#!/usr/bin/env bash
# new-rule.sh — append a rule stub to an existing skill.
#
# Usage:
#   tools/new-rule.sh <domain> <RULE-ID> "rule title"
#
# Examples:
#   tools/new-rule.sh python PY-001 "src/ layout vs flat layout"
#   tools/new-rule.sh containers DOCKER-027 "Use --no-install-recommends"
#
# Appends a four-part stub (What / Why / How / When-NOT-to-apply) to
# references/<topic>.md and adds the one-liner to the rule index in
# SKILL.md. If the reference file doesn't exist yet, it's created with
# a heading derived from the rule ID prefix.

set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "usage: $0 <domain> <RULE-ID> \"title\"" >&2
  echo "example: $0 python PY-001 \"src/ layout vs flat layout\"" >&2
  exit 2
fi

DOMAIN="$1"
RULE_ID="$2"
TITLE="$3"

if [[ ! "$RULE_ID" =~ ^[A-Z]{2,7}-[0-9]{3,}$ ]]; then
  echo "error: rule ID must match ^[A-Z]{2,7}-[0-9]{3,}$ (got: $RULE_ID)" >&2
  exit 2
fi

TOOLS_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$(dirname "$TOOLS_DIR")"
SKILL_DIR="${PLUGIN_ROOT}/skills/${DOMAIN}-best-practices"
TEMPLATE="${TOOLS_DIR}/templates/rule-entry.md.tmpl"

if [[ ! -d "$SKILL_DIR" ]]; then
  echo "error: skill does not exist: $SKILL_DIR" >&2
  echo "       run 'tools/new-skill.sh $DOMAIN' first" >&2
  exit 1
fi

if [[ ! -f "$TEMPLATE" ]]; then
  echo "error: template missing: $TEMPLATE" >&2
  exit 1
fi

# Derive a topic file name from the rule prefix (lowercased). The author
# can rename / split topics later; this is just a starting point.
PREFIX="${RULE_ID%%-*}"
TOPIC="$(echo "$PREFIX" | tr '[:upper:]' '[:lower:]')"
REF_FILE="${SKILL_DIR}/references/${TOPIC}.md"

# Check for collision: rule ID must not already exist anywhere in this skill.
if grep -RqE "^## ${RULE_ID} " "${SKILL_DIR}/references" 2>/dev/null; then
  echo "error: rule $RULE_ID already exists somewhere in ${SKILL_DIR}/references/" >&2
  exit 1
fi

# Render the entry.
ENTRY="$(sed \
  -e "s|__RULE_ID__|${RULE_ID}|g" \
  -e "s|__TITLE__|${TITLE}|g" \
  "$TEMPLATE")"

# Create the reference file with a heading if it doesn't exist yet.
if [[ ! -f "$REF_FILE" ]]; then
  cat > "$REF_FILE" <<EOF
# ${PREFIX} rules

Detailed entries for each \`${PREFIX}-NNN\` rule. Each entry follows
the same four-part shape: **What / Why / How / When NOT to apply**.

---

EOF
  echo "created: $REF_FILE"
fi

# Append the entry.
{
  echo
  echo "$ENTRY"
  echo
  echo "---"
} >> "$REF_FILE"

# Add a one-liner to the SKILL.md rule index.
# Look for a "## Rules — " section that references the topic file; if
# present, append after the last bullet in that section. Otherwise,
# append a new section at end of SKILL.md.
SKILL_FILE="${SKILL_DIR}/SKILL.md"
BULLET="- **${RULE_ID}** — ${TITLE}"

if grep -qF "references/${TOPIC}.md" "$SKILL_FILE"; then
  # Section exists — append the bullet after the last existing bullet for
  # this section. Simplest reliable approach: append at the end of the
  # file under a marker comment, then sort/move later if needed.
  # For now, just print a notice asking the author to slot it in.
  echo "$BULLET" >> "$SKILL_FILE"
  echo "note: appended bullet to end of SKILL.md — move it under the right ## Rules section by hand:"
  echo "      $BULLET"
else
  # No section for this topic yet — create one.
  {
    echo
    echo "## Rules — ${PREFIX}"
    echo
    echo "See [\`references/${TOPIC}.md\`](./references/${TOPIC}.md)."
    echo
    echo "$BULLET"
  } >> "$SKILL_FILE"
  echo "added new section to SKILL.md for ${PREFIX}"
fi

echo
echo "stub appended to: $REF_FILE"
echo "  Edit the four sections (What / Why / How / When NOT to apply)."
echo
echo "next: tools/render-index.sh && tools/lint.sh"
