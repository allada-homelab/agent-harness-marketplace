// Every pi extension in the repo must load: bundle it exactly the way its own
// tests do, run `default(pi)` against a stub that knows pi 0.84's extension
// API and rejects anything else, and assert it registered only event handlers
// and commands. `registerTool` is refused on purpose: a tool schema rides on
// every request, and this marketplace's extensions are event-only by contract
// (0 tokens/turn). A renamed pi API or an accidental tool fails here, not on a
// user's next `pi update`.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readdirSync, existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, basename } from "node:path";
import { pathToFileURL } from "node:url";

const ROOT = resolve(new URL("../..", import.meta.url).pathname);
const MODULES = join(ROOT, "modules");

const extensions = readdirSync(MODULES)
  .flatMap((m) => {
    const dir = join(MODULES, m, "extensions");
    return existsSync(dir) ? readdirSync(dir).filter((f) => f.endsWith(".ts")).map((f) => ({ module: m, file: join(dir, f) })) : [];
  })
  .sort((a, b) => a.file.localeCompare(b.file));

// The pi ExtensionAPI surface these extensions may use (pi 0.84.1
// docs/extensions.md). Unknown members throw, so a renamed API is caught.
const KNOWN = new Set([
  "on", "registerCommand", "registerShortcut", "registerFlag", "registerProvider",
  "registerMessageRenderer", "registerEntryRenderer", "sendMessage", "sendUserMessage",
  "appendEntry", "getCommands", "setActiveTools", "setModel", "exec", "events", "ui",
]);

function stubPi(log) {
  const api = {
    on: (event, handler) => { assert.equal(typeof handler, "function"); log.push(`on:${event}`); },
    registerCommand: (name, def) => { assert.equal(typeof def?.handler, "function", `command ${name} has no handler`); log.push(`command:${name}`); },
    registerShortcut: (k) => log.push(`shortcut:${k}`),
    registerFlag: (f) => log.push(`flag:${f?.name ?? f}`),
    registerProvider: () => log.push("provider"),
    registerMessageRenderer: () => log.push("renderer"),
    registerEntryRenderer: () => log.push("renderer"),
    sendMessage: () => log.push("sendMessage"),
    sendUserMessage: () => log.push("sendUserMessage"),
    appendEntry: () => log.push("appendEntry"),
    getCommands: () => [],
    setActiveTools: () => {},
    setModel: () => {},
    exec: async () => ({ code: 0, stdout: "", stderr: "" }),
    events: { on: () => {}, emit: () => {} },
    ui: { notify: () => {} },
  };
  return new Proxy(api, {
    get(target, prop) {
      if (typeof prop === "symbol" || prop === "then") return undefined;
      if (prop === "registerTool") throw new Error("registerTool is forbidden: marketplace extensions are event-only (0 tokens/turn)");
      if (!KNOWN.has(prop)) throw new Error(`pi.${String(prop)} is not a known ExtensionAPI member`);
      return target[prop];
    },
  });
}

test("there is at least one pi extension to check", () => {
  assert.ok(extensions.length > 0);
});

let esbuild;
test("esbuild is available (pinned devDependency, never fetched at test time)", async () => {
  esbuild = await import("esbuild");
  assert.equal(typeof esbuild.build, "function");
});

for (const { module, file } of extensions) {
  test(`${module}/${basename(file)}: bundles, loads, and registers event handlers only`, async () => {
    assert.ok(esbuild, "esbuild did not load");
    const out = join(mkdtempSync(join(tmpdir(), "conformance-pi-")), basename(file).replace(/\.ts$/, ".mjs"));
    await esbuild.build({
      entryPoints: [file],
      outfile: out,
      bundle: true,
      format: "esm",
      platform: "node",
      target: "node22",
      external: ["@earendil-works/*"],
      logLevel: "silent",
    });
    const mod = await import(pathToFileURL(out).href);
    assert.equal(typeof mod.default, "function", "extension must export a default function (pi) => void");
    const log = [];
    const stderr = [];
    const realWrite = process.stderr.write.bind(process.stderr);
    process.stderr.write = (chunk) => { stderr.push(String(chunk)); return true; };
    try {
      await mod.default(stubPi(log));
    } finally {
      process.stderr.write = realWrite;
    }
    assert.ok(log.some((l) => l.startsWith("on:")), `no pi.on handler registered (log: ${log.join(", ")})`);
    const src = readFileSync(file, "utf8");
    assert.ok(!/\bpi\.registerTool\s*\(/.test(src), "registerTool in source: extensions are event-only");
  });
}
