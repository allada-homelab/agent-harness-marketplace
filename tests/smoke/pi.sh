#!/usr/bin/env bash
# Real pi, throwaway $HOME: install this checkout as a package, then prove the
# root manifest resolves correctly end to end — the portable skills load
# natively, and the Claude-only modules stay out. `/name` commands and hook
# delivery are pi harness-side foundation now (skill-commands.ts,
# hook-runner.ts in the maintainer's harness layer) and are not exercised from
# this repo. A dummy API key lets pi reach `before_agent_start`, where the
# probe exits before any request.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
home=$(mktemp -d); trap 'rm -rf "$home"' EXIT
export HOME="$home"
mkdir -p "$home/work"
cat > "$home/probe.ts" <<'TS'
export default function (pi) {
  pi.on("before_agent_start", async () => {
    const out = pi.getCommands().filter(c => c.source === "skill" || c.source === "extension").map(c => c.source + " " + c.name);
    process.stderr.write("PROBE " + JSON.stringify(out) + "\n");
    process.exit(0);
  });
}
TS

echo "== pi install"
pi install "$repo"
cd "$home/work"
echo "== pi run"
set +e
ANTHROPIC_API_KEY=sk-ant-dummy-not-a-key \
  timeout 180 pi -e "$home/probe.ts" -p "hi" > "$home/run.log" 2>&1
rc=$?
set -e
probe=$(grep -a '^PROBE ' "$home/run.log" || true)
echo "rc=$rc"; echo "$probe"
fail=0
check() { if eval "$2"; then echo "  ok   $1"; else echo "  FAIL $1"; fail=1; fi; }
check "pi exited from the probe (rc 0)" '[ "$rc" = 0 ]'
check "portable skills loaded" '[[ "$probe" == *"skill:pragmatic-code-review"* && "$probe" == *"skill:get-shit-done"* && "$probe" == *"skill:research"* ]]'
check "Claude-only modules excluded" '[[ "$probe" != *"claude-transcript"* && "$probe" != *"dual-agent"* && "$probe" != *"skill:run"* ]]'
[ "$fail" = 0 ] || { echo "--- run.log"; tail -30 "$home/run.log"; exit 1; }
