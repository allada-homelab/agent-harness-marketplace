/**
 * Conformance suite for hook-runner-pi.
 *
 * Extract-not-copy: the extension is bundled with esbuild into a tmpdir and its
 * default export is wired to a FAKE pi object, so every corpus case runs through
 * the real seam mapping with the real fixture processes actually executing.
 *
 * Every case in ../../../hook-contract/corpus.json whose `harness` includes
 * "pi" runs here. If esbuild cannot be obtained the suite FAILS — a hook runner
 * that silently skips its conformance corpus is worse than no suite.
 */
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { after, before, describe, test } from "node:test";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const MODULE_DIR = resolve(HERE, "..");
const CONTRACT_DIR = resolve(MODULE_DIR, "..", "..", "hook-contract");
const CORPUS = JSON.parse(readFileSync(join(CONTRACT_DIR, "corpus.json"), "utf-8"));
const PROJECT_DIR = process.cwd();

const BUILD = mkdtempSync(join(tmpdir(), "hook-runner-test-"));
let mod;

before(async () => {
	// The pinned devDependency, not `npx esbuild@…`: a test that fetches from the
	// network at run time is not a test. Missing esbuild fails loudly here.
	let esbuild;
	try {
		esbuild = await import("esbuild");
	} catch (err) {
		throw new Error(`esbuild is not installed for this module — run \`pnpm install\` at the repo root: ${err.message}`);
	}
	const out = join(BUILD, "hook-runner.mjs");
	await esbuild.build({
		entryPoints: [join(MODULE_DIR, "extensions", "hook-runner.ts")],
		bundle: true,
		platform: "node",
		format: "esm",
		external: ["@earendil-works/*"],
		outfile: out,
		logLevel: "error",
	});
	mod = await import(out);
});

after(() => rmSync(BUILD, { recursive: true, force: true }));

/** A module dir that owns the case's hooks.json, with the fixtures beside it. */
function makeModuleDir(name, hooks) {
	const dir = mkdtempSync(join(BUILD, `${name}-`));
	mkdirSync(join(dir, "hooks"), { recursive: true });
	writeFileSync(join(dir, "hooks", "hooks.json"), JSON.stringify({ hooks }));
	symlinkSync(join(CONTRACT_DIR, "fixtures"), join(dir, "fixtures"));
	return dir;
}

/** Records everything the extension does to pi, and everything it says on stderr. */
function fakePi() {
	const handlers = {};
	const messages = [];
	const userMessages = [];
	const stderr = [];
	const api = {
		on: (event, handler) => {
			handlers[event] = handler;
		},
		registerCommand() {},
		registerTool() {
			throw new Error("hook-runner must stay event-only: registerTool costs tokens every turn");
		},
		sendMessage: (message, options) => messages.push({ message, options }),
		sendUserMessage: (content, options) => userMessages.push({ content, options }),
		appendEntry() {},
	};
	const ctx = { ui: { notify: () => {} }, cwd: PROJECT_DIR };
	return { api, ctx, handlers, messages, userMessages, stderr };
}

/** Capture process.stderr.write for the duration of one case. */
async function withStderr(sink, fn) {
	const original = process.stderr.write.bind(process.stderr);
	process.stderr.write = (chunk, ...rest) => {
		sink.push(String(chunk));
		return original(chunk, ...rest);
	};
	try {
		return await fn();
	} finally {
		process.stderr.write = original;
	}
}

const piCases = CORPUS.cases.filter((c) => c.harness.includes("pi"));

describe("corpus", () => {
	assert.ok(piCases.length > 0, "corpus has no pi cases");

	for (const testCase of piCases) {
		test(testCase.name, async () => {
			// Every fixture records the event it saw to $HOOK_CONTRACT_ECHO, so the
			// handler list the case declares is the one that runs — no probe.
			const wantStdin = testCase.stdin ?? testCase.stdin_by_harness?.pi;
			const moduleDir = makeModuleDir(testCase.name, testCase.hooks);
			const echoPath = join(moduleDir, "echo.json");
			process.env.PI_HOOK_MANIFESTS = moduleDir;
			process.env.HOOK_CONTRACT_ECHO = echoPath;

			const pi = fakePi();
			mod.default(pi.api);

			const native = testCase.native.pi;
			let result;
			let event;
			await withStderr(pi.stderr, async () => {
				switch (native.event) {
					case "tool_call":
						event = { toolName: native.toolName, toolCallId: "t1", input: { ...native.input } };
						result = await pi.handlers.tool_call(event, pi.ctx);
						break;
					case "tool_result":
						event = {
							toolName: native.toolName,
							toolCallId: "t1",
							input: { ...native.input },
							content: native.content,
							details: native.details,
						};
						result = await pi.handlers.tool_result(event, pi.ctx);
						break;
					case "before_agent_start":
						event = { prompt: native.prompt, systemPrompt: "", systemPromptOptions: {} };
						result = await pi.handlers.before_agent_start(event, pi.ctx);
						break;
					case "session_start":
						event = { reason: "startup" };
						result = await pi.handlers.session_start(event, pi.ctx);
						break;
					case "agent_settled":
						event = native.stop_hook_active === undefined ? {} : { stop_hook_active: native.stop_hook_active };
						result = await pi.handlers.agent_settled(event, pi.ctx);
						break;
					default:
						throw new Error(`unmapped native event ${native.event}`);
				}
			});

			const loud = pi.stderr.join("").includes("hook-runner");

			// A case may specify a per-harness outcome when the harnesses genuinely
			// differ (dsh cannot apply a PreToolUse rewrite, pi can).
			const outcome = testCase.outcome_by_harness?.pi ?? testCase.outcome;
			switch (outcome) {
				case "allow":
					assert.notEqual(result?.block, true, "expected the action to proceed");
					if (native.event === "tool_call") assert.deepEqual(event.input, native.input, "input must be unchanged");
					if (native.event === "agent_settled") assert.equal(pi.userMessages.length, 0);
					break;
				case "deny":
					assert.equal(result?.block, true, "expected a block");
					assert.match(result.reason, new RegExp(escapeRe(testCase.reason)));
					break;
				case "rewrite": {
					assert.notEqual(result?.block, true);
					// `updatedInput` on a rewrite case is the input the harness must end
					// up with, in its own native arg names (pi's `path`/`edits[].oldText`).
					assert.deepEqual(event.input, { ...native.input, ...testCase.updatedInput });
					assert.notDeepEqual(event.input, native.input, "rewrite did not change the input");
					break;
				}
				case "context": {
					let seen;
					if (native.event === "session_start") seen = pi.messages.map((m) => m.message.content).join("\n");
					else if (native.event === "tool_result")
						seen = (result?.content ?? []).map((p) => (p?.type === "text" ? p.text : "")).join("\n");
					else seen = result?.message?.content ?? "";
					assert.match(seen, new RegExp(escapeRe(testCase.additionalContext)));
					break;
				}
				case "stop-block":
					assert.equal(pi.userMessages.length, 1, "expected exactly one forced follow-up");
					assert.match(pi.userMessages[0].content, new RegExp(escapeRe(testCase.reason)));
					break;
				case "failed-open":
					assert.notEqual(result?.block, true, "a failed handler must not block");
					assert.ok(loud, "a failed handler must write one hook-runner line to stderr");
					break;
				default:
					throw new Error(`unknown outcome ${outcome}`);
			}

			if (wantStdin) {
				const seen = JSON.parse(readFileSync(echoPath, "utf-8"));
				for (const [key, want] of Object.entries(wantStdin)) {
					const expected = want === "$PROJECT_DIR" ? PROJECT_DIR : want;
					assert.deepEqual(seen[key], expected, `stdin.${key}`);
				}
			}
		});
	}
});

describe("manifest discovery", () => {
	test("finds sibling modules and honors PI_HOOK_MANIFESTS, deduped", () => {
		const repo = mkdtempSync(join(BUILD, "tree-"));
		const self = join(repo, "modules", "hook-runner-pi", "extensions", "hook-runner.ts");
		mkdirSync(dirname(self), { recursive: true });
		for (const name of ["alpha", "beta", "no-hooks"]) {
			mkdirSync(join(repo, "modules", name, "hooks"), { recursive: true });
		}
		writeFileSync(join(repo, "modules", "alpha", "hooks", "hooks.json"), "{}");
		writeFileSync(join(repo, "modules", "beta", "hooks", "hooks.json"), "{}");

		const fleet = mkdtempSync(join(BUILD, "fleet-"));
		mkdirSync(join(fleet, "hooks"), { recursive: true });
		writeFileSync(join(fleet, "hooks", "hooks.json"), "{}");

		// alpha appears twice (module dir + explicit file) and must collapse to one.
		const env = {
			PI_CODING_AGENT_DIR: "/nope",
			PI_HOOK_MANIFESTS: [fleet, join(repo, "modules", "alpha", "hooks", "hooks.json"), "", "/nope"].join(":"),
		};
		const found = mod.manifestPaths(self, env);
		assert.deepEqual(found, [
			join(repo, "modules", "alpha", "hooks", "hooks.json"),
			join(repo, "modules", "beta", "hooks", "hooks.json"),
			join(fleet, "hooks", "hooks.json"),
		]);
	});

	test("a module pi's package filter switches off contributes no hooks", () => {
		const repo = mkdtempSync(join(BUILD, "tree-"));
		const self = join(repo, "modules", "hook-runner-pi", "extensions", "hook-runner.ts");
		mkdirSync(dirname(self), { recursive: true });
		for (const name of ["alpha", "claude-only"]) {
			mkdirSync(join(repo, "modules", name, "hooks"), { recursive: true });
			writeFileSync(join(repo, "modules", name, "hooks", "hooks.json"), "{}");
		}
		const agentDir = mkdtempSync(join(BUILD, "agent-"));
		writeFileSync(
			join(agentDir, "settings.json"),
			JSON.stringify({
				packages: [
					"npm:something",
					{ source: "git:git@github.com:o/r.git@main", skills: ["!modules/claude-only/**", "!skills/x"], extensions: ["!modules/claude-only/**"] },
				],
			}),
		);
		const env = { PI_CODING_AGENT_DIR: agentDir, PI_HOOK_MANIFESTS: "" };
		assert.deepEqual([...mod.excludedModules(env)], ["claude-only"]);
		assert.deepEqual(mod.manifestPaths(self, env), [join(repo, "modules", "alpha", "hooks", "hooks.json")]);
		// The env override works without settings, and an unreadable settings file excludes nothing.
		assert.deepEqual([...mod.excludedModules({ PI_CODING_AGENT_DIR: "/nope", PI_HOOK_EXCLUDE_MODULES: "alpha, beta" })], ["alpha", "beta"]);
		assert.deepEqual(mod.manifestPaths(self, { PI_CODING_AGENT_DIR: "/nope", PI_HOOK_EXCLUDE_MODULES: "alpha" }), [
			join(repo, "modules", "claude-only", "hooks", "hooks.json"),
		]);
	});

	test("plugin root is the module dir; unreadable manifests are skipped loudly", () => {
		const dir = makeModuleDir("plugin-root", { SessionStart: [] });
		const bad = mkdtempSync(join(BUILD, "bad-"));
		mkdirSync(join(bad, "hooks"), { recursive: true });
		writeFileSync(join(bad, "hooks", "hooks.json"), "{ not json");
		const warnings = [];
		const manifests = mod.loadManifests(
			[join(dir, "hooks", "hooks.json"), join(bad, "hooks", "hooks.json")],
			(m) => warnings.push(m),
		);
		assert.equal(manifests.length, 1);
		assert.equal(manifests[0].pluginRoot, dir);
		assert.equal(warnings.length, 1);
	});
});

describe("translation", () => {
	test("native tool names map to Claude names", () => {
		assert.equal(mod.claudeToolName("bash"), "Bash");
		assert.equal(mod.claudeToolName("find"), "Glob");
		assert.equal(mod.claudeToolName("some_mcp_tool"), "some_mcp_tool");
	});

	test("pi edit args round-trip through the Claude shape", () => {
		const input = { path: "/a.ts", edits: [{ oldText: "a", newText: "b" }] };
		assert.deepEqual(mod.toClaudeInput("edit", input), {
			file_path: "/a.ts",
			old_string: "a",
			new_string: "b",
		});
		mod.applyUpdatedInput("edit", input, { file_path: "/b.ts", old_string: "x", new_string: "y" });
		assert.deepEqual(input, { path: "/b.ts", edits: [{ oldText: "x", newText: "y" }] });
	});

	test("a multi-edit call carries the whole list plus flat fields for the first", () => {
		const input = { path: "/a.ts", edits: [{ oldText: "a", newText: "b" }, { oldText: "c", newText: "d" }] };
		assert.deepEqual(mod.toClaudeInput("edit", input), {
			file_path: "/a.ts",
			old_string: "a",
			new_string: "b",
			edits: [{ old_string: "a", new_string: "b" }, { old_string: "c", new_string: "d" }],
		});
	});

	test("a rewrite returning edits replaces the whole list", () => {
		const input = { path: "/a.ts", edits: [{ oldText: "a", newText: "b" }, { oldText: "c", newText: "d" }] };
		mod.applyUpdatedInput("edit", input, { edits: [{ old_string: "a", new_string: "B" }] });
		assert.deepEqual(input, { path: "/a.ts", edits: [{ oldText: "a", newText: "B" }] });
	});

	test("tool_response is the text parts, else the native result as JSON", () => {
		assert.equal(mod.toolResponse({ content: [{ type: "text", text: "hi\n" }] }), "hi\n");
		assert.equal(mod.toolResponse({ content: [{ type: "image" }], details: { matches: ["a"] } }), '{"matches":["a"]}');
	});

	test("write and grep translate both ways", () => {
		assert.deepEqual(mod.toClaudeInput("write", { path: "/a", content: "c" }), { file_path: "/a", content: "c" });
		const grep = { pattern: "p", path: "/d" };
		mod.applyUpdatedInput("grep", grep, { pattern: "q" });
		assert.deepEqual(grep, { pattern: "q", path: "/d" });
	});
});

function escapeRe(s) {
	return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
