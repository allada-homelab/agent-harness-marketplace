/**
 * @allada-homelab/hook-runner-dsh — run a module's Claude-shaped
 * `hooks/hooks.json` on the DeepSeek Harness.
 *
 * A marketplace module ships ONE manifest (see ../../../hook-contract/README.md)
 * and Claude Code reads it natively. This plugin is the dsh half: it finds every
 * installed module's manifest and maps each Claude event onto dsh's own seam.
 *
 *   SessionStart     → `session/created`      → a `systemPrompt.context` entry
 *   UserPromptSubmit → `agent/pre-step`       → a `systemPrompt.context` entry
 *   PreToolUse       → `tools/pre-execute`    → allow / deny
 *   PostToolUse      → `tools/post-execute`   → `additionalContexts`
 *   Stop             → `agent/turn-stopping`  → `agent.steer(reason)`
 *
 * Two fidelity notes, both forced by the runtime and both in the README:
 *
 *   - PreToolUse cannot REWRITE. `PreToolDecision` has no rewrite variant
 *     (`@deepseek-ai/dsh-tools` lib/types/index.d.ts:418) and `exec.arguments`
 *     is deep-frozen before the waterfall (lib/index.js:3047, waterfall :3105),
 *     so a hook's `updatedInput` becomes a DENY whose reason states the input
 *     the hook wanted. The model can re-issue it; running the original command
 *     instead would silently discard the hook's intent.
 *   - Context injection is text on the model-facing surface, not a Claude
 *     "additionalContext" field, because that is the only channel dsh has.
 *
 * Failure posture, from the contract: a handler that crashes, times out, or
 * does not exist FAILS OPEN AND LOUD — the action proceeds and exactly one line
 * containing `hook-runner` goes to `process.stderr`. `ctx.logger` is not used
 * for those lines: it does not reach the journal a user reads after the fact.
 */
import { randomUUID } from "node:crypto";
import {
  DEFAULT_TIMEOUT_MS,
  applyUpdatedInput,
  matchesMatcher,
  nativeArgsFor,
  runHook,
  toolInputFor,
  toolNamesOf,
} from "./hooks.js";
import { collectHandlers, findProfileDir, loadManifests, selfDir } from "./manifests.js";

const PLUGIN = "hook-runner-dsh";

/** One line, on the stream a user can actually read after the session ended. */
function stderrWarn(message) {
  try {
    process.stderr.write(`${PLUGIN}: ${message}\n`);
  } catch {
    /* a closed stderr must not take the harness down */
  }
}

/** A user-role message in dsh's shape, built without importing a dsh internal. */
function pluginMessage(text, summary) {
  return Object.freeze({
    id: randomUUID(),
    role: "user",
    content: [{ type: "text", text }],
    source: { kind: "plugin", plugin: PLUGIN, form: "notice", summary: summary.slice(0, 120) },
  });
}

/**
 * What the contract puts in `tool_response`: the tool's text output as a
 * string, else the NATIVE result serialized as JSON. Handing a hook the raw
 * object instead would make the field's type depend on the tool — a hook that
 * does `.strip()` on a `grep` response but not on a `glob` one is a hook the
 * contract cannot describe.
 */
export function toolResponseFor(result) {
  if (typeof result === "string") return result;
  if (result === null || result === undefined) return "";
  if (Array.isArray(result?.content)) {
    const text = result.content
      .filter((b) => b?.type === "text" && typeof b.text === "string")
      .map((b) => b.text)
      .join("");
    if (text) return text;
  }
  if (typeof result?.value === "string") return result.value;
  try {
    return JSON.stringify(result) ?? "";
  } catch {
    return String(result);
  }
}

/** The newest human prompt among the messages entering a step, if any. */
export function latestPrompt(messages) {
  for (let i = (messages?.length ?? 0) - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (message?.source?.kind !== "user") continue;
    const text = (message.content ?? [])
      .filter((b) => b?.type === "text" && typeof b.text === "string")
      .map((b) => b.text)
      .join("");
    if (text) return text;
  }
  return null;
}

/**
 * Register every seam.
 *
 * @param ctx - the cordis context.
 * @param config - `{ manifests: [] }`; see ../README.md.
 */
export function apply(ctx, config = {}) {
  const warn = stderrWarn;
  const profileDir = config.profileDir ?? findProfileDir(selfDir);
  const loaded = loadManifests({ manifests: config.manifests ?? [], profileDir, warn });

  // One state record per session, delivered per session.
  //
  // `AssembleContext.scope` (@deepseek-ai/dsh-system-prompt
  // lib/types/index.d.ts:37) is an opaque `ScopeKey`, but dsh-agent mints the
  // agent itself as its own key (`scope: agent`, @deepseek-ai/dsh-agent
  // lib/index.js:387, carrier `scopeTarget(agent, agent)` :324) and an agent's
  // id IS its session id (`agent.id !== agent.session.id` throws, :603). So the
  // assembly names its session, and the `agent/pre-step` payload's agent names
  // the same one — two interleaved sessions cannot read each other's context.
  // `latest` remains only as the fallback for an assembly with no usable scope.
  const states = new Map();
  let latest = null;
  const stateFor = (session) => {
    const key = session?.id ?? "default";
    let state = states.get(key);
    if (!state) {
      state = { cwd: session?.header?.cwd ?? process.cwd(), sessionId: String(key), sessionStart: null, sessionStartText: "", promptText: "", stopActive: false };
      states.set(key, state);
    }
    latest = state;
    return state;
  };

  const handlersFor = (event, names) => collectHandlers(loaded, event, names, warn, matchesMatcher);

  const baseStdin = (state, event) => ({ session_id: state.sessionId, cwd: state.cwd, hook_event_name: event });

  /**
   * Run one event's handlers in order. Returns the first deny, else the
   * concatenated `additionalContext`, else null. A failed handler is one loud
   * line and the run continues — fail open.
   */
  async function runHandlers(handlers, state, stdin, signal, onRewrite) {
    const contexts = [];
    for (const handler of handlers) {
      const verdict = await runHook(handler, state.cwd, stdin, signal);
      if (verdict === undefined) return { deny: null, context: null };
      if (verdict.warn) {
        warn(`${stdin.hook_event_name} handler ${JSON.stringify(handler.command)} failed (${verdict.error ?? "unknown"}); proceeding without it`);
      }
      if (verdict.decision === "deny") return { deny: verdict.reason, context: null };
      if (verdict.updatedInput && onRewrite) {
        const deny = onRewrite(verdict.updatedInput);
        if (deny) return { deny, context: null };
      }
      if (verdict.additionalContext) contexts.push(verdict.additionalContext);
    }
    return { deny: null, context: contexts.length ? contexts.join("\n") : null };
  }

  /* ── SessionStart ─────────────────────────────────────────────────────── */
  ctx.on("session/created", (session) => {
    const state = stateFor(session);
    const handlers = handlersFor("SessionStart", null);
    if (!handlers.length) return;
    const stdin = { ...baseStdin(state, "SessionStart"), source: "startup" };
    // `session/created` is a synchronous emit, so the run cannot be awaited
    // here. `agent/pre-step` awaits this promise before the first assembly,
    // which is what keeps the text from missing its own session.
    state.sessionStart = runHandlers(handlers, state, stdin, undefined).then(({ context }) => {
      if (context) state.sessionStartText = context;
    });
  });

  /* ── UserPromptSubmit ─────────────────────────────────────────────────── */
  // `agent/pre-step` is the awaited waterfall carrying the messages claimed for
  // the step (@deepseek-ai/dsh-agent lib/types/runtime-types.d.ts:235), so the
  // handlers finish BEFORE the assembly that must show their text. The
  // `systemPrompt.context` provider below is then a pure read.
  // Bound the per-session state: dsh emits `session/disposed` (dsh-session
  // lib/types/index.d.ts:54) when a session is torn down.
  ctx.on("session/disposed", (session) => {
    const key = session?.id ?? "default";
    if (states.get(key) === latest) latest = null;
    states.delete(key);
  });

  ctx.on("agent/pre-step", async (payload, next) => {
    const state = stateFor(payload?.agent?.session);
    try {
      if (state.sessionStart) await state.sessionStart;
      const prompt = latestPrompt(payload?.messages);
      const handlers = prompt === null ? [] : handlersFor("UserPromptSubmit", null);
      if (handlers.length) {
        const stdin = { ...baseStdin(state, "UserPromptSubmit"), prompt };
        const { context } = await runHandlers(handlers, state, stdin, payload?.signal);
        state.promptText = context ?? "";
      }
    } catch (error) {
      warn(`UserPromptSubmit seam failed (${error}); the step proceeds without hook context`);
    }
    return next();
  });

  /** The session an assembly belongs to, read off its scope key; null if unreadable. */
  const assemblySessionId = (assembleContext) => {
    const scope = assembleContext?.scope;
    const id = scope?.session?.id ?? scope?.id;
    return typeof id === "string" && id ? id : null;
  };

  // Once per process, not once per assembly: an unscoped assembly recurs every
  // turn, and a line per turn would bury the loud lines that matter.
  let warnedUnscoped = false;

  /** Deliver one state field to the assembly that owns it. */
  const deliver = (field) => (assembleContext) => {
    const key = assemblySessionId(assembleContext);
    if (key !== null) return states.get(key)?.[field] ?? "";
    if (!warnedUnscoped) {
      warnedUnscoped = true;
      warn("a prompt assembly carried no readable session scope; hook context falls back to the most recent session, which can cross sessions");
    }
    return latest?.[field] ?? "";
  };

  ctx.systemPrompt?.context({
    name: `${PLUGIN}:session-start`,
    order: 90,
    text: deliver("sessionStartText"),
  });
  ctx.systemPrompt?.context({
    name: `${PLUGIN}:user-prompt-submit`,
    order: 91,
    text: deliver("promptText"),
  });

  /* ── PreToolUse ───────────────────────────────────────────────────────── */
  ctx.on("tools/pre-execute", async (exec, next) => {
    const names = toolNamesOf(exec?.name);
    const handlers = handlersFor("PreToolUse", names);
    if (!handlers.length) return next();
    const state = stateFor(exec?.agent?.session);
    const stdin = {
      ...baseStdin(state, "PreToolUse"),
      tool_name: names.claude,
      tool_input: toolInputFor(names.dsh, exec?.arguments),
    };
    const onRewrite = (updatedInput) => {
      if (applyUpdatedInput(exec, updatedInput, names.dsh)) return null;
      return `PreToolUse hook rewrote this call; dsh cannot apply a rewrite, so re-issue it as: ${JSON.stringify(nativeArgsFor(names.dsh, updatedInput))}`;
    };
    const { deny } = await runHandlers(handlers, state, stdin, exec?.signal, onRewrite);
    if (deny) return { kind: "deny", reason: deny };
    return next();
  });

  /* ── PostToolUse ──────────────────────────────────────────────────────── */
  ctx.on("tools/post-execute", async (exec, result, next) => {
    const decision = await next();
    const names = toolNamesOf(exec?.name);
    const handlers = handlersFor("PostToolUse", names);
    if (!handlers.length) return decision;
    const state = stateFor(exec?.agent?.session);
    const stdin = {
      ...baseStdin(state, "PostToolUse"),
      tool_name: names.claude,
      tool_input: toolInputFor(names.dsh, exec?.arguments),
      tool_response: toolResponseFor(result),
    };
    const { context } = await runHandlers(handlers, state, stdin, exec?.signal);
    if (!context) return decision;
    // `additionalContexts` is the seam's own channel for exactly this
    // (@deepseek-ai/dsh-tools lib/types/index.d.ts:435).
    return {
      ...decision,
      additionalContexts: [...(decision?.additionalContexts ?? []), pluginMessage(context, `${names.claude} PostToolUse hook context`)],
    };
  });

  /* ── Stop ─────────────────────────────────────────────────────────────── */
  ctx.on("agent/turn-stopping", async (payload) => {
    const agent = payload?.agent;
    const state = stateFor(agent?.session);
    const handlers = handlersFor("Stop", null);
    if (!handlers.length) return;
    const stdin = { ...baseStdin(state, "Stop"), stop_hook_active: state.stopActive === true };
    const { deny } = await runHandlers(handlers, state, stdin, payload?.signal);
    if (!deny) {
      state.stopActive = false;
      return;
    }
    // Steering is what makes the block real: the machine re-reads its inbox and
    // runs another step instead of closing the turn
    // (@deepseek-ai/dsh-agent lib/types/runtime-types.d.ts:285-301).
    state.stopActive = true;
    try {
      agent.steer(pluginMessage(deny, "Stop hook requires another turn"));
    } catch (error) {
      warn(`Stop hook wanted another turn but steering failed (${error}); the turn ends: ${deny}`);
    }
  });
}

export const name = PLUGIN;
// cordis throws on any `ctx.<service>` a plugin did not declare — `?.` cannot
// guard the ACCESS, only the result — so without this the plugin never loads.
export const inject = ['systemPrompt'];
