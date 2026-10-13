#!/usr/bin/env bash
# The dual-review preflight must know whether codex can start its sandbox.
#
# codex 0.162 dropped its landlock backend: features.use_legacy_landlock, which
# this script used to pass where `unshare -Ur` failed, now panics, and codex
# then "reviews" without reading a file. The probe is codex itself, forced
# read-only. Where it cannot start inside a container, codex runs
# danger-full-access (the container is the boundary) and preflight says so;
# on a host preflight fails instead of running the PR's code unsandboxed.
#
# The functions are EXTRACTED from the real script; `uname` and `codex` are
# stubs on PATH so the Linux branch runs on any host, and REMOTE_CONTAINERS
# stands in for a container.
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
for f in die run_with_timeout resolve_codex in_container codex_sandbox_works codex_sandbox_mode; do
    sed -n "/^$f() {/,/^}/p" "$REPO_ROOT/$SCRIPT" >> "$FN"
done
grep -q '^codex_sandbox_mode() {' "$FN" \
    && pass "codex_sandbox_mode is defined in $SCRIPT" \
    || fail "codex_sandbox_mode is missing from $SCRIPT"

grep -q -- '--enable use_legacy_landlock' "$REPO_ROOT/$SCRIPT" \
    && fail "the launch still passes --enable use_legacy_landlock (codex 0.162+ panics on it)" \
    || pass "no launch passes --enable use_legacy_landlock"

grep -q 'codex_sandbox_mode >/dev/null$' "$REPO_ROOT/$SCRIPT" \
    && pass "require_tools calls the probe, so preflight, prepare and run all gate on it" \
    || fail "require_tools does not call codex_sandbox_mode"
grep -qE -- '--sandbox "\$codex_sandbox"' "$REPO_ROOT/$SCRIPT" \
    && pass "the launch passes the probed mode, not a hard-coded one" \
    || fail "launch does not use the probed sandbox mode"

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
# $@ = env assignments; prints the mode, stderr to $SANDBOX/err. REMOTE_CONTAINERS
# is cleared unless the case sets it, so a real dev container cannot skew the host case.
probe() { env -u REMOTE_CONTAINERS -u REMOTE_CONTAINERS_IPC -u CODESPACES PROBE_LOG="$SANDBOX/probe.log" PATH="$BIN:$PATH" "$@" bash -c "source '$FN'; [[ -f /.dockerenv || -f /run/.containerenv ]] && exit 99; codex_sandbox_mode" 2>"$SANDBOX/err"; }

: > "$SANDBOX/probe.log"
mode=$(probe env CODEX_STUB=ok); rc=$?
[[ $rc -eq 0 && "$mode" == read-only ]] && pass "a sandbox that starts gives read-only" || fail "expected read-only rc 0, got '$mode' rc=$rc" "$(cat "$SANDBOX/err")"
grep -q -- 'sandbox --disable use_legacy_landlock' "$SANDBOX/probe.log" && grep -q 'sandbox_mode="read-only"' "$SANDBOX/probe.log" \
    && pass "the probe runs codex sandbox read-only with the dead flag disabled" \
    || fail "probe args wrong" "$(cat "$SANDBOX/probe.log")"

mode=$(probe env CODEX_STUB=fail REMOTE_CONTAINERS=true); rc=$?
if [[ $rc -eq 99 ]]; then
    pass "host case skipped: this test is itself running in a container (cannot prove the host branch here)"
else
    [[ $rc -eq 0 && "$mode" == danger-full-access ]] \
        && pass "in a container, a sandbox that cannot start falls back to danger-full-access" \
        || fail "expected danger-full-access rc 0, got '$mode' rc=$rc" "$(cat "$SANDBOX/err")"
fi

mode=$(probe env CODEX_STUB=fail); rc=$?
if [[ $rc -eq 99 ]]; then
    pass "host case skipped: this test is itself running in a container"
else
    [[ $rc -ne 0 && -z "$mode" ]] && pass "on a host, a sandbox that cannot start fails preflight (rc=$rc)" || fail "expected failure, got '$mode' rc=$rc"
    grep -q "danger-full-access outside a container" "$SANDBOX/err" \
        && pass "the host failure explains why it does not fall back" \
        || fail "host failure message wrong" "$(cat "$SANDBOX/err")"
fi

: > "$SANDBOX/probe.log"
mode=$(probe env CODEX_STUB=fail UNAME_STUB=Darwin); rc=$?
[[ $rc -eq 0 && "$mode" == read-only && ! -s "$SANDBOX/probe.log" ]] \
    && pass "macOS skips the probe (Seatbelt needs none)" \
    || fail "macOS ran or failed the probe" "rc=$rc mode=$mode $(cat "$SANDBOX/probe.log")"

echo
echo "$PASS passed, $FAIL failed"
[[ "$FAIL" == 0 ]]
