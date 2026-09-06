// Two interleaved sessions must not read each other's hook context.
//
// The delivery seam is `systemPrompt.context`, whose `AssembleContext` carries
// only `scope` and `signal`. dsh-agent mints the agent as its own scope key
// (`scope: agent`, @deepseek-ai/dsh-agent lib/index.js:387) and an agent's id
// is its session id (:603), so the assembly names its session. This proves the
// runner keys on that rather than on a single "latest session" pointer.
import { test } from "node:test";
import assert from "node:assert/strict";
import { chmodSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { apply } from "../lib/index.js";

/** A handler that echoes back the session it was told about, as injected context. */
const ECHO_SESSION = `#!/usr/bin/env python3
import json, sys
event = json.load(sys.stdin)
print(json.dumps({"hookSpecificOutput": {"additionalContext": "CTX-" + event["session_id"]}}))
`;

/** A module whose SessionStart and UserPromptSubmit hooks both name their session. */
function moduleDir() {
  const dir = mkdtempSync(join(tmpdir(), "hook-runner-dsh-sessions-"));
  mkdirSync(join(dir, "hooks"));
  const script = join(dir, "hooks", "echo_session.py");
  writeFileSync(script, ECHO_SESSION);
  chmodSync(script, 0o755);
  const entry = { hooks: [{ type: "command", command: `python3 "${script}"` }] };
  writeFileSync(
    join(dir, "hooks", "hooks.json"),
    JSON.stringify({ hooks: { SessionStart: [entry], UserPromptSubmit: [entry] } }),
  );
  return dir;
}

/** Register the runner on a stub ctx and hand back its seams and prompt providers. */
function wire(dir) {
  const seams = new Map();
  const contexts = new Map();
  apply(
    {
      on: (event, handler) => seams.set(event, handler),
      systemPrompt: { context: (provider) => contexts.set(provider.name, provider) },
      logger: { warn: () => {}, error: () => {} },
    },
    { manifests: [dir], profileDir: null },
  );
  return { seams, contexts };
}

const newSession = (id) => ({ id, header: { cwd: process.cwd() } });
const newAgent = (session) => ({ id: session.id, session, steer() {} });

/** Drive one session's start + one prompt, exactly as the loop orders them. */
async function startAndPrompt(harness, agent, prompt) {
  harness.seams.get("session/created")(agent.session);
  const messages = [{ role: "user", source: { kind: "user" }, content: [{ type: "text", text: prompt }] }];
  await harness.seams.get("agent/pre-step")({ agent, messages, turn: 1, step: 1 }, () =>
    Promise.resolve({ kind: "enter", messages }),
  );
}

/** What the named provider contributes to an assembly scoped to `agent`. */
const assembled = (harness, name, agent) => harness.contexts.get(`hook-runner-dsh:${name}`).text({ scope: agent });

test("each session's SessionStart context reaches only that session's assembly", async () => {
  const harness = wire(moduleDir());
  const alice = newAgent(newSession("alice"));
  const bob = newAgent(newSession("bob"));

  await startAndPrompt(harness, alice, "first");
  await startAndPrompt(harness, bob, "second");

  assert.equal(assembled(harness, "session-start", alice), "CTX-alice");
  assert.equal(assembled(harness, "session-start", bob), "CTX-bob");
});

test("an interleaved prompt does not leak into the other session's assembly", async () => {
  const harness = wire(moduleDir());
  const alice = newAgent(newSession("alice"));
  const bob = newAgent(newSession("bob"));

  await startAndPrompt(harness, alice, "first");
  await startAndPrompt(harness, bob, "second");
  await startAndPrompt(harness, alice, "third");

  assert.equal(assembled(harness, "user-prompt-submit", bob), "CTX-bob");
});

test("an assembly with no readable scope falls back to the latest session, loudly", async () => {
  const harness = wire(moduleDir());
  const alice = newAgent(newSession("alice"));
  await startAndPrompt(harness, alice, "first");

  const stderr = [];
  const realWrite = process.stderr.write.bind(process.stderr);
  process.stderr.write = (chunk) => {
    stderr.push(String(chunk));
    return true;
  };
  let text;
  try {
    text = harness.contexts.get("hook-runner-dsh:session-start").text({});
  } finally {
    process.stderr.write = realWrite;
  }

  assert.equal(text, "CTX-alice");
  assert.ok(
    stderr.some((line) => line.includes("hook-runner") && line.includes("no readable session scope")),
    `expected one loud line about the missing scope, got ${JSON.stringify(stderr)}`,
  );
});

test("session/disposed drops that session's state", async () => {
  const harness = wire(moduleDir());
  const alice = newAgent(newSession("alice"));
  await startAndPrompt(harness, alice, "first");
  assert.equal(assembled(harness, "session-start", alice), "CTX-alice");

  harness.seams.get("session/disposed")(alice.session);
  assert.equal(assembled(harness, "session-start", alice), "");
});
