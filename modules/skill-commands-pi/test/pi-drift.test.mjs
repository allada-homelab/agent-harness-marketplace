/**
 * Drift guard: `skillPrompt()` is a replica of pi's private
 * `AgentSession._expandSkillCommand`, and a pi upgrade that changes the skill
 * block would silently desync `/name` from `/skill:name`.
 *
 * This compares BEHAVIOR, not source text: pi's own method is called on a
 * fixture skill through a stand-in `this` (it touches only `resourceLoader` and
 * `_extensionRunner`), and its output must equal ours for the same inputs.
 *
 * The source of truth is the INSTALLED harness, so the guard needs pi present.
 * CI has no pi and must not fail for that, so the one skip in this repo lives
 * here: no pi and no `PI_INSTALLED_CHECK=1` => skip with a clear line. With
 * `PI_INSTALLED_CHECK=1` a missing pi is a failure naming what to install.
 */
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const MODULE_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const BUILD = mkdtempSync(join(tmpdir(), "skill-commands-drift-"));
const PI_PACKAGE = "@earendil-works/pi-coding-agent";

/**
 * pi is normally a global install (`npm i -g`), not a dependency of this module,
 * so the local resolution is tried first and the running Node's own global
 * `lib/node_modules` second. Returns the package.json path, or undefined.
 */
function findPi() {
	const require = createRequire(import.meta.url);
	try {
		return require.resolve(`${PI_PACKAGE}/package.json`);
	} catch {
		/* not a local dependency; try the global root */
	}
	const global = resolve(dirname(process.execPath), "..", "lib", "node_modules", PI_PACKAGE, "package.json");
	try {
		require(global);
		return global;
	} catch {
		return undefined;
	}
}

const PI_PACKAGE_JSON = findPi();
const skip = !PI_PACKAGE_JSON && process.env.PI_INSTALLED_CHECK !== "1";

let mod;
before(async () => {
	if (skip) return;
	const esbuild = await import("esbuild");
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

test("skillPrompt matches the installed pi's own skill expansion", { skip: skip && "skipped: pi not installed" }, async () => {
	assert.ok(
		PI_PACKAGE_JSON,
		`PI_INSTALLED_CHECK=1 but pi is not installed — run \`npm install -g ${PI_PACKAGE}\` (or install it into this module) so the drift guard can compare against the real harness`,
	);

	const piRoot = dirname(PI_PACKAGE_JSON);
	const { AgentSession } = await import(pathToFileURL(join(piRoot, "dist", "core", "agent-session.js")).href);
	const expand = AgentSession?.prototype?._expandSkillCommand;
	assert.equal(
		typeof expand,
		"function",
		`AgentSession._expandSkillCommand is gone in the installed pi — the skill-command expansion moved or was renamed, so extensions/skill-commands.ts must be re-derived from ${piRoot}/dist/core/agent-session.js`,
	);

	const dir = join(BUILD, "demo");
	mkdirSync(dir, { recursive: true });
	const filePath = join(dir, "SKILL.md");
	const source = "---\nname: demo\ndescription: d\nuser-invocable: true\n---\n\nStep one.\n\nStep two.\n";
	writeFileSync(filePath, source);

	// `_expandSkillCommand` reads only these two collaborators; pi's own Skill
	// carries baseDir, which for a loaded skill is the SKILL.md directory.
	const session = {
		resourceLoader: { getSkills: () => ({ skills: [{ name: "demo", filePath, baseDir: dir }] }) },
		_extensionRunner: { emitError: () => {} },
	};

	for (const args of ["", "go fast"]) {
		const piText = expand.call(session, `/skill:demo${args ? ` ${args}` : ""}`);
		assert.equal(
			mod.skillPrompt("demo", filePath, source, args),
			piText,
			`skillPrompt has drifted from pi ${createRequire(import.meta.url)(PI_PACKAGE_JSON).version} (args: ${args || "none"})`,
		);
	}
});
