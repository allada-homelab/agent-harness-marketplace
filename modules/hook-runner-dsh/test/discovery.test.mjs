// Manifest discovery against a fake profile tree: `$DSH_HOME/profiles/<name>`
// with a package.json whose `dsh.profile.bundles` names installed modules
// (@deepseek-ai/dsh-app-boot lib/index.js:318, :546).
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { collectHandlers, findProfileDir, loadManifests } from "../lib/manifests.js";
import { matchesMatcher } from "../lib/hooks.js";

const HOOKS = { PreToolUse: [{ matcher: "Bash", hooks: [{ type: "command", command: "echo hi", timeout: 3 }] }] };

/** A module directory, with a hooks.json unless `hooks` is null. */
function writeModule(profileDir, name, hooks) {
  const dir = join(profileDir, "node_modules", ...name.split("/"));
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "package.json"), JSON.stringify({ name, version: "0.0.0", exports: { "./package.json": "./package.json" } }));
  if (hooks !== null) {
    mkdirSync(join(dir, "hooks"));
    writeFileSync(join(dir, "hooks", "hooks.json"), typeof hooks === "string" ? hooks : JSON.stringify({ hooks }));
  }
  return dir;
}

/** A profile whose `dsh.profile.bundles` lists `bundles`. */
function writeProfile(bundles) {
  const dir = mkdtempSync(join(tmpdir(), "hook-runner-dsh-profile-"));
  writeFileSync(join(dir, "package.json"), JSON.stringify({ name: "profile", dsh: { profile: { bundles } } }));
  return dir;
}

const collect = () => {
  const lines = [];
  return { warn: (m) => lines.push(m), lines };
};

test("auto-discovery keeps the profile bundles that ship a hooks.json", () => {
  const profileDir = writeProfile(["@x/with-hooks", "@x/no-hooks"]);
  const withHooks = writeModule(profileDir, "@x/with-hooks", HOOKS);
  writeModule(profileDir, "@x/no-hooks", null);
  const { warn, lines } = collect();

  const loaded = loadManifests({ profileDir, warn });

  assert.deepEqual(
    loaded.map((m) => m.pluginRoot),
    [withHooks],
  );
  assert.deepEqual(lines, [], "a bundle without hooks is not an error");
});

test("an uninstalled bundle is skipped without failing discovery", () => {
  const profileDir = writeProfile(["@x/never-installed", "@x/with-hooks"]);
  const withHooks = writeModule(profileDir, "@x/with-hooks", HOOKS);

  const loaded = loadManifests({ profileDir, warn: () => {} });

  assert.deepEqual(
    loaded.map((m) => m.pluginRoot),
    [withHooks],
  );
});

test("config.manifests accepts a module directory", () => {
  const profileDir = writeProfile([]);
  const moduleDir = writeModule(profileDir, "@x/pinned", HOOKS);

  const loaded = loadManifests({ manifests: [moduleDir], warn: () => {} });

  assert.deepEqual(loaded.map((m) => m.pluginRoot), [moduleDir]);
});

test("config.manifests accepts a hooks.json path", () => {
  const profileDir = writeProfile([]);
  const moduleDir = writeModule(profileDir, "@x/pinned", HOOKS);

  const loaded = loadManifests({ manifests: [join(moduleDir, "hooks", "hooks.json")], warn: () => {} });

  assert.deepEqual(loaded.map((m) => m.pluginRoot), [moduleDir]);
});

test("a module reached by both config and auto-discovery is loaded once", () => {
  const profileDir = writeProfile(["@x/dual"]);
  const moduleDir = writeModule(profileDir, "@x/dual", HOOKS);
  const link = join(mkdtempSync(join(tmpdir(), "hook-runner-dsh-link-")), "dual");
  symlinkSync(moduleDir, link);

  const loaded = loadManifests({ manifests: [link], profileDir, warn: () => {} });

  assert.equal(loaded.length, 1, "the symlinked and resolved paths were not deduped by realpath");
});

test("a manifest named in config that does not exist is loud, not fatal", () => {
  const profileDir = writeProfile(["@x/with-hooks"]);
  const withHooks = writeModule(profileDir, "@x/with-hooks", HOOKS);
  const { warn, lines } = collect();

  const loaded = loadManifests({ manifests: ["/nowhere/at/all"], profileDir, warn });

  assert.deepEqual(loaded.map((m) => m.pluginRoot), [withHooks], "the healthy module still loaded");
  assert.equal(lines.length, 1);
  assert.match(lines[0], /does not exist/);
});

test("a manifest that does not parse is skipped and does not sink its siblings", () => {
  const profileDir = writeProfile(["@x/broken", "@x/with-hooks"]);
  writeModule(profileDir, "@x/broken", "{ not json");
  const withHooks = writeModule(profileDir, "@x/with-hooks", HOOKS);
  const { warn, lines } = collect();

  const loaded = loadManifests({ profileDir, warn });

  assert.deepEqual(loaded.map((m) => m.pluginRoot), [withHooks]);
  assert.match(lines[0], /did not parse/);
});

test("findProfileDir walks up to the package.json that declares dsh.profile.bundles", () => {
  const profileDir = writeProfile(["@x/with-hooks"]);
  const moduleDir = writeModule(profileDir, "@x/with-hooks", HOOKS);

  assert.equal(findProfileDir(join(moduleDir, "lib")), profileDir);
});

test("findProfileDir returns null outside a profile", () => {
  assert.equal(findProfileDir(mkdtempSync(join(tmpdir(), "hook-runner-dsh-loose-"))), null);
});

test("collectHandlers translates the manifest into runnable handlers", () => {
  const profileDir = writeProfile(["@x/with-hooks"]);
  const moduleDir = writeModule(profileDir, "@x/with-hooks", HOOKS);
  const loaded = loadManifests({ profileDir, warn: () => {} });

  const handlers = collectHandlers(loaded, "PreToolUse", { dsh: "bash", claude: "Bash" }, () => {}, matchesMatcher);

  assert.deepEqual(handlers, [{ command: "echo hi", timeoutMs: 3000, pluginRoot: moduleDir }]);
});

test("collectHandlers skips a handler whose matcher does not accept the tool", () => {
  const profileDir = writeProfile(["@x/with-hooks"]);
  writeModule(profileDir, "@x/with-hooks", HOOKS);
  const loaded = loadManifests({ profileDir, warn: () => {} });

  const handlers = collectHandlers(loaded, "PreToolUse", { dsh: "read", claude: "Read" }, () => {}, matchesMatcher);

  assert.deepEqual(handlers, []);
});

test("a Claude-only handler type is skipped with one line", () => {
  const profileDir = writeProfile(["@x/prompt-hook"]);
  writeModule(profileDir, "@x/prompt-hook", { PreToolUse: [{ hooks: [{ type: "prompt", prompt: "?" }] }] });
  const loaded = loadManifests({ profileDir, warn: () => {} });
  const { warn, lines } = collect();

  const handlers = collectHandlers(loaded, "PreToolUse", { dsh: "bash", claude: "Bash" }, warn, matchesMatcher);

  assert.deepEqual(handlers, []);
  assert.equal(lines.length, 1);
  assert.match(lines[0], /Claude-only/);
});
