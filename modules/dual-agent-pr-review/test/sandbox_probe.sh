#!/usr/bin/env bash
# The dual-review preflight must fail where codex cannot start its sandbox.
#
# codex 0.162 dropped its landlock backend: features.use_legacy_landlock, which
# this script used to pass where `unshare -Ur` failed, now panics, and codex
# then "reviews" without reading a file. The probe is codex itself, forced
# read-only, so a sandbox that cannot start fails preflight with the fix named
# instead of `run` rejecting the round twenty minutes later.
#
# The functions are EXTRACTED from the real script; `uname` and `codex` are
# stubs on PATH so the Linux branch runs on any host.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
REPO_ROOT="$PWD"
SCRIPT="skills/dual-agent-pr-review/scripts/dual_review.sh"
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

PASS=0; FAIL=0
pass() { PASS=$((PASS + 1)); printf "  PASS: %s\n" "$1"; }
fail() { FAIL=$((FAIL + 1)); printf "  FAIL: %s\n" "$1"; [[ -z "${2:-}" ]] || printf "       %s\n" "$2"; }

echo "── dual_review.sh: codex sandbox probe ──"

FN="$SANDBOX/fn.sh"
for f in die run_with_timeout resolve_codex codex_sandbox_works require_codex_sandbox; do
    sed -n "/^$f() {/,/^}/p" "$REPO_ROOT/$SCRIPT" >> "$FN"
done
grep -q '^require_codex_sandbox() {' "$FN" \
    && pass "require_codex_sandbox is defined in $SCRIPT" \
    || fail "require_codex_sandbox is missing from $SCRIPT"

grep -q -- '--enable use_legacy_landlock' "$REPO_ROOT/$SCRIPT" \
    && fail "the launch still passes --enable use_legacy_landlock (codex 0.162+ panics on it)" \
    || pass "no launch passes --enable use_legacy_landlock"

grep -q 'require_codex_sandbox$' "$REPO_ROOT/$SCRIPT" \
    && pass "require_tools calls the probe, so preflight, prepare and run all gate on it" \
    || fail "require_tools does not call require_codex_sandbox"

BIN="$SANDBOX/bin"; mkdir -p "$BIN"
cat > "$BIN/uname" <<'STUB'
#!/usr/bin/env bash
echo "${UNAME_STUB:-Linux}"
STUB
cat > "$BIN/codex" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$PROBE_LOG"
[[ "${CODEX_STUB:-ok}" == ok ]] || { echo "thread 'main' panicked: filesystem-restricted execution requires bubblewrap" >&2; exit 101; }
STUB
chmod +x "$BIN"/*
probe() { PROBE_LOG="$SANDBOX/probe.log" PATH="$BIN:$PATH" "$@" bash -c "source '$FN'; require_codex_sandbox" 2>"$SANDBOX/err"; }

: > "$SANDBOX/probe.log"
probe env CODEX_STUB=ok; rc=$?
[[ $rc -eq 0 ]] && pass "a sandbox that starts passes preflight" || fail "expected 0, got $rc" "$(cat "$SANDBOX/err")"
grep -q -- 'sandbox --disable use_legacy_landlock' "$SANDBOX/probe.log" && grep -q 'sandbox_mode="read-only"' "$SANDBOX/probe.log" \
    && pass "the probe runs codex sandbox read-only with the dead flag disabled" \
    || fail "probe args wrong" "$(cat "$SANDBOX/probe.log")"

probe env CODEX_STUB=fail; rc=$?
[[ $rc -ne 0 ]] && pass "a sandbox that cannot start fails preflight (rc=$rc)" || fail "expected non-zero exit"
grep -qF -- '--security-opt seccomp=' "$SANDBOX/err" \
    && pass "the failure names the seccomp fix" \
    || fail "failure message does not name the fix" "$(cat "$SANDBOX/err")"

: > "$SANDBOX/probe.log"
probe env CODEX_STUB=fail UNAME_STUB=Darwin; rc=$?
[[ $rc -eq 0 && ! -s "$SANDBOX/probe.log" ]] \
    && pass "macOS skips the probe (Seatbelt needs none)" \
    || fail "macOS ran or failed the probe" "rc=$rc $(cat "$SANDBOX/probe.log")"

echo
echo "$PASS passed, $FAIL failed"
[[ "$FAIL" == 0 ]]
