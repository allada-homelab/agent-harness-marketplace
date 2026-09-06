// Every hook-contract corpus case whose `harness` list includes "dsh", driven
// through the runner's real seams with the fixture scripts ACTUALLY executed.
//
// The ctx is a stub, but nothing else is: the manifests are on disk, the
// handlers are spawned processes, and `exec.arguments` is frozen exactly as
// @deepseek-ai/dsh-tools freezes it (lib/index.js:3047) — which is what makes
// the rewrite case deny rather than silently pass.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { apply } from "../lib/index.js";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../../..");
const contractDir = join(repoRoot, "hook-contract");
const corpus = JSON.parse(readFileSync(join(contractDir, "corpus.json"), "utf8"));

/** A throwaway module directory: the case's manifest, plus the fixtures it names. */
function moduleDirFor(hooks) {
  const dir = mkdtempSync(join(tmpdir(), "hook-runner-dsh-module-"));
  mkdirSync(join(dir, "hooks"));
  writeFileSync(join(dir, "hooks", "hooks.json"), JSON.stringify({ hooks }));
  // ${CLAUDE_PLUGIN_ROOT} must resolve to THIS directory, and the corpus names
  // its fixtures at `${CLAUDE_PLUGIN_ROOT}/fixtures/…`.
  symlinkSync(join(contractDir, "fixtures"), join(dir, "fixtures"));
  return dir;
}

/** Register the runner on a stub ctx, capturing seams, prompt contexts, and stderr. */
function wire(moduleDir, projectDir) {
  const seams = new Map();
  const contexts = new Map();
  const stderr = [];
  const realWrite = process.stderr.write.bind(process.stderr);
  process.stderr.write = (chunk, ...rest) => {
    stderr.push(String(chunk));
    return true;
  };
  const ctx = {
    on: (event, handler) => seams.set(event, handler),
    systemPrompt: { context: (entry) => contexts.set(entry.name, entry) },
    logger: { warn: () => {}, error: () => {} },
  };
  try {
    // profileDir null: this case pins its manifest, so auto-discovery is off.
    apply(ctx, { manifests: [moduleDir], profileDir: null });
  } finally {
    process.stderr.write = realWrite;
  }
  const session = { id: "corpus-session", header: { cwd: projectDir } };
  return {
    seams,
    contexts,
    stderr,
    session,
    /** Run `fn` with stderr captured, the way the harness would see it. */
    async capture(fn) {
      process.stderr.write = (chunk) => {
        stderr.push(String(chunk));
        return true;
      };
      try {
        return await fn();
      } finally {
        process.stderr.write = realWrite;
      }
    },
  };
}

const loud = (stderr) => stderr.some((line) => line.includes("hook-runner"));

/** What the runner's `hook-runner` line proves: the action was not silently dropped. */
function assertOutcome(kase, outcome, actual, harness) {
  if (outcome === "allow") {
    // No quietness assertion: the contract also spends a stderr line on a
    // skipped Claude-only handler, which is an `allow` case too.
    assert.equal(actual.kind, "allow", `${kase.name}: expected allow, got ${JSON.stringify(actual)}`);
    return;
  }
  if (outcome === "deny") {
    assert.equal(actual.kind, "deny", `${kase.name}: expected deny, got ${JSON.stringify(actual)}`);
    assert.ok(
      actual.reason.includes(kase.reason),
      `${kase.name}: reason ${JSON.stringify(actual.reason)} does not contain ${JSON.stringify(kase.reason)}`,
    );
    return;
  }
  if (outcome === "failed-open") {
    assert.equal(actual.kind, "allow", `${kase.name}: a failed handler must not block`);
    assert.ok(loud(harness.stderr), `${kase.name}: a failed handler must write a hook-runner line to stderr`);
    return;
  }
  assert.fail(`${kase.name}: unhandled outcome ${outcome}`);
}

/** The stdin the fixture actually received, via fixtures/echo.py. */
function readEcho(echoPath) {
  try {
    return JSON.parse(readFileSync(echoPath, "utf8"));
  } catch {
    return null;
  }
}

/** What this case says the dsh handler must have received, if anything. */
const stdinExpectationsFor = (kase) => kase.stdin_by_harness?.dsh ?? kase.stdin ?? null;

/**
 * Assert every key/value the corpus says the handler received.
 *
 * No probe handler is injected: every contract fixture writes the event it saw
 * to `$HOOK_CONTRACT_ECHO` itself, so the manifest under test is the manifest
 * the corpus wrote — which is the only way `stop_hook_active`, a flag only a
 * real block from stop_block.py can set, is observed on the real path.
 */
function assertStdin(kase, seen, projectDir) {
  const expectations = stdinExpectationsFor(kase);
  if (!expectations) return;
  assert.ok(seen, `${kase.name}: the fixture recorded no stdin`);
  for (const [key, expected] of Object.entries(expectations)) {
    const want = expected === "$PROJECT_DIR" ? projectDir : expected;
    assert.deepEqual(seen[key], want, `${kase.name}: stdin.${key}`);
  }
}

/** Drive one native dsh event through the runner; returns what the seam produced. */
async function drive(native, harness, agent) {
  if (native.event === "tools/pre-execute") {
    const exec = { name: native.name, arguments: Object.freeze({ ...native.args }), agent };
    const decision = await harness.capture(() =>
      harness.seams.get("tools/pre-execute")(exec, () => Promise.resolve({ kind: "allow" })),
    );
    return { kind: decision.kind, reason: decision.reason ?? "" };
  }
  if (native.event === "tools/post-execute") {
    const exec = { name: native.name, arguments: Object.freeze({ ...native.args }), agent };
    const decision = await harness.capture(() =>
      harness.seams.get("tools/post-execute")(exec, native.result, () => Promise.resolve({ kind: "accept" })),
    );
    // PostToolUse cannot block in this contract; `accept` is its "allow".
    // Its context rides `additionalContexts` (@deepseek-ai/dsh-tools
    // lib/types/index.d.ts:435), not the prompt assembly.
    const context = (decision.additionalContexts ?? [])
      .flatMap((message) => message.content ?? [])
      .filter((block) => block?.type === "text")
      .map((block) => block.text)
      .join("\n");
    return { kind: decision.kind === "accept" ? "allow" : decision.kind, reason: "", context };
  }
  if (native.event === "systemPrompt.context") {
    const messages = [{ role: "user", source: { kind: "user" }, content: [{ type: "text", text: native.prompt }] }];
    await harness.capture(() =>
      harness.seams.get("agent/pre-step")({ agent, messages, turn: 1, step: 1 }, () =>
        Promise.resolve({ kind: "enter", messages }),
      ),
    );
    return { kind: "allow", reason: "", context: harness.contexts.get("hook-runner-dsh:user-prompt-submit").text({ scope: agent }) };
  }
  if (native.event === "session/created") {
    await harness.capture(async () => {
      harness.seams.get("session/created")(harness.session);
      // `agent/pre-step` awaits the SessionStart run before the first assembly —
      // the same ordering the real loop provides.
      await harness.seams.get("agent/pre-step")({ agent, messages: [], turn: 1, step: 1 }, () =>
        Promise.resolve({ kind: "enter", messages: [] }),
      );
    });
    return { kind: "allow", reason: "", context: harness.contexts.get("hook-runner-dsh:session-start").text({ scope: agent }) };
  }
  if (native.event === "agent/turn-stopping") {
    const fire = () => harness.capture(() => harness.seams.get("agent/turn-stopping")({ agent, turn: 1 }));
    // A `stop_hook_active: true` event is by definition the SECOND fire; the
    // first is what set the flag, exactly as a real blocked turn would.
    if (native.stop_hook_active) {
      await fire();
      agent.steered.length = 0;
    }
    await fire();
    return { kind: "allow", reason: "", steered: agent.steered };
  }
  assert.fail(`no dsh seam for native event ${native.event}`);
}

const newAgent = (session) => ({ session, steered: [], steer(message) { this.steered.push(message); } });

const cases = corpus.cases.filter((kase) => kase.harness.includes("dsh"));
assert.ok(cases.length > 0, "the corpus contains no dsh cases");

for (const kase of cases) {
  test(`corpus: ${kase.name}`, async () => {
    const outcome = kase.outcome_by_harness?.dsh ?? kase.outcome;
    const projectDir = mkdtempSync(join(tmpdir(), "hook-runner-dsh-project-"));
    process.env.HOOK_CONTRACT_ECHO = join(projectDir, "echo.json");
    const harness = wire(moduleDirFor(kase.hooks), projectDir);
    const result = await drive(kase.native.dsh, harness, newAgent(harness.session));

    if (outcome === "stop-block") {
      assert.equal(result.steered.length, 1, `${kase.name}: the turn was not steered`);
      const text = result.steered[0].content.map((b) => b.text).join("");
      assert.ok(text.includes(kase.reason), `${kase.name}: steer text ${JSON.stringify(text)} lacks the reason`);
    } else if (outcome === "context") {
      assert.ok(
        result.context.includes(kase.additionalContext),
        `${kase.name}: assembled context ${JSON.stringify(result.context)} lacks ${JSON.stringify(kase.additionalContext)}`,
      );
    } else {
      assertOutcome(kase, outcome, result, harness);
      if (result.steered) assert.equal(result.steered.length, 0, `${kase.name}: the turn was steered unexpectedly`);
    }
  });

  if (!stdinExpectationsFor(kase)) continue;
  test(`corpus stdin: ${kase.name}`, async () => {
    const projectDir = mkdtempSync(join(tmpdir(), "hook-runner-dsh-stdin-"));
    const echoPath = join(projectDir, "echo.json");
    process.env.HOOK_CONTRACT_ECHO = echoPath;
    const harness = wire(moduleDirFor(kase.hooks), projectDir);
    await drive(kase.native.dsh, harness, newAgent(harness.session));
    assertStdin(kase, readEcho(echoPath), projectDir);
  });
}
