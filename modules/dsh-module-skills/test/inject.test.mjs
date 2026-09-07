// cordis throws `cannot get property "<svc>" without inject` for any service a
// plugin touches but did not declare. The stubbed ctx in the other tests hands
// `commands` straight in, so this is the only test that can see the gap — and
// it is the gap that shipped on 2026-09-06: skills listed, no /name commands,
// one stderr line per module at boot.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import plugin from '../lib/index.js';

test('inject declares every ctx service the plugin touches', async () => {
  const src = await readFile(new URL('../lib/index.js', import.meta.url), 'utf8');
  const touched = new Set([...src.matchAll(/ctx\.(?:get\?\.\(')?([a-z]+)/g)].map((m) => m[1]))
    .difference(new Set(['get', 'on', 'effect', 'logger', 'cmdlineArgs']));
  for (const svc of touched) {
    assert.ok(plugin.inject.includes(svc), `ctx.${svc} is used but not in inject (${plugin.inject.join(', ')})`);
  }
});
