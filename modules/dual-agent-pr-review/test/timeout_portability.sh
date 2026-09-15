#!/usr/bin/env bash
# The dual-review agent launch must survive a host with no `timeout`.
#
# macOS ships neither GNU `timeout` nor `gtimeout` unless coreutils is
# installed, and the two agent launches in dual_review.sh are wrapped in one —
# so on such a host every round died instantly with "timeout: command not
# found", which reads as an agent failure but never started an agent.
#
# The function is EXTRACTED from the real script rather than copied, so these
# cases cannot pass against a version that no longer has it. The fallback is
# driven by stripping PATH down to a dir with no timeout in it, which is the
# only way to exercise the branch on a Linux CI box that has one.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
REPO_ROOT="$PWD"
SCRIPT="skills/dual-agent-pr-review/scripts/dual_review.sh"
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

PASS=0; FAIL=0
pass() { PASS=$((PASS + 1)); printf "  PASS: %s\n" "$1"; }
fail() { FAIL=$((FAIL + 1)); printf "  FAIL: %s\n" "$1"; [[ -z "${2:-}" ]] || printf "       %s\n" "$2"; }

echo "── dual_review.sh: timeout portability ──"

FN="$SANDBOX/fn.sh"
sed -n '/^run_with_timeout() {/,/^}/p' "$REPO_ROOT/$SCRIPT" > "$FN"
[[ -s "$FN" ]] \
    && pass "run_with_timeout is defined in $SCRIPT" \
    || fail "run_with_timeout is missing from $SCRIPT"

# Both launches must go through it — a helper only half-adopted still dies on
# the call site that kept the bare builtin.
if grep -qE '^\s+timeout "\$AGENT_TIMEOUT"' "$REPO_ROOT/$SCRIPT"; then
    fail "a bare 'timeout \$AGENT_TIMEOUT' call site remains" "$(grep -nE '^\s+timeout "\$AGENT_TIMEOUT"' "$REPO_ROOT/$SCRIPT")"
else
    n=$(grep -cE 'run_with_timeout "\$AGENT_TIMEOUT"' "$REPO_ROOT/$SCRIPT")
    [[ "$n" == "2" ]] \
        && pass "both agent launches go through run_with_timeout" \
        || fail "expected 2 wrapped launches, found $n"
fi

# ── with a real `timeout` on PATH ────────────────────────────────────────────
run_fn() { ( source "$FN"; run_with_timeout "$@" ); }

run_fn 5 true; rc=$?
[[ $rc -eq 0 ]] && pass "a command that succeeds returns 0" || fail "expected 0, got $rc"

run_fn 5 sh -c 'exit 7'; rc=$?
[[ $rc -eq 7 ]] && pass "a command's own non-zero exit is propagated" || fail "expected 7, got $rc"

start=$(date +%s); run_fn 1 sleep 10; rc=$?; el=$(( $(date +%s) - start ))
[[ $rc -eq 124 && $el -lt 6 ]] \
    && pass "an overrunning command is killed and reports 124 (${el}s)" \
    || fail "expected rc 124 within 6s, got rc=$rc after ${el}s"

# ── and with NO timeout binary anywhere: the macOS case ──────────────────────
BIN="$SANDBOX/bin"; mkdir -p "$BIN"
# Everything a real host has EXCEPT timeout/gtimeout — withholding mktemp too
# would exercise the unbounded-degradation branch instead of the fallback.
for b in sleep sh true mktemp rm; do ln -sf "$(command -v $b)" "$BIN/$b"; done
command -v timeout >/dev/null && [[ ! -e "$BIN/timeout" ]] \
    && pass "the sandbox PATH really has no timeout (the branch is reachable)" \
    || fail "sandbox PATH still resolves timeout"

run_bare() { ( PATH="$BIN"; source "$FN"; run_with_timeout "$@" ); }

run_bare 5 true; rc=$?
[[ $rc -eq 0 ]] && pass "fallback: a fast command still returns 0" || fail "fallback expected 0, got $rc"

run_bare 5 sh -c 'exit 7'; rc=$?
[[ $rc -eq 7 ]] && pass "fallback: a non-zero exit is propagated" || fail "fallback expected 7, got $rc"

# Repeated, because the first cut of this helper inferred expiry from whether
# the watchdog was still alive — a race that returns the job's 143 instead of
# 124, and that a single trial happily passes through.
bad=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
    run_bare 1 sleep 5; rc=$?
    [[ $rc -eq 124 ]] || bad="$bad $rc"
done
[[ -z "$bad" ]] \
    && pass "fallback: an overrunning command reports 124, in 10 of 10 trials" \
    || fail "fallback: 124 is not deterministic" "off-trials returned:$bad"

# GNU timeout signals the process GROUP (that is what --foreground opts out
# of). An agent launch spawns tool subprocesses, so signalling only the
# top-level PID leaves them running past the deadline — measured before this
# helper took the job's process group.
MARK="$RANDOM.5"
run_bare 1 sh -c "sleep $MARK & wait" >/dev/null 2>&1
sleep 1
orphans=$(pgrep -f "sleep $MARK" | wc -l)
pkill -f "sleep $MARK" 2>/dev/null
[[ "$orphans" -eq 0 ]] \
    && pass "fallback: the command's children die with it, not after it" \
    || fail "fallback: $orphans child process(es) outlived the timeout"

echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
