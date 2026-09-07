// cordis throws `cannot get property "<svc>" without inject` for any service a
// plugin touches but did not declare, and `?.` cannot guard the access itself.
// The stubbed ctx in the other tests hands services straight in, so this is the
// only test that can see the gap (it shipped once in dsh-module-skills).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import * as plugin from '../lib/index.js';

test('inject declares every ctx service the plugin touches', async () => {
  const src = await readFile(new URL('../lib/index.js', import.meta.url), 'utf8');
  const core = new Set(['get', 'on', 'once', 'off', 'emit', 'effect', 'logger', 'cmdlineArgs', 'root', 'scope', 'plugin', 'inject', 'name', 'reflect', 'fiber', 'runtime']);
  const touched = new Set([...src.matchAll(/ctx\.(?:get\?\.\(')?([a-zA-Z]+)/g)].map((m) => m[1]).filter((s) => !core.has(s)));
  for (const svc of touched) {
    assert.ok(plugin.inject?.includes(svc), `ctx.${svc} is used but not in inject (${(plugin.inject ?? []).join(', ') || 'none'})`);
  }
});
