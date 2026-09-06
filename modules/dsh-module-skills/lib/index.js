/**
 * @allada-homelab/dsh-module-skills — make a packaged module's `skills/`
 * directory visible to dsh.
 *
 * dsh's skill provider only knows fixed roots (`<project>/.dsh/skills`,
 * `<project>/.agents/skills`, `customSkillDirs`, `<dshHome>/skills`,
 * `<agentsHome>/skills` — dsh-skill-filesystem lib/index.js, `roots()`), so a
 * module installed with `dsh plugin add` ships skills nothing can see. This
 * plugin is the generic bridge: it registers one `ctx.skills` provider over
 * every module root it finds, and — only where it adds something dsh cannot do
 * — a `/name` command that substitutes `$ARGUMENTS` / `$N` before the body
 * reaches the model.
 *
 * Skills only. Nothing here spawns a process, reads a hook manifest, or gates
 * on trust: the plugin reads Markdown and hands text to two registries.
 *
 * Fails open and loud. A malformed skill drops with one line, an unreadable
 * root drops with one line, and `apply()` never throws — a broken module must
 * not stop a session from starting. Lines go to `process.stderr` because
 * `ctx.logger` does not reach journald on a service-managed dsh.
 */

import { readFile } from 'node:fs/promises';
import { resolveRoots } from './roots.js';
import { scanRoot, parseSkill } from './skills.js';
import { expandArguments, usesArguments } from './expand.js';

export const name = 'module-skills';
export const inject = ['skills'];

/**
 * Default provider label carried on every candidate this plugin contributes.
 * `config.providerName` overrides it, mirroring dsh-skill-filesystem's own
 * `providerName` config: dsh throws on a duplicate provider name within one
 * layer, so two rows of this plugin (one per content module) must not both
 * register as `module-skills`.
 */
const PROVIDER = 'module-skills';

/**
 * Discovery bucket and precedence. `rank` matches dsh's own
 * `BUNDLED_SKILL_RANK` (dsh-skill lib/types/index.d.ts) so that a project,
 * custom, or user skill of the same name (ranks 100-500) always wins over one
 * a module shipped.
 */
const SOURCE = 'custom';
const RANK = 600;

/** One-line failure reporting on the channel a service manager actually sees. */
function warn(message) {
  process.stderr.write(`${PROVIDER}: ${message}\n`);
}

/**
 * Mount the bridge.
 * @param {object} ctx - the cordis context (requires `ctx.skills`).
 * @param {object} config - `{dirs, profileDir?, autoDiscover?, commands?}`.
 */
export function apply(ctx, config = {}) {
  const provider = typeof config.providerName === 'string' && config.providerName !== ''
    ? config.providerName
    : PROVIDER;
  let roots = [];
  try {
    roots = resolveRoots(ctx, config, warn);
  } catch (error) {
    warn(`root resolution failed, no module skills are visible: ${String(error)}`);
  }

  // One provider over every root, not one per root: dsh throws on a duplicate
  // provider name within a layer, and per-root isolation is a property of the
  // scan loop below (a failing root drops itself), not of the registration.
  try {
    ctx.skills.registerProvider(() => ({
      name: provider,
      list: () => listCandidates(roots, provider),
      get: (candidate) => loadCandidate(candidate, provider),
    }));
  } catch (error) {
    warn(`provider registration failed, no module skills are visible: ${String(error)}`);
    return;
  }

  if (config.commands === false) return;
  // Command registration needs the bodies, so it is asynchronous. Cordis awaits
  // an async apply, and each `register()` returns an effect disposer bound to
  // this fiber, so unloading the plugin removes the commands with it.
  return registerCommands(ctx, roots).catch((error) => {
    warn(`command registration failed: ${String(error)}`);
  });
}

/** Scan every root once and build the merged candidate list. */
async function listCandidates(roots, provider = PROVIDER) {
  const candidates = [];
  const claimed = new Set();
  for (const root of roots) {
    let found;
    try {
      found = await scanRoot(root, warn);
    } catch (error) {
      warn(`skill root ${root} dropped: ${String(error)}`);
      continue;
    }
    for (const skill of found) {
      // Earlier roots win: `config.dirs` is explicit intent and precedes
      // auto-discovery, and dsh would otherwise see one name twice.
      if (claimed.has(skill.name)) {
        warn(`skill ${skill.name} at ${skill.path} dropped: a higher-precedence root already provides it`);
        continue;
      }
      claimed.add(skill.name);
      candidates.push(summaryOf(skill, { path: skill.path, directory: skill.directory }, provider));
    }
  }
  return candidates;
}

/** Shared candidate/definition shape; `resourceBase` is the skill's own dir. */
function summaryOf(skill, locator, provider = PROVIDER) {
  return {
    name: skill.name,
    description: skill.description,
    ...skill.whenToUse !== undefined ? { whenToUse: skill.whenToUse } : {},
    invocation: skill.invocation,
    source: SOURCE,
    provider,
    rank: RANK,
    locator,
    // The skill's own directory, so `./scripts/x.py` in a body resolves.
    resourceBase: { kind: 'directory', path: locator.directory },
    path: locator.path,
    ...skill.metadata !== undefined ? { metadata: skill.metadata } : {},
  };
}

/** Re-read a listed candidate's body at load time. */
async function loadCandidate(candidate, provider = PROVIDER) {
  const locator = candidate.locator;
  if (locator?.path === undefined) return undefined;
  let text;
  try {
    text = await readFile(locator.path, 'utf8');
  } catch (error) {
    if (error?.code !== 'ENOENT' && error?.code !== 'ENOTDIR') warn(`skill file ${locator.path} dropped: ${String(error)}`);
    return undefined;
  }
  const result = parseSkill(text);
  if (result.skill === undefined) {
    if (!result.skipped) warn(`skill file ${locator.path} dropped: ${result.reason}`);
    return undefined;
  }
  const { rank, locator: _locator, ...definition } = summaryOf(result.skill, locator, provider);
  return { ...definition, content: result.skill.content };
}

/**
 * Register a `/name` command for each user-invocable skill whose body uses an
 * argument token.
 *
 * Only those: dsh's native `/name` gesture already injects a token-free body
 * verbatim and does it better (it renders `<skill_content>` with the skill's
 * `resourceBase`), so shadowing it there would remove behavior instead of
 * adding any. A body containing `$ARGUMENTS` or `$N` is the case dsh cannot
 * serve, because nothing in its slash path substitutes anything.
 *
 * @param {object} ctx - the cordis context.
 * @param {string[]} roots - resolved skill roots.
 * @param {Function} [factory] - dsh's `createUserMessage`; imported when omitted.
 */
export async function registerCommands(ctx, roots, factory) {
  const commands = ctx.get?.('commands') ?? ctx.commands;
  if (commands?.register === undefined) return;

  const wanted = [];
  const claimed = new Set();
  for (const root of roots) {
    let found;
    try {
      found = await scanRoot(root, () => {}); // the provider's scan owns the warnings
    } catch {
      continue;
    }
    for (const skill of found) {
      if (!skill.invocation.userInvocable || !usesArguments(skill.content)) continue;
      if (claimed.has(skill.name)) {
        warn(`command /${skill.name} from ${skill.path} skipped: that name is already registered`);
        continue;
      }
      claimed.add(skill.name);
      wanted.push(skill);
    }
  }
  if (wanted.length === 0) return;

  // `Agent.followup` takes an IDENTIFIED, frozen message; only dsh can mint one
  // (`createUserMessage` stamps `id`/`role`, and the inbox rejects a message
  // without an identity). dsh-llm is resolvable from any profile through the
  // flat fallback `<dshHome>/profiles/node_modules`, but it is not a declared
  // dependency of this package, so the import is dynamic and its absence costs
  // only the commands — the provider above still publishes every skill.
  const createUserMessage = factory ?? await importCreateUserMessage();
  if (createUserMessage === undefined) return;

  for (const skill of wanted) {
    try {
      commands.register({
        name: skill.name,
        description: skill.description,
        ...skill.argumentHint !== undefined ? { input: { hint: skill.argumentHint } } : {},
        handler: (invocation) => runSkillCommand(skill, invocation, createUserMessage),
      });
    } catch (error) {
      // dsh owns the global command namespace; a collision is its call, not
      // ours, and the native `/name` gesture still reaches the skill.
      warn(`command /${skill.name} from ${skill.path} skipped: ${String(error)}`);
    }
  }
}

/** Borrow dsh's own message factory; `undefined` when it is not resolvable. */
async function importCreateUserMessage() {
  try {
    const { createUserMessage } = await import('@deepseek-ai/dsh-llm');
    if (typeof createUserMessage === 'function') return createUserMessage;
    warn('commands disabled: @deepseek-ai/dsh-llm exports no createUserMessage');
  } catch (error) {
    warn(`commands disabled: @deepseek-ai/dsh-llm is not resolvable: ${String(error)}`);
  }
  return undefined;
}

/**
 * Expand the skill body against the typed arguments and send it as the user
 * turn. `followup` is the same seam dsh's own `/goal` uses to put text in
 * front of the model (dsh-command-goal lib/index.js:99).
 */
export function runSkillCommand(skill, invocation, createUserMessage) {
  const text = expandArguments(skill.content, invocation.rawInput ?? '');
  try {
    invocation.agent.followup(createUserMessage({
      content: [{ type: 'text', text }],
      source: { kind: 'user' },
    }));
  } catch (error) {
    return { kind: 'error', text: `/${skill.name} could not be sent: ${String(error)}` };
  }
  return { kind: 'success' };
}

export default { name, inject, apply };
