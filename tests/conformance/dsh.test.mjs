// Until 2026-09-07 this suite applied every dsh plugin module under cordis's
// real inject rule (a plugin may touch only the ctx services it declares).
// The two modules that made that necessary — the skills bridge and the hook
// runner — moved to the maintainer's harness layer as
// foundation, always installed there rather than shipped as marketplace
// modules. No module under modules/ ships code anymore, so this suite is now
// the invariant that keeps it that way: a module with a lib/ directory (or a
// pi extensions/ directory — see pi.test.mjs) would need this repo to grow
// the strict-ctx conformance machinery back.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";

const ROOT = resolve(new URL("../..", import.meta.url).pathname);
const MODULES = join(ROOT, "modules");

test("no module under modules/ ships a lib/ directory — code belongs in dotfiles", () => {
  const offenders = readdirSync(MODULES)
    .filter((m) => existsSync(join(MODULES, m, "lib")))
    .sort();
  assert.deepEqual(offenders, []);
});
