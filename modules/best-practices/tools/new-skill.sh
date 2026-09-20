#!/usr/bin/env bash
# new-skill.sh — scaffold a new domain skill.
#
# Usage:
#   tools/new-skill.sh <domain>
#
# Examples:
#   tools/new-skill.sh python      # creates skills/python-best-practices/
#   tools/new-skill.sh frontend    # creates skills/frontend-best-practices/
#
# Creates the skill directory with SKILL.md (from template) and an empty
# references/ subdirectory. The SKILL.md frontmatter and body contain
# placeholders that you must edit before committing.

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <domain>" >&2
  echo "example: $0 python" >&2
  exit 2
fi

DOMAIN="$1"

if [[ ! "$DOMAIN" =~ ^[a-z][a-z0-9-]*$ ]]; then
  echo "error: domain must be lowercase kebab-case (got: $DOMAIN)" >&2
  exit 2
fi

# Resolve plugin root relative to this script.
TOOLS_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$(dirname "$TOOLS_DIR")"
SKILL_NAME="${DOMAIN}-best-practices"
SKILL_DIR="${PLUGIN_ROOT}/skills/${SKILL_NAME}"
TEMPLATE="${TOOLS_DIR}/templates/SKILL.md.tmpl"

if [[ -d "$SKILL_DIR" ]]; then
  echo "error: skill already exists: $SKILL_DIR" >&2
  exit 1
fi

if [[ ! -f "$TEMPLATE" ]]; then
  echo "error: template missing: $TEMPLATE" >&2
  exit 1
fi

mkdir -p "${SKILL_DIR}/references"

# Title-case the domain for the heading (first letter uppercased; hyphens
# become spaces with each word capitalized).
DOMAIN_TITLE="$(echo "$DOMAIN" | awk -F'-' '{ for (i=1; i<=NF; i++) printf "%s%s%s", toupper(substr($i,1,1)), substr($i,2), (i<NF ? " " : "") }')"

# Default placeholder prefix and topic — author edits these.
PREFIX="$(echo "$DOMAIN" | tr '[:lower:]' '[:upper:]' | tr -d '-' | cut -c1-4)"

# Render the template.
sed \
  -e "s|__SKILL_NAME__|${SKILL_NAME}|g" \
  -e "s|__DOMAIN_TITLE__|${DOMAIN_TITLE}|g" \
  -e "s|__TRIGGERS__|${DOMAIN}|g" \
  -e "s|__PREFIX__|${PREFIX}|g" \
  -e "s|__TOPIC 1__|__TOPIC1__|g" \
  -e "s|__TOPIC1__|topic1|g" \
  "$TEMPLATE" > "${SKILL_DIR}/SKILL.md"

echo "created: ${SKILL_DIR}/SKILL.md"
echo "created: ${SKILL_DIR}/references/"
echo
echo "next steps:"
echo "  1. edit ${SKILL_DIR}/SKILL.md — replace __FILL IN__ markers"
echo "  2. tools/new-rule.sh ${DOMAIN} ${PREFIX}-001 'first rule title'"
echo "  3. tools/render-index.sh    # regenerate INDEX.md"
echo "  4. tools/lint.sh            # verify before committing"
