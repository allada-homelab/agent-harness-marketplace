// Every dsh plugin module must survive `apply` under cordis's real rule: a
// plugin may touch only the ctx services it declares in `inject` (plus the
// core ones every plugin gets). cordis throws on the ACCESS, so `?.` cannot
// guard it, and a permissive test stub hides the gap — which is how two
// plugins shipped that registered nothing (hook-runner-dsh, dsh-module-skills
// before v0.1.1/v0.1.3). This suite applies each module against a ctx that
// throws on any undeclared service and asserts it registered something.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const ROOT = resolve(new URL("../..", import.meta.url).pathname);
const MODULES = join(ROOT, "modules");

import { CORE, strictCtx } from "./strict-ctx.mjs";

const dshModules = readdirSync(MODULES)
  .filter((m) => {
    const pkg = join(MODULES, m, "package.json");
    return existsSync(pkg) && JSON.parse(readFileSync(pkg, "utf8")).dsh?.bundle?.patch && existsSync(join(MODULES, m, "lib", "index.js"));
  })
  .sort();

test("there is at least one dsh plugin module to check", () => {
  assert.ok(dshModules.length > 0, "no modules with dsh.bundle.patch + lib/index.js");
});

for (const m of dshModules) {
  test(`${m}: package.json, cordis.patch.yml and lib/index.js agree`, async () => {
    const dir = join(MODULES, m);
    const pkg = JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
    assert.equal(pkg.dsh.bundle.patch, "./cordis.patch.yml");
    assert.equal(pkg.type, "module", "dsh plugins are ESM");
    assert.ok(existsSync(join(dir, "cordis.patch.yml")), "cordis.patch.yml missing");
    const patch = readFileSync(join(dir, "cordis.patch.yml"), "utf8");
    assert.ok(patch.includes(`name: '${pkg.name}'`) || patch.includes(`name: "${pkg.name}"`), `cordis.patch.yml must insert a row of ${pkg.name}`);
    const main = pkg.main ?? pkg.exports?.["."] ?? "lib/index.js";
    const mod = await import(pathToFileURL(join(dir, main)).href);
    const plugin = mod.default ?? mod;
    assert.equal(typeof plugin.apply, "function", "no apply()");
    assert.equal(typeof plugin.name, "string", "no name export");
    assert.ok(Array.isArray(plugin.inject), "inject must be an array (cordis throws on undeclared services)");
  });

  test(`${m}: apply() under a strict ctx registers at least one seam and throws nothing`, async () => {
    const dir = join(MODULES, m);
    const pkg = JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
    const mod = await import(pathToFileURL(join(dir, pkg.main ?? "lib/index.js")).href);
    const plugin = mod.default ?? mod;
    const log = [];
    const stderr = [];
    const realWrite = process.stderr.write.bind(process.stderr);
    process.stderr.write = (chunk) => { stderr.push(String(chunk)); return true; };
    try {
      await plugin.apply(strictCtx(plugin.inject ?? [], log), {});
    } finally {
      process.stderr.write = realWrite;
    }
    assert.ok(log.length > 0, `apply() registered nothing (stderr: ${stderr.join(" ").slice(0, 300)})`);
    const injectGaps = stderr.filter((l) => l.includes("without inject"));
    assert.deepEqual(injectGaps, [], "apply() swallowed an inject gap into stderr");
  });

  test(`${m}: source touches no ctx service outside inject`, async () => {
    const dir = join(MODULES, m);
    const pkg = JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
    const mod = await import(pathToFileURL(join(dir, pkg.main ?? "lib/index.js")).href);
    const plugin = mod.default ?? mod;
    const libDir = join(dir, "lib");
    const touched = new Set();
    for (const f of readdirSync(libDir).filter((f) => f.endsWith(".js"))) {
      const src = readFileSync(join(libDir, f), "utf8");
      for (const mm of src.matchAll(/\bctx\.(?:get\?\.\(')?([a-zA-Z]+)/g)) {
        if (!CORE.has(mm[1])) touched.add(mm[1]);
      }
    }
    for (const svc of touched) {
      assert.ok(plugin.inject.includes(svc), `ctx.${svc} is used but not in inject [${plugin.inject.join(", ")}]`);
    }
  });
}
