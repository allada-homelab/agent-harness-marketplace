#!/usr/bin/env bash
# `dual_review.sh run` must report what actually happened to each reviewer.
#
# Every case here is a failure seen in real runs: a non-zero codex exit that
# surfaced as "exit ?" (the launch subshell inherited set -e), an exhausted or
# logged-out account reported as "read no files", a codex that only ever read
# the run dir passing the evidence gate, and a one-side re-run that wiped the
# other side's result. `claude` and `codex` are stubs on PATH; CODEX_MODE picks
# the codex behaviour.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
SCRIPT="$PWD/skills/dual-agent-pr-review/scripts/dual_review.sh"
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

PASS=0; FAIL=0
pass() { PASS=$((PASS + 1)); printf "  PASS: %s\n" "$1"; }
fail() { FAIL=$((FAIL + 1)); printf "  FAIL: %s\n" "$1"; [[ -z "${2:-}" ]] || printf "       %s\n" "$2"; }
check() { local name="$1" want="$2" got="$3"; [[ "$got" == *"$want"* ]] && pass "$name" || fail "$name" "want *$want*, got: $got"; }

echo "── dual_review.sh run: status and exit reporting ──"

BIN="$SANDBOX/bin"; mkdir -p "$BIN"
cat > "$BIN/claude" <<'STUB'
#!/usr/bin/env bash
[[ "${CLAUDE_MODE:-ok}" == ok ]] || exit 7
echo '{"structured_output":{"summary":"s","findings":[]}}'
STUB
cat > "$BIN/codex" <<'STUB'
#!/usr/bin/env bash
[[ "$1" == sandbox ]] && exit 0
out=""; while [[ $# -gt 0 ]]; do [[ "$1" == --output-last-message ]] && out="$2"; shift; done
answer='{"summary":"s","findings":[]}'
[[ "${CODEX_ITEMS:-0}" -gt 0 ]] && answer=$(printf '{"verdicts":[%s],"withdrawn":[],"notes":""}' \
  "$(for i in $(seq "$CODEX_ITEMS"); do printf '%s{"finding_id":"CC-%d"}' "$([[ $i -gt 1 ]] && echo ,)" "$i"; done)")
case "${CODEX_MODE:-ok}" in
  ok)      printf 'exec\n/bin/bash -lc "sed -n 1,9p src/app.py" in /wt\n succeeded in 3ms:\n' >&2
           echo "$answer" > "$out" ;;
  rundir)  printf 'exec\n/bin/bash -lc "cat %s/diff.patch" in /wt\n succeeded in 3ms:\n' "$RUN_DIR_UNDER_TEST" >&2
           echo "$answer" > "$out" ;;
  mention) printf 'exec\n/bin/bash -lc "grep -n bubblewrap src/app.py" in /wt\n succeeded in 3ms:\n12: # 401 Unauthorized, out of credits, requires bubblewrap\n' >&2
           echo "$answer" > "$out" ;;
  credits) echo "ERROR: Your workspace is out of credits. Ask your workspace owner to refill in order to continue." >&2; exit 3 ;;
  auth)    echo "ERROR codex_api: failed to connect to websocket: HTTP error: 401 Unauthorized" >&2; exit 1 ;;
esac
STUB
chmod +x "$BIN/claude" "$BIN/codex"
export PATH="$BIN:$PATH" CODEX_BIN="$BIN/codex"

new_run() {
  local rd="$SANDBOX/run$1"
  mkdir -p "$rd/round1" "$SANDBOX/wt"
  printf 'RUN_DIR=%s\nWORKTREE=%s\nCLAUDE_MODEL=m\nCLAUDE_EFFORT=high\nCODEX_MODEL=m\nCODEX_EFFORT=high\nAGENT_TIMEOUT=60\n' \
    "$rd" "$SANDBOX/wt" > "$rd/config.env"
  echo "review" > "$rd/round1/claude.prompt.md"
  echo "review" > "$rd/round1/codex.prompt.md"
  echo "$rd"
}
status() { cat "$1/round1/$2.status" 2>/dev/null || echo "<none>"; }

RD=$(new_run 1); CODEX_MODE=ok "$BASH" "$SCRIPT" run "$RD" round1 findings >/dev/null 2>&1; rc=$?
check "both reviewers ok → claude ok" "ok" "$(status "$RD" claude)"
check "both reviewers ok → codex ok" "ok" "$(status "$RD" codex)"
[[ $rc -eq 0 ]] && pass "both ok → run exits 0" || fail "both ok → run exits 0" "rc=$rc"

RD=$(new_run 2); CODEX_MODE=credits "$BASH" "$SCRIPT" run "$RD" round1 findings >/dev/null 2>&1; rc=$?
check "a non-zero codex exit is recorded, not lost to set -e" "3" "$(cat "$RD/round1/codex.exit" 2>/dev/null || echo '<none>')"
check "out of credits is named as the cause" "out of credits" "$(status "$RD" codex)"
[[ $rc -ne 0 ]] && pass "a failed side makes run exit non-zero" || fail "a failed side makes run exit non-zero"

RD=$(new_run 3); CODEX_MODE=auth "$BASH" "$SCRIPT" run "$RD" round1 findings >/dev/null 2>&1
check "a 401 is named as not logged in" "not logged in" "$(status "$RD" codex)"

RD=$(new_run 4); RUN_DIR_UNDER_TEST="$RD" CODEX_MODE=rundir "$BASH" "$SCRIPT" run "$RD" round1 findings >/dev/null 2>&1
check "reading only the run dir fails the evidence gate" "read no code" "$(status "$RD" codex)"
[[ ! -f "$RD/round1/codex.json" ]] && pass "a void codex answer is discarded" || fail "a void codex answer is discarded"

RD=$(new_run 5); CODEX_MODE=credits "$BASH" "$SCRIPT" run "$RD" round1 findings >/dev/null 2>&1
claude_before=$(status "$RD" claude)
CODEX_MODE=ok "$BASH" "$SCRIPT" run --only codex "$RD" round1 findings >/dev/null 2>&1; rc=$?
check "--only codex re-runs codex" "ok" "$(status "$RD" codex)"
check "--only codex leaves claude's result alone" "$claude_before" "$(status "$RD" claude)"
check "the failed attempt is archived, not overwritten" "out of credits" "$(cat "$RD/round1/attempt-1/codex.status" 2>/dev/null || echo '<none>')"
[[ $rc -eq 0 ]] && pass "--only re-run exits 0 once both sides are ok" || fail "--only re-run exits 0 once both sides are ok" "rc=$rc"

RD=$(new_run 6); rm "$RD/round1/claude.prompt.md"
CODEX_MODE=ok "$BASH" "$SCRIPT" run "$RD" round1 findings >/dev/null 2>&1; rc=$?
check "a side with no prompt is skipped as an empty docket" "skipped" "$(status "$RD" claude)"
[[ $rc -eq 0 ]] && pass "an empty docket is not a failure" || fail "an empty docket is not a failure" "rc=$rc"

RD=$(new_run 7); CODEX_MODE=ok CODEX_ITEMS=9 "$BASH" "$SCRIPT" run "$RD" round1 verdicts >/dev/null 2>&1
check "one command for nine verdicts is flagged as low evidence" "low evidence" "$(status "$RD" codex)"

RD=$(new_run 9); CODEX_MODE=mention "$BASH" "$SCRIPT" run "$RD" round1 findings >/dev/null 2>&1
check "a good review of code that mentions failure strings stays ok" "ok" "$(status "$RD" codex)"

RD=$(new_run 8); CODEX_MODE=ok CLAUDE_MODE=fail "$BASH" "$SCRIPT" run "$RD" round1 findings >/dev/null 2>&1
check "a claude failure records its real exit code" "exit 7" "$(status "$RD" claude)"

echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
