/**
 * The Claude-shaped half of the runner: tool-name translation, matcher
 * evaluation, the subprocess calling convention, and the decision protocol.
 *
 * Ported from `@davidallada/dsh-claude-bridge` (lib/index.js: matchesMatcher
 * :1600, toolNamesOf :1596, toolInputFor :1818, applyUpdatedInput :1850,
 * expandHookPlaceholders :1882, runHook :1914, decide :2005, parseDecision
 * :2038), trimmed to what ../../../hook-contract/README.md requires: no `if`
 * subcommand filter, no trust gate, no plugin-data placeholder.
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";

/**
 * The first script path a command names that does not exist.
 *
 * A missing handler script is a FAILED handler (the contract's "fail open and
 * loud"), but the shell cannot say so: `python3 /gone.py` exits 2, which is
 * also the contract's BLOCK code, so trusting the exit status alone turns a
 * module's packaging mistake into a deny nobody can explain. Only absolute
 * paths with a script extension are checked — everything else (interpreters on
 * PATH, `-c` programs, flags) is left to the shell.
 */
export function missingScript(command) {
  const tokens = String(command).match(/"[^"]+"|'[^']+'|\S+/g) ?? [];
  for (const raw of tokens) {
    const token = raw.replace(/^["']|["']$/g, "");
    if (!token.startsWith("/") || !/\.(py|sh|bash|js|mjs|cjs|ts|rb|pl)$/.test(token)) continue;
    if (!existsSync(token)) return token;
  }
  return null;
}

/** dsh tool name → Claude tool name (hook-contract README, "Tool-name translation"). */
const TOOL_NAMES = { bash: "Bash", read: "Read", write: "Write", edit: "Edit", glob: "Glob", grep: "Grep" };

/** Contract default when a handler declares no `timeout`. */
export const DEFAULT_TIMEOUT_MS = 60_000;

export function toolNamesOf(dshName) {
  return { dsh: dshName, claude: TOOL_NAMES[dshName] ?? dshName };
}

/**
 * `matcher` is a regex over the Claude tool name; omitted or `""` matches
 * everything. A plain name list is compared literally so `Bash` cannot match
 * `BashOutput` by accident, which an unanchored regex would.
 */
export function matchesMatcher(matcher, names) {
  if (matcher === undefined || matcher === null || matcher === "" || matcher === "*") return true;
  if (typeof matcher !== "string") return false;
  if (/^[A-Za-z0-9_\- ,|]+$/.test(matcher)) {
    return matcher
      .split(/[|,]/)
      .map((s) => s.trim())
      .filter(Boolean)
      .some((m) => m === names.claude || m === names.dsh);
  }
  try {
    const re = new RegExp(matcher);
    return re.test(names.claude) || re.test(names.dsh);
  } catch {
    return false;
  }
}

/**
 * dsh call arguments → the Claude `tool_input` shape a hook expects
 * (hook-contract README: `Bash → {command}`, `Read → {file_path}`, …). dsh's
 * fs tools name their path argument `path`; Claude's name it `file_path`.
 * An unknown tool's arguments pass through verbatim — the contract matches it
 * under its own name, so its input shape is its own too.
 */
export function toolInputFor(dshName, args) {
  const a = args && typeof args === "object" ? args : {};
  if (dshName === "bash") return { command: typeof a.command === "string" ? a.command : "" };
  const fp = typeof a.file_path === "string" ? a.file_path : typeof a.path === "string" ? a.path : null;
  if (dshName === "read") {
    const base = { file_path: fp ?? "" };
    if (typeof a.offset === "number") base.offset = a.offset;
    if (typeof a.limit === "number") base.limit = a.limit;
    return base;
  }
  if (dshName === "write") {
    const base = { file_path: fp ?? "" };
    if (typeof a.content === "string") base.content = a.content;
    return base;
  }
  if (dshName === "edit") {
    const base = { file_path: fp ?? "" };
    if (typeof a.old_string === "string") base.old_string = a.old_string;
    if (typeof a.new_string === "string") base.new_string = a.new_string;
    return base;
  }
  if (dshName === "glob" || dshName === "grep") {
    const base = {};
    if (typeof a.pattern === "string") base.pattern = a.pattern;
    if (fp !== null) base.path = fp;
    return base;
  }
  return { ...a };
}

/** The inverse of {@link toolInputFor}: a Claude `updatedInput` back in dsh's argument spelling. */
export function nativeArgsFor(dshName, updatedInput) {
  const u = updatedInput && typeof updatedInput === "object" ? updatedInput : {};
  const merged = u.tool_input && typeof u.tool_input === "object" ? u.tool_input : u;
  if (dshName === "bash") return { command: merged.command };
  const out = { ...merged };
  if (typeof out.file_path === "string" && dshName !== "read" && dshName !== "write" && dshName !== "edit") return out;
  if (typeof out.file_path === "string") {
    out.path = out.file_path;
    delete out.file_path;
  }
  return out;
}

/**
 * Apply a hook's `updatedInput` in place — possible only if this dsh does not
 * freeze the arguments. dsh 0.1.1 does (`@deepseek-ai/dsh-tools` lib/index.js
 * :3047 `arguments: deepFreeze(detached)`, before the `tools/pre-execute`
 * waterfall at :3105), so this returns `false` there and the caller denies with
 * the intended input in the reason. The check stays because a later dsh that
 * grows a rewrite channel makes the seam full-fidelity for free.
 */
export function applyUpdatedInput(exec, updatedInput, dshName) {
  try {
    if (!exec || typeof exec !== "object" || Object.isFrozen(exec.arguments)) return false;
    const native = nativeArgsFor(dshName, updatedInput);
    let changed = false;
    for (const [key, value] of Object.entries(native)) {
      if (value === undefined) continue;
      exec.arguments[key] = value;
      changed = true;
    }
    return changed;
  } catch {
    return false;
  }
}

/** The two portable placeholders (hook-contract README, "Manifest"). */
export function expandHookPlaceholders(value, projectDir, pluginRoot) {
  return String(value)
    .replace(/\$\{CLAUDE_PROJECT_DIR\}/g, projectDir)
    .replace(/\$CLAUDE_PROJECT_DIR\b/g, projectDir)
    .replace(/\$\{CLAUDE_PLUGIN_ROOT\}/g, pluginRoot)
    .replace(/\$CLAUDE_PLUGIN_ROOT\b/g, pluginRoot);
}

/**
 * SIGKILL the abandoned handler's whole process group. Killing the pid alone
 * leaves anything it backgrounded running forever, unattributable; handlers are
 * therefore spawned `detached` so the negated pid reaches every descendant.
 */
function killGroup(child) {
  try {
    process.kill(-child.pid, "SIGKILL");
  } catch {
    try {
      child.kill("SIGKILL");
    } catch {
      /* already gone */
    }
  }
}

/**
 * Run one `"type": "command"` handler under the contract's process convention:
 * event JSON on stdin, decision on exit code + stdout. Never throws — a crash,
 * a timeout, or a missing script resolves to a verdict carrying `warn: true`,
 * which is the caller's cue to fail open and loud.
 *
 * @returns a verdict, or `undefined` when the run was abandoned (caller aborted).
 */
export function runHook(handler, projectDir, stdin, signal) {
  return new Promise((resolveVerdict) => {
    const timeoutMs = Math.max(250, handler.timeoutMs ?? DEFAULT_TIMEOUT_MS);
    let settled = false;
    let timer = null;
    let onAbort = null;
    const finish = (verdict) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      if (signal && onAbort) signal.removeEventListener("abort", onAbort);
      resolveVerdict(verdict);
    };
    let child;
    try {
      const env = { ...process.env, CLAUDE_PROJECT_DIR: projectDir, CLAUDE_PLUGIN_ROOT: handler.pluginRoot };
      const command = expandHookPlaceholders(handler.command, projectDir, handler.pluginRoot);
      const missing = missingScript(command);
      if (missing !== null) {
        finish({ decision: "allow", warn: true, error: `handler script ${missing} does not exist` });
        return;
      }
      child = spawn("bash", ["-c", command], {
        cwd: projectDir,
        env,
        detached: true,
        stdio: ["pipe", "pipe", "pipe"],
      });
    } catch (error) {
      finish({ decision: "allow", warn: true, error: String(error) });
      return;
    }
    let stdout = "";
    let stderr = "";
    // A handler may exit without reading stdin; the resulting EPIPE must never
    // become an unhandled 'error' event (that would take the harness down).
    child.stdin.on("error", () => {});
    try {
      child.stdin.write(JSON.stringify(stdin));
      child.stdin.end();
    } catch {
      /* EPIPE — the handler exited before consuming stdin */
    }
    child.stdout.on("data", (d) => {
      stdout += d;
    });
    child.stderr.on("data", (d) => {
      stderr += d;
    });
    child.on("error", (error) => finish({ decision: "allow", warn: true, error: String(error) }));
    child.on("close", (code) => finish(decide(code ?? 0, stdout, stderr)));
    timer = setTimeout(() => {
      killGroup(child);
      finish({ decision: "allow", warn: true, error: `timed out after ${timeoutMs}ms` });
    }, timeoutMs);
    if (signal) {
      if (signal.aborted) {
        killGroup(child);
        finish(undefined);
        return;
      }
      onAbort = () => {
        killGroup(child);
        finish(undefined);
      };
      signal.addEventListener("abort", onAbort, { once: true });
    }
  });
}

/**
 * The contract's decision protocol: exit 2 blocks with stderr as the reason;
 * exit 0 proceeds and a parsable stdout object may still decide; any other exit
 * is a FAILED handler — allow, but loudly.
 */
export function decide(code, stdout, stderr) {
  const text = String(stdout ?? "").trim();
  const parsed = text.startsWith("{") ? parseDecision(text) : { valid: false };
  const stderrReason = String(stderr ?? "").trim() || null;
  if (code === 2) {
    const reason = parsed.valid && parsed.reason ? parsed.reason : (stderrReason ?? "blocked by hook");
    return { decision: "deny", reason };
  }
  if (parsed.valid) {
    if (parsed.decision === "deny" || parsed.decision === "block") {
      return { decision: "deny", reason: parsed.reason ?? "blocked by hook" };
    }
    if (parsed.decision === "ask") {
      return { decision: "deny", reason: `hook requested human approval: ${parsed.reason ?? "no reason given"}` };
    }
    return {
      decision: "allow",
      warn: code !== 0,
      updatedInput: parsed.updatedInput ?? null,
      additionalContext: parsed.additionalContext ?? null,
      error: code === 0 ? undefined : `exited ${code}`,
    };
  }
  if (code === 0) return { decision: "allow", warn: false };
  return { decision: "allow", warn: true, error: `exited ${code}${stderrReason ? `: ${stderrReason}` : ""}` };
}

/** Parse a decision object in either nesting (top level or `hookSpecificOutput`). */
export function parseDecision(text) {
  let obj;
  try {
    obj = JSON.parse(text);
  } catch {
    return { valid: false };
  }
  if (obj === null || typeof obj !== "object") return { valid: false };
  const hs = obj.hookSpecificOutput && typeof obj.hookSpecificOutput === "object" ? obj.hookSpecificOutput : {};
  const str = (v) => (typeof v === "string" && v ? v : null);
  const permissionDecision = obj.permissionDecision ?? hs.permissionDecision;
  const additionalContext = str(obj.additionalContext ?? hs.additionalContext);
  const updatedInput = obj.updatedInput ?? hs.updatedInput ?? null;
  if (permissionDecision === undefined) {
    // The Stop event's channel, and Claude's deprecated top-level form, which
    // Claude still blocks on: reading it as "no decision" turns a deny into a
    // silent allow.
    const legacy = obj.decision ?? hs.decision;
    if (legacy === "block") {
      return { valid: true, decision: "deny", reason: str(obj.reason ?? hs.reason), updatedInput: null, additionalContext };
    }
    if (additionalContext !== null || updatedInput !== null) {
      return { valid: true, decision: "allow", reason: null, updatedInput, additionalContext };
    }
    return { valid: false };
  }
  return {
    valid: true,
    decision: String(permissionDecision),
    reason: str(obj.permissionDecisionReason ?? hs.permissionDecisionReason),
    updatedInput,
    additionalContext,
  };
}
