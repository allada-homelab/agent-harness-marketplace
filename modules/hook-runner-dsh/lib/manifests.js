/**
 * Finding the `hooks/hooks.json` files this runner is responsible for.
 *
 * Two sources, unioned and deduped by realpath:
 *
 *   1. `config.manifests` — absolute paths to a `hooks.json` or to a module
 *      directory. The fleet path: a config-managed profile names its modules
 *      explicitly and nothing depends on install layout.
 *   2. Auto-discovery — the profile's own `package.json` lists its installed
 *      bundles under `dsh.profile.bundles`; each is `createRequire`-resolved and
 *      kept when it ships `hooks/hooks.json`. This is what makes
 *      `dsh plugin add <module>` enough, with no second config edit.
 *
 * Installed modules are trusted by installation, so there is no trust gate here.
 */
import { createRequire } from "node:module";
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * Locate the dsh profile directory by walking up from this file.
 *
 * A profile is `$DSH_HOME/profiles/<name>` (`@deepseek-ai/dsh-app-boot`
 * lib/index.js:289, :318) and its `package.json` is the one carrying
 * `dsh.profile.bundles` (read at :546). This plugin is installed into that
 * profile's `node_modules`, so the nearest ancestor whose manifest has that key
 * IS the profile — no runtime API needs to hand it over.
 *
 * @returns the profile directory, or `null` when this runner is not installed
 *   into a profile (a checkout, a test tree, the flat module fallback).
 */
export function findProfileDir(startDir) {
  let dir = startDir;
  for (let i = 0; i < 12; i += 1) {
    const manifest = join(dir, "package.json");
    if (existsSync(manifest)) {
      try {
        const pkg = JSON.parse(readFileSync(manifest, "utf8"));
        if (Array.isArray(pkg?.dsh?.profile?.bundles)) return dir;
      } catch {
        /* an unreadable package.json is simply not the profile */
      }
    }
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

/** Resolve one `config.manifests` entry (a hooks.json, or a module dir) to a hooks.json path. */
function manifestPathOf(entry, baseDir) {
  const path = isAbsolute(entry) ? entry : resolve(baseDir, entry);
  if (path.endsWith(".json")) return path;
  return join(path, "hooks", "hooks.json");
}

/** Every bundle in the profile's `dsh.profile.bundles` that ships a hooks.json. */
function autoDiscovered(profileDir, warn) {
  const found = [];
  const manifest = join(profileDir, "package.json");
  let bundles;
  try {
    bundles = JSON.parse(readFileSync(manifest, "utf8"))?.dsh?.profile?.bundles ?? [];
  } catch (error) {
    warn(`could not read ${manifest} for auto-discovery, so only config.manifests apply: ${error}`);
    return found;
  }
  const require = createRequire(manifest);
  for (const bundle of bundles) {
    let packageDir;
    try {
      packageDir = dirname(require.resolve(`${bundle}/package.json`));
    } catch {
      // A bundle without an exported package.json is not something we can
      // inspect; it is also not a module of ours. Silent by design — every dsh
      // profile lists first-party bundles that will never carry hooks.
      continue;
    }
    const hooksPath = join(packageDir, "hooks", "hooks.json");
    if (existsSync(hooksPath)) found.push(hooksPath);
  }
  return found;
}

/**
 * Load every manifest that applies, in `config.manifests`-first order.
 *
 * @returns `[{ pluginRoot, manifestPath, hooks }]`. A manifest that will not
 *   parse is skipped with one loud line — never a boot failure, because a
 *   broken module must not cost the user their harness.
 */
export function loadManifests({ manifests = [], profileDir = undefined, baseDir = process.cwd(), warn }) {
  const paths = manifests.map((entry) => manifestPathOf(entry, baseDir));
  if (profileDir) paths.push(...autoDiscovered(profileDir, warn));
  const seen = new Set();
  const loaded = [];
  for (const path of paths) {
    let real;
    try {
      real = realpathSync(path);
    } catch {
      warn(`manifest ${path} does not exist; its module's hooks will not run`);
      continue;
    }
    if (seen.has(real)) continue;
    seen.add(real);
    try {
      const hooks = JSON.parse(readFileSync(real, "utf8"))?.hooks ?? {};
      // ${CLAUDE_PLUGIN_ROOT} is "the module directory owning the hooks.json",
      // i.e. the parent of hooks/.
      loaded.push({ pluginRoot: dirname(dirname(real)), manifestPath: real, hooks });
    } catch (error) {
      warn(`manifest ${real} did not parse, so its hooks are skipped: ${error}`);
    }
  }
  return loaded;
}

/**
 * Every command handler registered for `event` whose matcher accepts `names`,
 * in manifest order then declaration order — the order the contract's
 * "first deny wins" depends on.
 *
 * @param names - `null` for the events that carry no tool (SessionStart,
 *   UserPromptSubmit, Stop); their entries have no meaningful matcher.
 */
export function collectHandlers(loaded, event, names, warn, matchesMatcher) {
  const handlers = [];
  for (const { pluginRoot, manifestPath, hooks } of loaded) {
    for (const entry of hooks?.[event] ?? []) {
      if (names !== null && !matchesMatcher(entry?.matcher, names)) continue;
      for (const handler of entry?.hooks ?? []) {
        if (handler?.type !== "command" || typeof handler.command !== "string") {
          warn(`${manifestPath}: ${event} handler of type ${JSON.stringify(handler?.type)} is Claude-only and was skipped`);
          continue;
        }
        handlers.push({
          command: handler.command,
          timeoutMs: typeof handler.timeout === "number" ? handler.timeout * 1000 : undefined,
          pluginRoot,
        });
      }
    }
  }
  return handlers;
}

/** This file's directory — the walk-up anchor for {@link findProfileDir}. */
export const selfDir = dirname(fileURLToPath(import.meta.url));
