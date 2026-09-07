// Apply every @allada-homelab plugin installed in a dsh profile under the same
// strict ctx the conformance suite uses, and list what the bridge serves.
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
  // A content module carries dsh.bundle only to mount the bridge; it ships no
  // plugin of its own. The bridge (a real plugin) is exercised below.
  const main = pkg.main ?? pkg.exports?.["."];
  if (!main || !existsSync(join(scope, name, main))) { console.log(`  ok   ${pkg.name}: content module (no plugin to apply)`); continue; }
  const mod = await import(pathToFileURL(req.resolve(pkg.name)).href);
  const plugin = mod.default ?? mod;
  const log = [];
  try {
    await plugin.apply(strictCtx(plugin.inject ?? [], log, { baseUrl: pathToFileURL(profileDir).href + "/" }), {});
    if (pkg.name.endsWith("dsh-module-skills") && !log.some((l) => l.includes("research"))) throw new Error("bridge did not discover the installed research skill");
    if (!log.length) throw new Error("registered nothing");
    console.log(`  ok   ${pkg.name} applied: ${log.join(", ")}`);
  } catch (e) {
    console.log(`  FAIL ${pkg.name}: ${e.message}`);
    bad = 1;
  }
}
// The apply-loop above already applied the bridge with the RESEARCH row (dsh
// composes one bridge instance per content module), so proving the bridge
// discovered the installed research package is: did that instance register a
// provider and the research command? `commands.register:research` in the log is
// the bridge reading research's SKILL.md out of the profile's node_modules.
process.exit(bad);
