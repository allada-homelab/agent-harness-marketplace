// Until 2026-09-07 this suite bundled and loaded every pi extension in the
// repo against a strict ExtensionAPI stub. The two extensions that made that
// necessary — the hook runner and skill-commands — moved to
// the maintainer's harness layer as pi foundation, always
// installed there rather than shipped as marketplace modules. No module
// under modules/ ships a pi extension anymore, so this suite is now the
// invariant that keeps it that way: a module with an extensions/ directory
// (or a dsh lib/ directory — see dsh.test.mjs) would need this repo to grow
// the strict-stub conformance machinery back.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";

const ROOT = resolve(new URL("../..", import.meta.url).pathname);
const MODULES = join(ROOT, "modules");

test("no module under modules/ ships an extensions/ directory — code belongs in dotfiles", () => {
  const offenders = readdirSync(MODULES)
    .filter((m) => existsSync(join(MODULES, m, "extensions")))
    .sort();
  assert.deepEqual(offenders, []);
});
