/**
 * MEASUREMENT SPIKE — run background agent work after a pi turn ends.
 *
 * Question for the okf-wiki design: can an extension do post-turn work off the
 * turn's critical path, and how does the result get back in front of the model?
 *
 * Seam. `agent_settled` carries an empty payload — `interface AgentSettledEvent
 * { type: 'agent_settled' }` (PKG/dist/core/extensions/types.d.ts:545). The
 * handler chain is SERIAL AND AWAITED: `for (const ext …) for (const handler …)
 * await handler(event, ctx)` (PKG/dist/core/extensions/runner.js:579), emitted
 * as `await this._extensionRunner.emit({type:'agent_settled'})` before the idle
 * wait resolves (PKG/dist/core/agent-session.js:327). So the handler must NOT
 * await the child — it spawns and returns synchronously.
 *
 * Transport. `pi.exec(command, args, options)` takes only `{signal, timeout,
 * cwd}` (PKG/dist/core/exec.d.ts:7) and buffers-and-awaits the whole process —
 * it cannot detach. So this uses `node:child_process.spawn`, the same call the
 * shipped subagent example makes (PKG/examples/extensions/subagent/index.ts:335).
 *
 * Injection. Two channels, both exercised here so the docs can record what the
 * model actually sees:
 *   - `pi.appendEntry(customType, data)` (types.d.ts:936) persists a `custom`
 *     session entry that explicitly does NOT participate in LLM context
 *     (PKG/docs/extensions.md:1440, session-format.md:340). State only.
 *   - `pi.sendMessage({customType, content, display}, {deliverAs})`
 *     (types.d.ts:924) persists a `custom_message`, which IS in context
 *     (session-format.md:339). `deliverAs:'nextTurn'` queues it for the next
 *     user prompt without interrupting or triggering a turn (extensions.md:1407).
 *
 * Recursion guard. A child `pi -p` re-runs discovery and would load this same
 * extension. `-ne` disables discovery and SPIKE_PI_CHILD is belt-and-braces for
 * the explicit `-e` case.
 */
import { spawn } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const OUT_DIR = process.env.SPIKE_OUT_DIR || "";
const CHILD_TASK =
  "Write the single word DONE to the file child-done.txt in the current directory, then reply with exactly: DONE";

function record(event: Record<string, unknown>): void {
  const line = JSON.stringify({ t: Date.now(), iso: new Date().toISOString(), ...event });
  try {
    if (OUT_DIR) {
      mkdirSync(OUT_DIR, { recursive: true });
      appendFileSync(path.join(OUT_DIR, "spike.jsonl"), `${line}\n`);
    }
  } catch {
    /* logging must never break the turn */
  }
  process.stderr.write(`spike-pi-background ${line}\n`);
}

/** How to re-invoke pi itself — verbatim shape from PKG/examples/extensions/subagent/index.ts:248. */
function piInvocation(args: string[]): { command: string; args: string[] } {
  const script = process.argv[1];
  if (script && !script.startsWith("/$bunfs/root/") && existsSync(script)) {
    return { command: process.execPath, args: [script, ...args] };
  }
  const exec = path.basename(process.execPath).toLowerCase();
  if (!/^(node|bun)(\.exe)?$/.test(exec)) return { command: process.execPath, args };
  return { command: "pi", args };
}

export default function (pi: ExtensionAPI): void {
  if (process.env.SPIKE_PI_CHILD) {
    record({ phase: "child-guard-hit" });
    return;
  }
  const mode = process.env.SPIKE_MODE || "detached-unref";
  let dispatched = false;
  record({ phase: "extension-loaded", mode, pid: process.pid });

  pi.on("agent_settled", (_event, ctx) => {
    if (dispatched) return;
    dispatched = true;
    const t0 = Date.now();
    record({ phase: "agent-settled-enter", mode, cwd: (ctx as { cwd?: string }).cwd });

    // `--no-session` keeps the child's JSONL out of the sessions tree entirely;
    // `-ne -ns -nc` stop it inheriting this extension, skills, and AGENTS.md —
    // that inheritance is both the recursion risk and the token cost.
    const childArgs =
      mode === "inherit-all"
        ? ["-p", CHILD_TASK]
        : ["-p", "--no-session", "-ne", "-ns", "-nc", "-na", CHILD_TASK];
    const { command, args } = piInvocation(childArgs);

    const child = spawn(command, args, {
      cwd: (ctx as { cwd?: string }).cwd || process.cwd(),
      shell: false,
      detached: true,
      stdio: mode === "detached-ignore" ? "ignore" : ["ignore", "pipe", "pipe"],
      env: { ...process.env, SPIKE_PI_CHILD: "1", PI_OFFLINE: "1" },
    });

    record({ phase: "child-spawned", pid: child.pid, mode, args: childArgs.slice(0, 8) });

    if (mode === "detached-ignore") {
      // Fully fire-and-forget: the parent can exit first, and the result can
      // never come back through this process.
      child.unref();
      record({ phase: "agent-settled-exit", mode, elapsedMs: Date.now() - t0 });
      return;
    }

    let out = "";
    child.stdout?.on("data", (d: Buffer) => {
      out += String(d);
    });
    child.on("error", (error: Error) => {
      record({ phase: "child-error", error: String(error), elapsedMs: Date.now() - t0 });
    });
    child.on("close", (code: number | null) => {
      const elapsedMs = Date.now() - t0;
      record({ phase: "child-closed", code, elapsedMs, out: out.trim().slice(0, 400) });

      // Channel A — persisted state, NOT model-visible.
      pi.appendEntry("spike-bg-result", { code, elapsedMs, out: out.trim() });
      // Channel B — model-visible on the next user prompt.
      pi.sendMessage(
        {
          customType: "spike-bg-result",
          content: `[spike] background pi child exited ${code} in ${elapsedMs}ms:\n${out.trim()}`,
          display: true,
        },
        { deliverAs: "nextTurn" },
      );
      record({ phase: "injected", channels: ["appendEntry", "sendMessage:nextTurn"] });
    });

    // Not unref'd: keeping the handle is what lets `close` fire, which is the
    // only way the result reaches the parent session.
    record({ phase: "agent-settled-exit", mode, elapsedMs: Date.now() - t0 });
  });

  pi.on("session_shutdown", () => {
    record({ phase: "session-shutdown" });
  });
}
