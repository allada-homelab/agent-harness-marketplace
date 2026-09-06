/**
 * Unit suite for skill-commands-pi: the frontmatter filter, the expansion, and
 * the registration wiring against a fake pi API. The extension is bundled with
 * esbuild first; if esbuild cannot be obtained the suite FAILS, not skips.
 */
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { after, before, describe, test } from "node:test";
import { fileURLToPath } from "node:url";

const MODULE_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const BUILD = mkdtempSync(join(tmpdir(), "skill-commands-test-"));
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
	const out = join(BUILD, "skill-commands.mjs");
	await esbuild.build({
		entryPoints: [join(MODULE_DIR, "extensions", "skill-commands.ts")],
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

/** Write a SKILL.md and return its path. */
function makeSkill(name, frontmatterLines, body = "Do the thing.") {
	const dir = join(BUILD, name);
	mkdirSync(dir, { recursive: true });
	const path = join(dir, "SKILL.md");
	writeFileSync(path, `---\nname: ${name}\ndescription: d\n${frontmatterLines.join("\n")}\n---\n\n${body}\n`);
	return path;
}

/** Fake pi: records registered commands and sent user messages. */
function fakePi(commands) {
	const registered = new Map();
	const sent = [];
	const handlers = {};
	const api = {
		on: (event, handler) => {
			handlers[event] = handler;
		},
		getCommands: () => commands,
		registerCommand: (name, options) => registered.set(name, options),
		registerTool() {
			throw new Error("skill-commands must stay event-only");
		},
		sendUserMessage: (content) => sent.push(content),
		sendMessage() {},
		appendEntry() {},
	};
	return { api, handlers, registered, sent, ctx: { ui: { notify: () => {} } } };
}

const skillCommand = (name, path) => ({
	name: `skill:${name}`,
	description: `the ${name} skill`,
	source: "skill",
	sourceInfo: { path, source: "package", scope: "user" },
});

describe("frontmatter filter", () => {
	test("user-invocable: true is the only thing that registers a command", () => {
		assert.equal(mod.isUserInvocable("---\nname: a\nuser-invocable: true\n---\nbody"), true);
	});

	test("user-invocable: false does not", () => {
		assert.equal(mod.isUserInvocable("---\nname: a\nuser-invocable: false\n---\nbody"), false);
	});

	test("a skill without the field does not", () => {
		assert.equal(mod.isUserInvocable("---\nname: a\ndescription: d\n---\nbody"), false);
	});

	test("a file without frontmatter does not", () => {
		assert.equal(mod.isUserInvocable("# just markdown"), false);
	});

	test("quoted values are unwrapped", () => {
		assert.equal(mod.isUserInvocable('---\nuser-invocable: "true"\n---\n'), true);
	});
});

describe("expansion", () => {
	test("matches pi's /skill: block, with args appended", () => {
		const source = "---\nname: demo\n---\n\nStep one.\n";
		const expanded = mod.skillPrompt("demo", "/skills/demo/SKILL.md", source, "go fast");
		assert.equal(
			expanded,
			'<skill name="demo" location="/skills/demo/SKILL.md">\n' +
				"References are relative to /skills/demo.\n\n" +
				"Step one.\n</skill>\n\ngo fast",
		);
	});

	test("no args means no trailing user line", () => {
		const expanded = mod.skillPrompt("demo", "/skills/demo/SKILL.md", "---\nname: demo\n---\n\nStep one.\n", "");
		assert.ok(expanded.endsWith("</skill>"));
	});
});

describe("registration", () => {
	test("registers only the user-invocable skill", async () => {
		const yes = makeSkill("deploy", ["user-invocable: true"]);
		const no = makeSkill("research", []);
		const pi = fakePi([skillCommand("deploy", yes), skillCommand("research", no)]);
		mod.default(pi.api);
		await pi.handlers.session_start({ reason: "startup" }, pi.ctx);

		assert.deepEqual([...pi.registered.keys()], ["deploy"]);
	});

	test("declines a name an existing command already owns", async () => {
		const path = makeSkill("stats", ["user-invocable: true"]);
		const pi = fakePi([
			{ name: "stats", description: "an extension command", source: "extension", sourceInfo: { path: "x" } },
			skillCommand("stats", path),
		]);
		mod.default(pi.api);
		await pi.handlers.session_start({ reason: "startup" }, pi.ctx);

		assert.equal(pi.registered.size, 0);
	});

	test("the handler sends the expanded skill with its args", async () => {
		const path = makeSkill("deploy", ["user-invocable: true"], "Ship it.");
		const pi = fakePi([skillCommand("deploy", path)]);
		mod.default(pi.api);
		await pi.handlers.session_start({ reason: "startup" }, pi.ctx);
		await pi.registered.get("deploy").handler("staging", pi.ctx);

		assert.equal(pi.sent.length, 1);
		assert.match(pi.sent[0], /<skill name="deploy"/);
		assert.match(pi.sent[0], /Ship it\.\n<\/skill>\n\nstaging$/);
	});

	test("an unreadable skill file does not stop the others", async () => {
		const good = makeSkill("deploy", ["user-invocable: true"]);
		const pi = fakePi([skillCommand("gone", join(BUILD, "nope", "SKILL.md")), skillCommand("deploy", good)]);
		mod.default(pi.api);
		await pi.handlers.session_start({ reason: "startup" }, pi.ctx);

		assert.deepEqual([...pi.registered.keys()], ["deploy"]);
	});
});
