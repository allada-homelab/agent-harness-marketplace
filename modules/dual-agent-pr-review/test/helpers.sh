#!/usr/bin/env bash
# The dual_review.sh helpers that decide what a run reports, against fixtures
# shaped like real codex logs and git histories:
#   write_prior          — a re-review with no delta must not abort prepare
#                          (an assignment ending in a failed `$( … )` exits
#                          under set -e, and prepare's trap then deletes the run)
#   codex_worktree_execs — parallel exec batches log every header first, then
#                          the results with no header
#   codex_failure_cause  — a timeout is a timeout even when the log quotes "401"
#   cmd_anchors          — GitHub rejects a whole review for one bad anchor
# The functions are EXTRACTED from the real script and run under set -euo
# pipefail, as they do there.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
SCRIPT="$PWD/skills/dual-agent-pr-review/scripts/dual_review.sh"
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

PASS=0; FAIL=0
pass() { PASS=$((PASS + 1)); printf "  PASS: %s\n" "$1"; }
fail() { FAIL=$((FAIL + 1)); printf "  FAIL: %s\n" "$1"; [[ -z "${2:-}" ]] || printf "       %s\n" "$2"; }
check() { local name="$1" want="$2" got="$3"; [[ "$got" == *"$want"* ]] && pass "$name" || fail "$name" "want *$want*, got: $got"; }

echo "── dual_review.sh helpers ──"

FN="$SANDBOX/fn.sh"
for f in die info write_prior codex_failure_cause codex_worktree_execs cmd_anchors; do
  sed -n "/^$f() {/,/^}/p" "$SCRIPT" >> "$FN"
done
# Run a helper the way the script does: under set -euo pipefail, in a subshell.
run() { "$BASH" -c 'set -euo pipefail; source "$1"; shift; "$@"' _ "$FN" "$@"; }

# ── write_prior ──
REPO="$SANDBOX/repo"; git init -q "$REPO"
git -C "$REPO" -c user.email=t@t -c user.name=t commit -q --allow-empty -m one
H1=$(git -C "$REPO" rev-parse HEAD)
echo "x" > "$REPO/a.txt"; git -C "$REPO" add a.txt
git -C "$REPO" -c user.email=t@t -c user.name=t commit -q -m two
H2=$(git -C "$REPO" rev-parse HEAD)
prior_run() { local d="$SANDBOX/prior-$1"; mkdir -p "$d"; printf '{"headRefOid":"%s"}' "$2" > "$d/pr.json"; echo "# Venn" > "$d/venn.md"; echo "$d"; }
new_run() { local d="$SANDBOX/run-$1"; mkdir -p "$d"; printf 'a.txt\n' > "$d/changed_files.txt"; echo "$d"; }

RD=$(new_run same); note=$(run write_prior "$(prior_run same "$H2")" "$RD" "$REPO" "$H2" 2>/dev/null); rc=$?
[[ $rc -eq 0 ]] && pass "an unmoved head (empty delta) does not abort prepare" || fail "an unmoved head (empty delta) does not abort prepare" "rc=$rc"
check "an unmoved head is said so in the note" "has not moved" "$note"

RD=$(new_run gone); note=$(run write_prior "$(prior_run gone 0123456789abcdef0123456789abcdef01234567)" "$RD" "$REPO" "$H2" 2>/dev/null); rc=$?
[[ $rc -eq 0 ]] && pass "a prior head missing from the repo does not abort prepare" || fail "a prior head missing from the repo does not abort prepare" "rc=$rc"
check "the note still points at prior.md" "prior.md" "$note"

RD=$(new_run moved); note=$(run write_prior "$(prior_run moved "$H1")" "$RD" "$REPO" "$H2" 2>/dev/null)
check "a moved head yields a delta limited to the PR's files" "a.txt" "$(cat "$RD/delta.patch" 2>/dev/null)"
check "the note points at delta.patch" "delta.patch" "$note"
check "prior.md falls back to the prior Venn" "# Venn" "$(cat "$RD/prior.md")"

# ── codex_worktree_execs ──
RUNDIR=/runs/r1
LOG="$SANDBOX/batch.log"
cat > "$LOG" <<EOF
exec
/bin/bash -lc 'cat $RUNDIR/diff.patch' in /wt
exec
/bin/bash -lc 'sed -n 1,9p src/a.py' in /wt
exec
/bin/bash -lc 'sed -n 1,9p src/b.py' in /wt
 succeeded in 3ms:
output
 succeeded in 4ms:
output
 succeeded in 5ms:
output
exec
/bin/bash -lc 'cat $RUNDIR/pr.json' in /wt
 succeeded in 1ms:
{}
EOF
check "a parallel batch credits successes beyond its run-dir reads" "2" "$(run codex_worktree_execs "$LOG" "$RUNDIR")"
cat > "$LOG" <<EOF
exec
/bin/bash -lc 'cat $RUNDIR/diff.patch' in /wt
exec
/bin/bash -lc 'ls src' in /wt
 succeeded in 3ms:
output
 exited 1 in 2ms:
ls: src: Operation not permitted
EOF
check "a denied worktree read beside a run-dir read credits nothing" "0" "$(run codex_worktree_execs "$LOG" "$RUNDIR")"

# ── codex_failure_cause ──
D="$SANDBOX/cause"; mkdir -p "$D"
printf 'exec\n/bin/bash -lc "grep 401 src/auth.py" in /wt\n succeeded in 3ms:\n12: raise HTTPError("401 Unauthorized")\n' > "$D/codex.log"
echo 124 > "$D/codex.exit"
check "a timeout is named as a timeout even when the log quotes 401" "timed out" "$(run codex_failure_cause "$D")"
echo 1 > "$D/codex.exit"
got=$(run codex_failure_cause "$D")
[[ -z "$got" ]] && pass "quoted code alone is not read as an auth failure" || fail "quoted code alone is not read as an auth failure" "got: $got"
echo "2026-10-12T20:25:23Z ERROR codex_api: HTTP error: 401 Unauthorized" >> "$D/codex.log"
check "codex's own 401 error line is named" "not logged in" "$(run codex_failure_cause "$D")"
S="$SANDBOX/sbx"; mkdir -p "$S"; echo 0 > "$S/codex.exit"
printf '%s\n' 'exec' "/bin/bash -lc 'ls' in /wt" ' exited 1 in 2ms:' \
  '{"summary":"Every file-read command failed: the sandbox requires bubblewrap, which is unavailable.","findings":[]}' > "$S/codex.log"
check "a sandbox failure reported only in codex's answer is named" "sandbox" "$(run codex_failure_cause "$S")"

# ── cmd_anchors ──
A="$SANDBOX/anch"; mkdir -p "$A"
cat > "$A/diff.patch" <<'EOF'
diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -10,4 +10,6 @@ def f():
 x
+y
diff --git a/gone.py b/gone.py
--- a/gone.py
+++ /dev/null
@@ -1,3 +0,0 @@
-z
EOF
run cmd_anchors "$A" src/a.py 15 && pass "a line inside a hunk is anchorable" || fail "a line inside a hunk is anchorable"
run cmd_anchors "$A" src/a.py 16 && fail "a line past the hunk is not anchorable" || pass "a line past the hunk is not anchorable"
run cmd_anchors "$A" gone.py 1 && fail "a deleted file has no head-side anchor" || pass "a deleted file has no head-side anchor"

echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
