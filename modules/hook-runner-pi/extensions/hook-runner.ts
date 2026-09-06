/**
 * hook-runner — run Claude Code `hooks/hooks.json` manifests on pi.
 *
 * A module in this marketplace ships ONE `hooks/hooks.json` in Claude Code's
 * shape. Claude reads it natively; on pi this extension reads the same file and
 * maps each event onto pi's native seam (see ../README.md and
 * hook-contract/README.md for the contract this is held to).
 *
 *   SessionStart     -> session_start        (pi.sendMessage, deliverAs nextTurn)
 *   UserPromptSubmit -> before_agent_start   (returned { message })
 *   PreToolUse       -> tool_call            ({ block } / mutate event.input)
 *   PostToolUse      -> tool_result          ({ content } with context appended)
 *   Stop             -> agent_settled        (DEGRADED: observe + sendUserMessage)
 *
 * Event-only: no registerTool, no prompt text, so it costs 0 tokens/turn.
 *
 * Fails OPEN and loud, always: a handler that crashes, times out, or does not
 * exist lets the action proceed and writes ONE line containing "hook-runner" to
 * process.stderr (plus ui.notify when a ctx is at hand). A hook runner that
 * wedges the tool loop is worse than the hook it failed to run.
 *
 * Self-contained on purpose: nothing outside node builtins and pi's own types.
 */

import { spawn } from "node:child_process";
import { existsSync, readdirSync, readFileSync, realpathSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/* ── manifest model ───────────────────────────────────────────────────────── */

export interface HookHandler {
	type?: string;
	command?: string;
	timeout?: number;
}
export interface HookMatcherGroup {
	matcher?: string;
	hooks?: HookHandler[];
}
export interface HookManifest {
	/** Directory that owns the manifest — `${CLAUDE_PLUGIN_ROOT}`. */
	pluginRoot: string;
	hooks: Record<string, HookMatcherGroup[]>;
}

const DEFAULT_TIMEOUT_S = 60;

/** One line, one channel, every time. Never throws. */
export function warn(message: string, ctx?: any): void {
	const line = `[hook-runner] ${message}`;
	try {
		process.stderr.write(`${line}\n`);
	} catch {
		/* ignore */
	}
	try {
		ctx?.ui?.notify?.(line, "warning");
	} catch {
		/* ignore */
	}
}

/* ── discovery ────────────────────────────────────────────────────────────── */

/**
 * Where manifests come from, and deliberately where they do not.
 *
 * (a) Sibling modules of this extension. This file lives at
 *     `<repo>/modules/hook-runner-pi/extensions/hook-runner.ts`, so the sibling
 *     modules are `<repo>/modules/<name>/hooks/hooks.json`. Resolving from our
 *     own location means the runner works from any install root pi chose
 *     (`~/.pi/agent/git/...`, a local path install, a worktree) without reading
 *     settings.
 * (b) `$PI_HOOK_MANIFESTS`, colon-separated, each entry either a hooks.json
 *     path or a module directory containing `hooks/hooks.json`. This is the
 *     dotfiles/fleet path, where the modules are not siblings.
 *
 * NOT loaded: `<cwd>/.claude/hooks.json`. Project-local hooks are attacker-
 * controlled by anyone who can open a PR against a repo you clone; Claude gates
 * them behind its own trust prompt and pi has no equivalent surface here.
 */
export function manifestPaths(selfFile: string, env: NodeJS.ProcessEnv = process.env): string[] {
	const found: string[] = [];
	const seen = new Set<string>();
	const add = (p: string) => {
		if (!p || !existsSync(p)) return;
		let key = p;
		try {
			key = realpathSync(p);
		} catch {
			/* keep the literal path */
		}
		if (seen.has(key)) return;
		seen.add(key);
		found.push(p);
	};

	const modulesDir = resolve(dirname(selfFile), "..", "..");
	let entries: string[] = [];
	try {
		entries = readdirSync(modulesDir);
	} catch {
		entries = [];
	}
	for (const name of entries.sort()) {
		const candidate = join(modulesDir, name, "hooks", "hooks.json");
		if (existsSync(candidate)) add(candidate);
	}

	for (const raw of (env.PI_HOOK_MANIFESTS ?? "").split(":")) {
		const entry = raw.trim();
		if (!entry) continue;
		let candidate = entry;
		try {
			if (statSync(entry).isDirectory()) candidate = join(entry, "hooks", "hooks.json");
		} catch {
			continue;
		}
		add(candidate);
	}

	return found;
}

/** Read and shape-check the manifests. A bad file costs itself, not the others. */
export function loadManifests(paths: string[], onWarn: (m: string) => void = (m) => warn(m)): HookManifest[] {
	const manifests: HookManifest[] = [];
	for (const path of paths) {
		try {
			const parsed = JSON.parse(readFileSync(path, "utf-8"));
			const hooks = parsed?.hooks;
			if (!hooks || typeof hooks !== "object") {
				onWarn(`manifest has no "hooks" object, skipped: ${path}`);
				continue;
			}
			// `<module>/hooks/hooks.json` -> `<module>` is ${CLAUDE_PLUGIN_ROOT}.
			manifests.push({ pluginRoot: resolve(dirname(path), ".."), hooks });
		} catch (err) {
			onWarn(`manifest unreadable, skipped: ${path}: ${err instanceof Error ? err.message : String(err)}`);
		}
	}
	return manifests;
}

/* ── tool-name / argument translation ─────────────────────────────────────── */

const PI_TO_CLAUDE: Record<string, string> = {
	bash: "Bash",
	read: "Read",
	write: "Write",
	edit: "Edit",
	grep: "Grep",
	find: "Glob",
	glob: "Glob",
};

export function claudeToolName(piToolName: string): string {
	return PI_TO_CLAUDE[piToolName] ?? piToolName;
}

/**
 * pi's native tool args -> Claude's `tool_input` shape.
 *
 * Verified against pi 0.84.1's schemas: read/write/edit take `path` (not
 * `file_path`), write takes `content`, edit takes `edits: [{oldText, newText}]`,
 * grep/find take `pattern`/`path`. Unknown tools pass through untouched so an
 * MCP tool still reaches its hook with its real arguments.
 */
export function toClaudeInput(piToolName: string, input: any): Record<string, unknown> {
	const i = input ?? {};
	switch (piToolName) {
		case "bash":
			return { command: i.command };
		case "read":
			return { file_path: i.path };
		case "write":
			return { file_path: i.path, content: i.content };
		case "edit": {
			const first = Array.isArray(i.edits) ? (i.edits[0] ?? {}) : {};
			return { file_path: i.path, old_string: first.oldText, new_string: first.newText };
		}
		case "grep":
		case "find":
		case "glob":
			return { pattern: i.pattern, path: i.path };
		default:
			return { ...i };
	}
}

/**
 * Apply a hook's `updatedInput` (Claude shape) back onto pi's native input,
 * mutating in place because that is how pi's `tool_call` rewrite works.
 *
 * Lossy in exactly one place: Claude's Edit is a single old/new pair while pi's
 * edit carries an array, so a rewrite lands on `edits[0]`.
 */
export function applyUpdatedInput(piToolName: string, input: any, updated: Record<string, any>): void {
	if (!input || !updated) return;
	const set = (key: string, value: unknown) => {
		if (value !== undefined) input[key] = value;
	};
	switch (piToolName) {
		case "bash":
			set("command", updated.command);
			return;
		case "read":
			set("path", updated.file_path);
			return;
		case "write":
			set("path", updated.file_path);
			set("content", updated.content);
			return;
		case "edit": {
			set("path", updated.file_path);
			if (updated.old_string === undefined && updated.new_string === undefined) return;
			if (!Array.isArray(input.edits) || input.edits.length === 0) input.edits = [{}];
			if (updated.old_string !== undefined) input.edits[0].oldText = updated.old_string;
			if (updated.new_string !== undefined) input.edits[0].newText = updated.new_string;
			return;
		}
		case "grep":
		case "find":
		case "glob":
			set("pattern", updated.pattern);
			set("path", updated.path);
			return;
		default:
			for (const [k, v] of Object.entries(updated)) input[k] = v;
	}
}

/* ── the process contract ─────────────────────────────────────────────────── */

export function matches(matcher: string | undefined, claudeToolName: string): boolean {
	if (!matcher) return true;
	try {
		return new RegExp(matcher).test(claudeToolName);
	} catch {
		return false; // an uncompilable matcher matches nothing; the caller warns
	}
}

export interface HandlerOutcome {
	/** exit 2 or permissionDecision deny */
	deny?: string;
	updatedInput?: Record<string, unknown>;
	additionalContext?: string;
	/** top-level {"decision":"block"} from a Stop hook */
	stopBlockReason?: string;
	failed?: string;
}

function expand(command: string, pluginRoot: string, projectDir: string): string {
	return command
		.replaceAll("${CLAUDE_PLUGIN_ROOT}", pluginRoot)
		.replaceAll("${CLAUDE_PROJECT_DIR}", projectDir);
}

/**
 * A missing hook script must fail OPEN, but the interpreter that cannot find it
 * usually exits 2 — which is the contract's BLOCK channel. `python3 missing.py`
 * exits 2, and honoring that would turn a deleted hook into a hard denial: the
 * one failure mode "fail open" exists to prevent. So the script is checked
 * before the spawn: any absolute path with a script extension in the expanded
 * command must exist.
 *
 * Deliberately narrow — only `/…/x.<ext>` tokens are checked, so a command with
 * no script path (`grep -q foo`) is never blocked by this.
 */
const SCRIPT_PATH = /(?:^|[\s"'=])(\/[^\s"']+\.(?:py|sh|bash|js|mjs|cjs|ts|rb|pl))(?=$|[\s"'])/g;

export function missingScript(expandedCommand: string): string | undefined {
	for (const match of expandedCommand.matchAll(SCRIPT_PATH)) {
		if (!existsSync(match[1])) return match[1];
	}
	return undefined;
}

/**
 * Run one `type: "command"` handler: event JSON on stdin, exit code and stdout
 * decide the outcome. Never rejects — a failure is a value, not an exception.
 */
export function runHandler(
	handler: HookHandler,
	event: Record<string, unknown>,
	pluginRoot: string,
	projectDir: string,
): Promise<HandlerOutcome> {
	return new Promise((resolveOutcome) => {
		const command = expand(String(handler.command ?? ""), pluginRoot, projectDir);
		const timeoutMs = Math.max(1, Number(handler.timeout) > 0 ? Number(handler.timeout) : DEFAULT_TIMEOUT_S) * 1000;
		const missing = missingScript(command);
		if (missing) {
			resolveOutcome({ failed: `handler script not found, proceeding: ${missing}` });
			return;
		}
		let child: ReturnType<typeof spawn>;
		try {
			child = spawn(command, {
				shell: true,
				cwd: projectDir,
				env: { ...process.env, CLAUDE_PLUGIN_ROOT: pluginRoot, CLAUDE_PROJECT_DIR: projectDir },
				stdio: ["pipe", "pipe", "pipe"],
			});
		} catch (err) {
			resolveOutcome({ failed: `handler could not start: ${err instanceof Error ? err.message : String(err)}` });
			return;
		}

		let stdout = "";
		let stderr = "";
		let settled = false;
		const finish = (outcome: HandlerOutcome) => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			resolveOutcome(outcome);
		};
		const timer = setTimeout(() => {
			try {
				child.kill("SIGKILL");
			} catch {
				/* ignore */
			}
			finish({ failed: `handler timed out after ${timeoutMs / 1000}s: ${command}` });
		}, timeoutMs);

		child.stdout?.on("data", (d) => {
			stdout += String(d);
		});
		child.stderr?.on("data", (d) => {
			stderr += String(d);
		});
		child.on("error", (err) => finish({ failed: `handler could not run: ${err.message}` }));
		child.on("close", (code) => {
			if (code === 0) {
				finish(parseStdout(stdout));
				return;
			}
			if (code === 2) {
				finish({ deny: stderr.trim() || `blocked by hook: ${command}` });
				return;
			}
			finish({ failed: `handler exited ${code}: ${command}: ${stderr.trim().split("\n").pop() ?? ""}` });
		});

		try {
			child.stdin?.end(JSON.stringify(event));
		} catch (err) {
			finish({ failed: `handler stdin failed: ${err instanceof Error ? err.message : String(err)}` });
		}
	});
}

/** Exit 0: honor `hookSpecificOutput` and a top-level Stop decision; ignore the rest. */
export function parseStdout(stdout: string): HandlerOutcome {
	const text = stdout.trim();
	if (!text) return {};
	let parsed: any;
	try {
		parsed = JSON.parse(text);
	} catch {
		return {}; // "any other text is ignored"
	}
	if (!parsed || typeof parsed !== "object") return {};
	const outcome: HandlerOutcome = {};
	if (parsed.decision === "block" && typeof parsed.reason === "string") outcome.stopBlockReason = parsed.reason;
	const specific = parsed.hookSpecificOutput;
	if (specific && typeof specific === "object") {
		if (specific.permissionDecision === "deny") {
			outcome.deny = String(specific.permissionDecisionReason ?? "blocked by hook");
		}
		if (specific.updatedInput && typeof specific.updatedInput === "object") outcome.updatedInput = specific.updatedInput;
		if (typeof specific.additionalContext === "string") outcome.additionalContext = specific.additionalContext;
	}
	return outcome;
}

/** All `type: "command"` handlers for one event, in manifest then declaration order. */
export function selectHandlers(
	manifests: HookManifest[],
	eventName: string,
	toolName: string | undefined,
	onWarn: (m: string) => void,
): Array<{ handler: HookHandler; pluginRoot: string }> {
	const selected: Array<{ handler: HookHandler; pluginRoot: string }> = [];
	for (const manifest of manifests) {
		for (const group of manifest.hooks[eventName] ?? []) {
			if (toolName !== undefined && !matches(group.matcher, toolName)) continue;
			for (const handler of group.hooks ?? []) {
				if (handler.type !== "command" || !handler.command) {
					onWarn(`skipping non-command handler (type=${handler.type ?? "?"}) in ${manifest.pluginRoot}`);
					continue;
				}
				selected.push({ handler, pluginRoot: manifest.pluginRoot });
			}
		}
	}
	return selected;
}

/* ── wiring ───────────────────────────────────────────────────────────────── */

function selfFile(): string {
	try {
		if (typeof import.meta !== "undefined" && import.meta.url) return fileURLToPath(import.meta.url);
	} catch {
		/* fall through */
	}
	const cjs = (globalThis as any).__filename;
	return typeof cjs === "string" ? cjs : process.cwd();
}

export default function (pi: ExtensionAPI): void {
	const projectDir = process.cwd();
	const paths = manifestPaths(selfFile());
	const manifests = loadManifests(paths);
	const sessionId = `pi-${process.pid}-${Date.now()}`;
	/**
	 * Latched for the session once a Stop hook has forced a follow-up. Claude
	 * resets this per user prompt; pi's own follow-up would look like a new
	 * prompt here, so latching is the loop-safe reading of the same flag.
	 */
	let stopHookActive = false;

	const base = (eventName: string) => ({ session_id: sessionId, cwd: projectDir, hook_event_name: eventName });

	/** Run every selected handler; returns the outcomes, warning about failures. */
	const runAll = async (
		eventName: string,
		toolName: string | undefined,
		payload: Record<string, unknown>,
		ctx: any,
		stopEarly?: (o: HandlerOutcome) => boolean,
	): Promise<HandlerOutcome[]> => {
		const outcomes: HandlerOutcome[] = [];
		for (const { handler, pluginRoot } of selectHandlers(manifests, eventName, toolName, (m) => warn(m, ctx))) {
			const outcome = await runHandler(handler, { ...base(eventName), ...payload }, pluginRoot, projectDir);
			if (outcome.failed) warn(outcome.failed, ctx);
			outcomes.push(outcome);
			if (stopEarly?.(outcome)) break;
		}
		return outcomes;
	};

	const contextFrom = (outcomes: HandlerOutcome[]): string =>
		outcomes
			.map((o) => o.additionalContext)
			.filter((c): c is string => typeof c === "string" && c.length > 0)
			.join("\n");

	pi.on("session_start", async (_event: any, ctx: any) => {
		try {
			const context = contextFrom(await runAll("SessionStart", undefined, { source: "startup" }, ctx));
			if (context) {
				// nextTurn: the context belongs to the first prompt, and a session
				// start must never trigger a turn on its own.
				pi.sendMessage({ customType: "hook-runner", content: context, display: true }, { deliverAs: "nextTurn" });
			}
		} catch (err) {
			warn(`session_start failed open: ${err instanceof Error ? err.message : String(err)}`, ctx);
		}
	});

	pi.on("before_agent_start", async (event: any, ctx: any) => {
		try {
			const context = contextFrom(await runAll("UserPromptSubmit", undefined, { prompt: event?.prompt ?? "" }, ctx));
			if (!context) return;
			return { message: { customType: "hook-runner", content: context, display: true } };
		} catch (err) {
			warn(`before_agent_start failed open: ${err instanceof Error ? err.message : String(err)}`, ctx);
			return;
		}
	});

	pi.on("tool_call", async (event: any, ctx: any) => {
		try {
			const claudeName = claudeToolName(event.toolName);
			const outcomes = await runAll(
				"PreToolUse",
				claudeName,
				{ tool_name: claudeName, tool_input: toClaudeInput(event.toolName, event.input) },
				ctx,
				(o) => Boolean(o.deny),
			);
			const denied = outcomes.find((o) => o.deny);
			if (denied) return { block: true, reason: denied.deny };
			for (const outcome of outcomes) {
				if (outcome.updatedInput) applyUpdatedInput(event.toolName, event.input, outcome.updatedInput);
			}
			return;
		} catch (err) {
			warn(`tool_call failed open: ${err instanceof Error ? err.message : String(err)}`, ctx);
			return;
		}
	});

	pi.on("tool_result", async (event: any, ctx: any) => {
		try {
			const claudeName = claudeToolName(event.toolName);
			const response = Array.isArray(event.content)
				? event.content
						.filter((p: any) => p?.type === "text" && typeof p.text === "string")
						.map((p: any) => p.text)
						.join("")
				: event.content;
			const context = contextFrom(
				await runAll(
					"PostToolUse",
					claudeName,
					{
						tool_name: claudeName,
						tool_input: toClaudeInput(event.toolName, event.input),
						tool_response: response,
					},
					ctx,
				),
			);
			if (!context) return;
			const content = Array.isArray(event.content) ? [...event.content] : [];
			content.push({ type: "text", text: context });
			return { content };
		} catch (err) {
			warn(`tool_result failed open: ${err instanceof Error ? err.message : String(err)}`, ctx);
			return;
		}
	});

	/**
	 * DEGRADED on purpose. `agent_settled` is fire-only — pi has already stopped
	 * and nothing here can refuse that. A Stop hook's `block` therefore becomes
	 * one extra user message, which restarts the agent but does not suppress the
	 * stop the user already saw.
	 */
	pi.on("agent_settled", async (event: any, ctx: any) => {
		try {
			const active = typeof event?.stop_hook_active === "boolean" ? event.stop_hook_active : stopHookActive;
			const outcomes = await runAll("Stop", undefined, { stop_hook_active: active }, ctx);
			if (active) return;
			const blocked = outcomes.find((o) => o.stopBlockReason);
			if (!blocked) return;
			stopHookActive = true;
			pi.sendUserMessage(blocked.stopBlockReason as string);
		} catch (err) {
			warn(`agent_settled failed open: ${err instanceof Error ? err.message : String(err)}`, ctx);
		}
	});
}
