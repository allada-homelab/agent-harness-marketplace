// The filesystem watcher: a skill added after boot must appear without a
// restart. Invalidation goes through `SkillProviderControl.invalidate`, and the
// watcher's cleanup seam is `SkillProviderControl.signal`
// (@deepseek-ai/dsh-skill lib/types/index.d.ts:190-195).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { apply, watchRoots } from '../lib/index.js';

const tmp = () => mkdtemp(join(tmpdir(), 'dsh-module-skills-watch-'));

/** Write `<root>/<name>/SKILL.md`. */
async function skill(root, name, frontmatter = `name: ${name}\ndescription: d`) {
  await mkdir(join(root, name), { recursive: true });
  await writeFile(join(root, name, 'SKILL.md'), `---\n${frontmatter}\n---\nBody.\n`);
}

/** A cordis stub whose provider control records every invalidation. */
function wire() {
  const providers = [];
  const invalidations = [];
  const errors = [];
  const aborts = [];
  const write = process.stderr.write.bind(process.stderr);
  process.stderr.write = (line) => { errors.push(String(line)); return true; };
  const ctx = {
    skills: {
      registerProvider(create) {
        const controller = new AbortController();
        aborts.push(controller);
        providers.push(create({ signal: controller.signal, invalidate: () => invalidations.push(Date.now()) }));
        return () => {};
      },
    },
    get(service) { return ctx[service]; },
  };
  return { ctx, providers, invalidations, errors, aborts, restore: () => { process.stderr.write = write; } };
}

/** Resolve once `predicate()` holds, or fail after `ms`. */
async function until(predicate, ms = 4000) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  assert.fail('timed out waiting for the watcher');
}

test('a skill added after boot invalidates the catalog and appears in the next list', async () => {
  const root = join(await tmp(), 'skills');
  await skill(root, 'first');
  const w = wire();
  try {
    await apply(w.ctx, { dirs: [root], autoDiscover: false, commands: false });
    assert.deepEqual((await w.providers[0].list({})).map((c) => c.name), ['first']);

    await skill(root, 'second');
    await until(() => w.invalidations.length > 0);

    assert.deepEqual((await w.providers[0].list({})).map((c) => c.name), ['first', 'second']);
  } finally {
    w.aborts[0]?.abort();
    w.restore();
  }
});

test('a burst of writes collapses into one invalidation', async () => {
  const root = join(await tmp(), 'skills');
  await mkdir(root, { recursive: true });
  const invalidations = [];
  const stop = watchRoots([root], () => invalidations.push(1), () => {}, 150);
  try {
    for (const name of ['a', 'b', 'c', 'd']) await skill(root, name);
    await until(() => invalidations.length > 0);
    await new Promise((resolve) => setTimeout(resolve, 400));
    assert.equal(invalidations.length, 1, 'the debounce must fold a burst into one rescan');
  } finally { stop(); }
});

test('an unwatchable root costs one line and keeps the plugin alive', () => {
  const lines = [];
  const stop = watchRoots(['/definitely/not/a/directory'], () => {}, (message) => lines.push(message));
  stop();
  assert.equal(lines.length, 1, JSON.stringify(lines));
  assert.match(lines[0], /is not watched, a new skill needs a restart/);
});

test('disposing the provider stops the watcher', async () => {
  const root = join(await tmp(), 'skills');
  await mkdir(root, { recursive: true });
  const w = wire();
  try {
    await apply(w.ctx, { dirs: [root], autoDiscover: false, commands: false });
    w.aborts[0].abort();
    await skill(root, 'late');
    await new Promise((resolve) => setTimeout(resolve, 500));
    assert.deepEqual(w.invalidations, [], 'a disposed provider must not keep invalidating');
  } finally { w.restore(); }
});
