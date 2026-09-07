// Apply every @allada-homelab plugin installed in a dsh profile under the
// same strict ctx the conformance suite uses. The skills bridge is harness
// foundation now (not installed from this repo), so today every installed
// package is a content module with dsh.bundle but no code — the loop stays
// generic so it still catches a future module that ships code but registers
// nothing.
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { strictCtx } from "../conformance/strict-ctx.mjs";

const profileDir = process.argv[2];
const req = createRequire(join(profileDir, "package.json"));
const scope = join(profileDir, "node_modules", "@allada-homelab");
let bad = 0;
for (const name of readdirSync(scope).sort()) {
  const pkg = JSON.parse(readFileSync(join(scope, name, "package.json"), "utf8"));
  if (!pkg.dsh?.bundle?.patch) continue;
  // A content module carries dsh.bundle so the harness's foundation skills
  // bridge discovers it, but ships no plugin of its own — its patch is empty.
  const main = pkg.main ?? pkg.exports?.["."];
  if (!main || !existsSync(join(scope, name, main))) { console.log(`  ok   ${pkg.name}: content module (no plugin to apply)`); continue; }
  const mod = await import(pathToFileURL(req.resolve(pkg.name)).href);
  const plugin = mod.default ?? mod;
  const log = [];
  try {
    await plugin.apply(strictCtx(plugin.inject ?? [], log, { baseUrl: pathToFileURL(profileDir).href + "/" }), {});
    if (!log.length) throw new Error("registered nothing");
    console.log(`  ok   ${pkg.name} applied: ${log.join(", ")}`);
  } catch (e) {
    console.log(`  FAIL ${pkg.name}: ${e.message}`);
    bad = 1;
  }
}
process.exit(bad);
