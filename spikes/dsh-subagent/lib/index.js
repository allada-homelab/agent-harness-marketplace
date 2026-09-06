/**
 * MEASUREMENT SPIKE — dispatch a ONE-SHOT dsh subagent from a plugin listener.
 *
 * Question this answers for the okf-wiki design: can a plugin run background
 * agent work after a turn ends, and does the parent turn pay for it?
 *
 * Seam choice. `agent/turn-stopping` is the only turn-boundary event a plugin
 * can listen on: it is dispatched with `await this.dispatch.serial(...)`
 * (@deepseek-ai/dsh-agent-loop lib/index.js:565). `turn/end` is NOT a cordis
 * event — it is a session-log append (same file, :592) folded by the session
 * reducer (@deepseek-ai/dsh-agent lib/index.js:238), so `ctx.on('turn/end')`
 * never fires. The payload carries `{ turn, signal }` plus the scoped `agent`
 * that hook-runner-dsh already relies on (modules/hook-runner-dsh/lib/index.js:278).
 *
 * Dispatch API. `ctx.subagents` is the capability seam
 * (@deepseek-ai/dsh-subagent lib/types/index.d.ts:61); `start(name, request)`
 * returns a published one-shot `SubagentRun` (same file, :~250 — the `start`
 * member) whose `result` promise settles with `{ output, stopReason }`
 * (lib/types/types.d.ts, `SubagentResult`). "One-shot" means one disposable
 * foreground delegation with exactly one result and a `dispose()` the caller
 * MUST call; "continuable" (`startContinuable`) is a durable child with an
 * inbox that never becomes a `SubagentRun`. The provider name `spawn` comes
 * from @deepseek-ai/dsh-subagent-spawn-in-process lib/index.js:13 (config
 * default `providerName: 'spawn'`), which runs the child as a fresh Agent on
 * the SAME cordis context with `inheritsParentContext: false` (same file, :29).
 *
 * `maxDepth` is an optional absolute delegation-depth cap on the request
 * (lib/types/types.d.ts, `SubagentStartRequest.maxDepth`), gated by the
 * provider's `depthLimit` capability, which spawn supports.
 *
 * The four modes exist to separate the measurements:
 *   awaited   — await run.result inside the listener (does the turn block?)
 *   detached  — dispatch, return immediately, settle in the background
 *   throw     — throw inside the listener (what does the parent turn do?)
 *   off       — control run, plugin loaded but dispatches nothing
 */
import { appendFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { delegationDepthOf } from "@deepseek-ai/dsh-subagent";

export const name = "spike-dsh-subagent";
export const inject = ["subagents"];

const PROVIDER = "spawn";
const CHILD_PROMPT =
  "Write the single word DONE to the file named done.txt in the current directory using the bash tool, then reply with exactly: DONE";

/** Append one JSON line to the spike log; timing evidence must survive the process. */
function record(outDir, event) {
  const line = JSON.stringify({ t: Date.now(), iso: new Date().toISOString(), ...event });
  try {
    if (outDir) {
      mkdirSync(dirname(join(outDir, "x")), { recursive: true });
      appendFileSync(join(outDir, "spike.jsonl"), `${line}\n`);
    }
  } catch (error) {
    process.stderr.write(`spike-dsh-subagent: log write failed (${error})\n`);
  }
  process.stderr.write(`spike-dsh-subagent ${line}\n`);
}

/** The child's final assistant text, from the canonical content-block array. */
function textOf(blocks) {
  return (Array.isArray(blocks) ? blocks : [])
    .filter((b) => b?.type === "text" && typeof b.text === "string")
    .map((b) => b.text)
    .join("");
}

export function apply(ctx, config) {
  const outDir = config?.outDir || process.env.SPIKE_OUT_DIR || "";
  const mode = config?.mode || process.env.SPIKE_MODE || "detached";
  record(outDir, { phase: "plugin-applied", mode, providers: ctx.subagents.list() });

  ctx.on("agent/turn-stopping", async (payload) => {
    const turn = payload?.turn;
    // MANDATORY. The root plugin context carries no scope filter, so this same
    // listener fires for the CHILD's turn-stopping too; without the guard the
    // child dispatches a grandchild forever. depth 0 == top-level
    // (@deepseek-ai/dsh-subagent lib/types/depth.js:18).
    const depth = delegationDepthOf(payload.agent);
    if (depth > 0) {
      record(outDir, { phase: "recursion-guard-hit", turn, depth });
      return;
    }
    record(outDir, { phase: "turn-stopping-enter", turn, mode, depth });

    if (mode === "off") {
      record(outDir, { phase: "turn-stopping-exit", turn, mode });
      return;
    }
    if (mode === "throw") {
      record(outDir, { phase: "about-to-throw", turn });
      throw new Error("spike: deliberate throw inside agent/turn-stopping");
    }

    // A detached background dispatch must NOT ride the turn's signal: that
    // signal is aborted as the turn tears down. Own the cancellation instead.
    const controller = new AbortController();
    const request = {
      label: "spike-child",
      prompt: [{ type: "text", text: CHILD_PROMPT }],
      parent: payload.agent,
      signal: mode === "awaited" ? payload.signal : controller.signal,
      maxDepth: 1,
    };

    const dispatchedAt = Date.now();
    const settle = (async () => {
      const run = await ctx.subagents.start(PROVIDER, request);
      record(outDir, { phase: "child-published", turn, childSession: String(run.id), local: run.localAgent !== undefined });
      try {
        const result = await run.result;
        // Usage is NOT on SubagentResult. It lives on the child's own session
        // log as `assistant/message` events (@deepseek-ai/dsh-session
        // lib/types/types.d.ts:279), so it must be read BEFORE dispose().
        const usage = { input: 0, output: 0, messages: 0 };
        for (const e of run.localAgent?.session?.events ?? []) {
          if (e?.type !== "assistant/message" || !e?.data?.usage) continue;
          usage.messages += 1;
          for (const [k, v] of Object.entries(e.data.usage)) {
            if (typeof v === "number") usage[k] = (usage[k] ?? 0) + v;
          }
        }
        record(outDir, {
          usage,
          phase: "child-settled",
          turn,
          childSession: String(run.id),
          stopReason: result.stopReason,
          output: textOf(result.output).slice(0, 500),
          diagnostic: result.diagnostic,
          elapsedMs: Date.now() - dispatchedAt,
        });
      } finally {
        await run.dispose();
        record(outDir, { phase: "child-disposed", turn, elapsedMs: Date.now() - dispatchedAt });
      }
    })().catch((error) => {
      record(outDir, { phase: "child-failed", turn, error: String(error), elapsedMs: Date.now() - dispatchedAt });
    });

    if (mode === "awaited") await settle;
    record(outDir, { phase: "turn-stopping-exit", turn, mode, elapsedMs: Date.now() - dispatchedAt });
  });
}
