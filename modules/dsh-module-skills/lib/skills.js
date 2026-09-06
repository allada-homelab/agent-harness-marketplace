/**
 * Directory-bundle skill discovery for one packaged module root.
 *
 * Only `<root>/<name>/SKILL.md` is discovered. A flat `<root>/<name>.md` is
 * deliberately ignored: dsh's own filesystem provider gives a flat file the
 * ROOT as its `resourceBase` (dsh-skill-filesystem lib/index.js, `discoverRoot`
 * — `directory: root.path`), so every `./scripts/x.py` in such a skill would
 * resolve against a directory it does not own. Content modules ship bundles.
 */

import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { parseFrontmatter } from './frontmatter.js';

/** dsh's own skill-name grammar (dsh-skill lib/index.js:17). */
const SKILL_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** Whether a name is addressable as a dsh skill. */
export function isSkillName(name) {
  return typeof name === 'string' && SKILL_NAME.test(name);
}

/**
 * Read one front-matter boolean the way dsh does, without throwing.
 * @returns {boolean | undefined | null} the value, `undefined` when absent, or
 *   `null` when present but not boolean-shaped (the caller drops the skill).
 */
function frontmatterBoolean(data, key) {
  if (!Object.hasOwn(data, key)) return undefined;
  const value = data[key];
  if (typeof value === 'boolean') return value;
  if (value === 1 || value === '1') return true;
  if (value === 0 || value === '0') return false;
  if (typeof value === 'string') {
    switch (value.toLowerCase()) {
      case 'true': case 'yes': case 'on': return true;
      case 'false': case 'no': case 'off': return false;
      default: return null;
    }
  }
  return null;
}

/**
 * Whether this repo's `harness:` convention admits dsh. The key is invisible
 * to every harness's own loader; honoring it here is the whole point of the
 * bridge — a claude-only skill must not reach a dsh catalog.
 */
export function admitsDsh(data) {
  const value = data.harness;
  if (value === undefined || value === null) return true;
  const list = Array.isArray(value) ? value : [value];
  return list.some((item) => typeof item === 'string' && item.trim().toLowerCase() === 'dsh');
}

/**
 * Parse one SKILL.md into the fields a dsh candidate needs.
 * @param {string} text - complete SKILL.md text.
 * @returns {{skill?: object, reason?: string, skipped?: boolean}} the parsed
 *   skill, or a `reason` the caller logs, or `skipped` for a harness filter.
 */
export function parseSkill(text) {
  const parsed = parseFrontmatter(text);
  if (parsed === undefined) return { reason: 'missing YAML frontmatter' };
  const { data, body } = parsed;
  if (!admitsDsh(data)) return { skipped: true };

  const name = typeof data.name === 'string' ? data.name.trim() : '';
  const description = typeof data.description === 'string' ? data.description.trim() : '';
  if (name === '' || description === '') return { reason: 'frontmatter requires name and description' };
  if (!isSkillName(name)) return { reason: `invalid skill name "${name}"` };

  const disableModel = frontmatterBoolean(data, 'disable-model-invocation');
  const userInvocable = frontmatterBoolean(data, 'user-invocable');
  if (disableModel === null || userInvocable === null) {
    return { reason: 'disable-model-invocation and user-invocable must be booleans' };
  }

  const metadata = typeof data.metadata === 'object' && data.metadata !== null && !Array.isArray(data.metadata)
    ? data.metadata
    : undefined;
  const hint = typeof data['argument-hint'] === 'string' && data['argument-hint'].trim() !== ''
    ? data['argument-hint'].trim()
    : undefined;

  return {
    skill: {
      name,
      description,
      ...typeof data.whenToUse === 'string' && data.whenToUse.trim() !== '' ? { whenToUse: data.whenToUse.trim() } : {},
      // dsh hard-rejects the camelCase legacy spellings on the way in; these
      // are the resolved policy booleans its API asks for, not frontmatter.
      invocation: { modelInvocable: disableModel !== true, userInvocable: userInvocable !== false },
      ...metadata !== undefined ? { metadata } : {},
      ...hint !== undefined ? { argumentHint: hint } : {},
      content: body.trim(),
    },
  };
}

/**
 * Scan one `skills/` root for directory-bundle skills.
 * @param {string} root - absolute path of a `<module>/skills` directory.
 * @param {(message: string) => void} warn - one-line failure reporter.
 * @returns {Promise<object[]>} parsed skills, each with `path` and `directory`.
 */
export async function scanRoot(root, warn) {
  let entries;
  try {
    entries = await readdir(root, { withFileTypes: true, encoding: 'utf8' });
  } catch (error) {
    // A root that vanished is not an error worth a line; anything else is.
    if (error?.code !== 'ENOENT' && error?.code !== 'ENOTDIR') {
      warn(`skill root ${root} dropped: ${String(error)}`);
    }
    return [];
  }

  const found = [];
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    if (!entry.isDirectory() && !entry.isSymbolicLink()) continue;
    const directory = join(root, entry.name);
    const path = join(directory, 'SKILL.md');
    let text;
    try {
      text = await readFile(path, 'utf8');
    } catch (error) {
      if (error?.code !== 'ENOENT' && error?.code !== 'ENOTDIR') warn(`skill file ${path} dropped: ${String(error)}`);
      continue;
    }
    let result;
    try {
      result = parseSkill(text);
    } catch (error) {
      warn(`skill file ${path} dropped: ${String(error)}`);
      continue;
    }
    if (result.skipped) continue;
    if (result.skill === undefined) {
      warn(`skill file ${path} dropped: ${result.reason}`);
      continue;
    }
    found.push({ ...result.skill, path, directory });
  }
  return found;
}
