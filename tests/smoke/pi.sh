#!/usr/bin/env bash
# Real pi, throwaway $HOME: install this checkout as a package, then prove the
# root manifest and both pi foundation modules work end to end — the portable
# skills load, the Claude-only modules stay out, skill-commands-pi registers
# `/research`, and hook-runner-pi delivers a SessionStart hook. A dummy API key
# lets pi reach `before_agent_start`, where the probe exits before any request.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
home=$(mktemp -d); trap 'rm -rf "$home"' EXIT
export HOME="$home"
mkdir -p "$home/work" "$home/fleetmod/hooks"
printf '%s\n' '{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"python3 \"${CLAUDE_PLUGIN_ROOT}/echo.py\""}]}]}}' > "$home/fleetmod/hooks/hooks.json"
cp "$repo/hook-contract/fixtures/echo.py" "$home/fleetmod/echo.py"
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
ANTHROPIC_API_KEY=sk-ant-dummy-not-a-key PI_HOOK_MANIFESTS="$home/fleetmod" HOOK_CONTRACT_ECHO="$home/echo.json" \
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
check "skill-commands-pi registered /research" '[[ "$probe" == *"extension research"* ]]'
check "hook-runner-pi delivered SessionStart" 'grep -q "\"hook_event_name\": \"SessionStart\"" "$home/echo.json" 2>/dev/null'
[ "$fail" = 0 ] || { echo "--- run.log"; tail -30 "$home/run.log"; exit 1; }
