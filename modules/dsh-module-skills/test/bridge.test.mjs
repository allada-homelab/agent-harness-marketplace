// Root resolution and the two registrations, exercised through `apply()`.
//
// The ctx here is a stub of the two seams this plugin touches:
//   ctx.skills.registerProvider(create)  — @deepseek-ai/dsh-skill
//                                          lib/types/index.d.ts:249
//   ctx.commands.register(definition)    — @deepseek-ai/dsh-commands
//                                          lib/types/index.d.ts (CommandDefinition)
// `ctx.baseUrl` is the profile directory: dsh boots a profile through
// `boot(NAME, <profileDir>/cordis.root.yml, …)`, which sets
// `ctx.baseUrl = pathToFileURL(dirname(configPath))` — @deepseek-ai/dsh-app-boot
// lib/index.js:1171.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, symlink, chmod } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { apply } from '../lib/index.js';
import { resolveRoots } from '../lib/roots.js';

const tmp = () => mkdtemp(join(tmpdir(), 'dsh-module-skills-'));

/** Write `<root>/<name>/SKILL.md`. */
async function skill(root, name, frontmatter, body = 'Body.') {
  await mkdir(join(root, name), { recursive: true });
  await writeFile(join(root, name, 'SKILL.md'), `---\n${frontmatter}\n---\n${body}\n`);
}

/** A cordis context stub plus captured stderr. */
function wire(baseDir) {
  const providers = [];
  const commands = [];
  const errors = [];
  const write = process.stderr.write.bind(process.stderr);
  process.stderr.write = (line) => { errors.push(String(line)); return true; };
  const ctx = {
    baseUrl: baseDir === undefined ? undefined : `${pathToFileURL(baseDir).href}/`,
    skills: {
      registerProvider(create) {
        providers.push(create({ signal: new AbortController().signal, invalidate() {} }));
        return () => {};
      },
    },
    commands: {
      register(definition) { commands.push(definition); return () => {}; },
    },
    get(service) { return ctx[service]; },
  };
  return { ctx, providers, commands, errors, restore: () => { process.stderr.write = write; } };
}

test('an installed module\'s skills/ dir becomes a dsh provider catalog', async () => {
  const dir = await tmp();
  const root = join(dir, 'mod', 'skills');
  await skill(root, 'do-thing', 'name: do-thing\ndescription: Does the thing.\nmetadata:\n  owner: platform');
  const w = wire();
  try {
    await apply(w.ctx, { dirs: [root] });
    assert.equal(w.providers.length, 1, 'exactly one provider registers');
    const candidates = await w.providers[0].list({});
    assert.equal(candidates.length, 1);
    const [candidate] = candidates;
    assert.equal(candidate.name, 'do-thing');
    assert.equal(candidate.description, 'Does the thing.');
    assert.deepEqual(candidate.invocation, { modelInvocable: true, userInvocable: true });
    assert.deepEqual(candidate.metadata, { owner: 'platform' });
    // resourceBase is the skill's OWN directory, so ./scripts/x.py resolves.
    assert.deepEqual(candidate.resourceBase, { kind: 'directory', path: join(root, 'do-thing') });
    // Rank 600 = dsh's BUNDLED_SKILL_RANK: project/user skills outrank a module's.
    assert.equal(candidate.rank, 600);

    const definition = await w.providers[0].get(candidate, {});
    assert.equal(definition.content, 'Body.');
    assert.equal(definition.rank, undefined, 'rank is a candidate field, not a definition field');
    assert.equal(definition.locator, undefined);
  } finally { w.restore(); }
});

test('a flat <root>/<name>.md is ignored, not given the root as its resource base', async () => {
  const dir = await tmp();
  const root = join(dir, 'skills');
  await mkdir(root, { recursive: true });
  await writeFile(join(root, 'flat.md'), '---\nname: flat\ndescription: d\n---\nBody.\n');
  const w = wire();
  try {
    await apply(w.ctx, { dirs: [root] });
    assert.deepEqual(await w.providers[0].list({}), []);
  } finally { w.restore(); }
});

test('a claude-only skill never reaches the dsh catalog', async () => {
  const dir = await tmp();
  const root = join(dir, 'skills');
  await skill(root, 'claude-only', 'name: claude-only\ndescription: d\nharness: [claude]');
  await skill(root, 'shared', 'name: shared\ndescription: d\nharness: [claude, pi, dsh]');
  const w = wire();
  try {
    await apply(w.ctx, { dirs: [root] });
    assert.deepEqual((await w.providers[0].list({})).map((c) => c.name), ['shared']);
  } finally { w.restore(); }
});

test('roots are deduped by realpath, so a symlinked checkout registers once', async () => {
  const dir = await tmp();
  const real = join(dir, 'real', 'skills');
  await mkdir(real, { recursive: true });
  const link = join(dir, 'linked');
  await symlink(join(dir, 'real'), link);
  const roots = resolveRoots({}, { dirs: [real, join(link, 'skills'), real] }, () => {});
  assert.deepEqual(roots.length, 1, `expected one root, got ${JSON.stringify(roots)}`);
});

test('a relative config.dirs entry is refused with one line', () => {
  const lines = [];
  const roots = resolveRoots({}, { dirs: ['relative/skills'], autoDiscover: false }, (m) => lines.push(m));
  assert.deepEqual(roots, []);
  assert.equal(lines.length, 1);
  assert.match(lines[0], /absolute path/);
});

test('auto-discovery finds every profile bundle that ships a skills/ dir', async () => {
  const dir = await tmp();
  const profile = join(dir, 'profiles', 'web');
  const withSkills = join(profile, 'node_modules', '@scope', 'content-module');
  const without = join(profile, 'node_modules', '@scope', 'plain-plugin');
  await mkdir(join(withSkills, 'skills'), { recursive: true });
  await mkdir(without, { recursive: true });
  await writeFile(join(withSkills, 'package.json'), JSON.stringify({ name: '@scope/content-module', version: '1.0.0' }));
  await writeFile(join(without, 'package.json'), JSON.stringify({ name: '@scope/plain-plugin', version: '1.0.0' }));
  await writeFile(join(profile, 'package.json'), JSON.stringify({
    name: 'dsh-profile-web',
    dsh: { profile: { bundles: ['@scope/content-module', '@scope/plain-plugin', '@scope/not-installed'] } },
  }));
  const lines = [];
  const roots = resolveRoots({ baseUrl: `${pathToFileURL(profile).href}/` }, {}, (m) => lines.push(m));
  assert.deepEqual(roots, [join(withSkills, 'skills')]);
  assert.deepEqual(lines, [], 'a bundle without skills/ is ordinary, not a failure');
});

test('a profile with no manifest yields no roots and no noise', () => {
  const lines = [];
  assert.deepEqual(resolveRoots({ baseUrl: pathToFileURL(tmpdir()).href + '/' }, {}, (m) => lines.push(m)), []);
  assert.deepEqual(lines, []);
});

test('a broken root drops with one line and the good root still publishes', async () => {
  const dir = await tmp();
  const good = join(dir, 'good', 'skills');
  const broken = join(dir, 'broken', 'skills');
  await skill(good, 'fine', 'name: fine\ndescription: d');
  await mkdir(broken, { recursive: true });
  await skill(broken, 'unreadable', 'name: unreadable\ndescription: d');
  await chmod(broken, 0o000);
  const w = wire();
  try {
    await apply(w.ctx, { dirs: [broken, good], autoDiscover: false });
    const names = (await w.providers[0].list({})).map((c) => c.name);
    assert.deepEqual(names, ['fine'], 'a broken root must not take the whole catalog with it');
    assert.equal(w.errors.length, 1, `expected exactly one line, got ${JSON.stringify(w.errors)}`);
    assert.match(w.errors[0], /^module-skills: skill root .*broken/);
  } finally {
    w.restore();
    await chmod(broken, 0o755);
  }
});

test('a malformed skill drops with one line and its siblings survive', async () => {
  const dir = await tmp();
  const root = join(dir, 'skills');
  await skill(root, 'good', 'name: good\ndescription: d');
  await skill(root, 'nameless', 'description: d');
  await mkdir(join(root, 'empty'), { recursive: true });
  const w = wire();
  try {
    await apply(w.ctx, { dirs: [root], autoDiscover: false });
    assert.deepEqual((await w.providers[0].list({})).map((c) => c.name), ['good']);
    assert.equal(w.errors.length, 1, JSON.stringify(w.errors));
    assert.match(w.errors[0], /nameless.*requires name and description/);
  } finally { w.restore(); }
});

test('apply() never throws out of a broken registry', async () => {
  const w = wire();
  try {
    const hostile = {
      baseUrl: undefined,
      skills: { registerProvider() { throw new Error('duplicate provider name'); } },
      get() { return undefined; },
    };
    await apply(hostile, { dirs: [], autoDiscover: false });
    assert.match(w.errors.join(''), /provider registration failed/);
  } finally { w.restore(); }
});

test('config.bundles narrows auto-discovery to one module\'s own package', async () => {
  const dir = await tmp();
  const profile = join(dir, 'profiles', 'web');
  const mine = join(profile, 'node_modules', '@scope', 'mine');
  const other = join(profile, 'node_modules', '@scope', 'other');
  await mkdir(join(mine, 'skills'), { recursive: true });
  await mkdir(join(other, 'skills'), { recursive: true });
  await writeFile(join(mine, 'package.json'), JSON.stringify({ name: '@scope/mine' }));
  await writeFile(join(other, 'package.json'), JSON.stringify({ name: '@scope/other' }));
  await writeFile(join(profile, 'package.json'), JSON.stringify({
    dsh: { profile: { bundles: ['@scope/mine', '@scope/other'] } },
  }));
  const ctx = { baseUrl: `${pathToFileURL(profile).href}/` };
  assert.deepEqual(resolveRoots(ctx, { bundles: ['@scope/mine'] }, () => {}), [join(mine, 'skills')]);
  assert.equal(resolveRoots(ctx, {}, () => {}).length, 2, 'no narrowing serves every bundle');
});
