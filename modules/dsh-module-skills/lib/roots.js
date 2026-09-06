/**
 * Where a packaged module's `skills/` directory lives, and how to find it.
 *
 * dsh's own provider only ever looks at fixed roots — `<project>/.dsh/skills`,
 * `<project>/.agents/skills`, `customSkillDirs`, `<dshHome>/skills`,
 * `<agentsHome>/skills` (dsh-skill-filesystem lib/index.js, `roots()`). An
 * installed profile package's `skills/` directory is invisible to all of them.
 * This resolver supplies the missing roots from two sources:
 *
 *   1. `config.dirs` — absolute paths, for a checkout or a dotfiles tree.
 *   2. auto-discovery — every package named in the profile manifest's
 *      `dsh.profile.bundles` that actually ships a `skills/` directory.
 *
 * The profile directory is `ctx.baseUrl`: dsh boots a profile by calling
 * `boot(NAME, <profileDir>/cordis.root.yml, ...)`, which sets
 * `ctx.baseUrl = pathToFileURL(dirname(absoluteConfigPath))` (dsh-app-boot
 * lib/index.js:1171), and `dsh plugin` installs into that same directory
 * (`resolveProfileDir` :318 = `<dshHome>/profiles/<name>`).
 */

import { createRequire } from 'node:module';
import { existsSync, readFileSync, realpathSync, statSync } from 'node:fs';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

/** Whether a path is an existing directory. */
function isDirectory(path) {
  try {
    return statSync(path).isDirectory();
  } catch {
    return false;
  }
}

/**
 * Resolve the profile directory a plugin was mounted from.
 * @param {object} ctx - the cordis context.
 * @param {object} config - plugin config; `profileDir` overrides discovery.
 * @returns {string | undefined} the absolute profile directory.
 */
export function profileDirOf(ctx, config = {}) {
  if (typeof config.profileDir === 'string' && config.profileDir !== '') return resolve(config.profileDir);
  const baseUrl = ctx?.baseUrl;
  if (typeof baseUrl !== 'string' || !baseUrl.startsWith('file:')) return undefined;
  try {
    return fileURLToPath(baseUrl);
  } catch {
    return undefined;
  }
}

/**
 * Locate the `skills/` directories of every bundle the profile mounts.
 * @param {string | undefined} profileDir - absolute profile directory.
 * @param {(message: string) => void} warn - one-line failure reporter.
 * @param {string[] | undefined} only - when set, the only bundle names considered.
 * @returns {string[]} absolute `skills` directories, in manifest order.
 */
export function discoverBundleSkillDirs(profileDir, warn, only) {
  if (profileDir === undefined) return [];
  const manifestPath = join(profileDir, 'package.json');
  let bundles;
  try {
    bundles = JSON.parse(readFileSync(manifestPath, 'utf8'))?.dsh?.profile?.bundles;
  } catch (error) {
    if (error?.code !== 'ENOENT') warn(`profile manifest ${manifestPath} unreadable: ${String(error)}`);
    return [];
  }
  if (!Array.isArray(bundles)) return [];

  const require = createRequire(manifestPath);
  const dirs = [];
  const wanted = Array.isArray(only) && only.length > 0 ? new Set(only) : undefined;
  for (const bundle of bundles) {
    if (typeof bundle !== 'string' || bundle === '') continue;
    if (wanted !== undefined && !wanted.has(bundle)) continue;
    const packageDir = resolvePackageDir(require, bundle);
    if (packageDir === undefined) continue;
    const skills = join(packageDir, 'skills');
    if (isDirectory(skills)) dirs.push(skills);
  }
  return dirs;
}

/** Resolve an installed package's directory without requiring its main entry. */
function resolvePackageDir(require, name) {
  try {
    return dirname(require.resolve(`${name}/package.json`));
  } catch { /* the package may not export its manifest */ }
  try {
    let dir = dirname(require.resolve(name));
    while (!existsSync(join(dir, 'package.json'))) {
      const parent = dirname(dir);
      if (parent === dir) return undefined;
      dir = parent;
    }
    return dir;
  } catch {
    return undefined;
  }
}

/**
 * Compose every skill root this plugin serves, deduped by realpath so a
 * `config.dirs` entry and an auto-discovered bundle that are the same
 * directory (a pnpm link, a symlinked dotfiles checkout) register once.
 * @param {object} ctx - the cordis context.
 * @param {object} config - plugin config (`dirs`, `bundles`, `profileDir`, `autoDiscover`).
 * @param {(message: string) => void} warn - one-line failure reporter.
 * @returns {string[]} absolute, deduped skill roots.
 */
export function resolveRoots(ctx, config = {}, warn = () => {}) {
  const configured = Array.isArray(config.dirs) ? config.dirs : [];
  const explicit = [];
  for (const dir of configured) {
    if (typeof dir !== 'string' || dir === '') continue;
    if (!isAbsolute(dir)) {
      warn(`config.dirs entry ${JSON.stringify(dir)} dropped: must be an absolute path`);
      continue;
    }
    explicit.push(resolve(dir));
  }
  const discovered = config.autoDiscover === false
    ? []
    : discoverBundleSkillDirs(profileDirOf(ctx, config), warn, config.bundles);

  const seen = new Set();
  const roots = [];
  for (const dir of [...explicit, ...discovered]) {
    let key;
    try {
      key = realpathSync(dir);
    } catch {
      key = dir;
    }
    if (seen.has(key)) continue;
    seen.add(key);
    roots.push(key);
  }
  return roots;
}
