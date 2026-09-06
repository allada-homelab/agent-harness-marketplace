// Slash-command registration and dispatch.
//
// Why these commands exist at all: dsh's own slash path does NOT pass
// arguments into a skill body. The `/` menu types `/<name> ` into the composer
// (@deepseek-ai/dsh-client-ui-skill lib/client.js, the trigger source's
// `onPick`); the server then matches the bare gesture
// `(^|\s)\/([a-z0-9]+(?:-[a-z0-9]+)*)(?=\s|$)` (@deepseek-ai/dsh-tool-skill
// lib/index.js:352) and injects the body verbatim through `renderSkillContent`
// (:163-170). The user's words ride only as their own plain message.
//
// The dispatch shape is dsh's: `CommandDefinition.handler` receives
// `{agent, rawInput, …}` and returns a `CommandResult`
// (@deepseek-ai/dsh-commands lib/types/index.d.ts + types.d.ts), and text
// reaches the model through `agent.followup(createUserMessage(...))` — the same
// seam `/goal` uses (@deepseek-ai/dsh-command-goal lib/index.js:99).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { registerCommands } from '../lib/index.js';

const tmp = () => mkdtemp(join(tmpdir(), 'dsh-module-skills-cmd-'));

async function skill(root, name, frontmatter, body) {
  await mkdir(join(root, name), { recursive: true });
  await writeFile(join(root, name, 'SKILL.md'), `---\n${frontmatter}\n---\n${body}\n`);
}

/** A stub factory, so the identity assertions elsewhere can name an exact id. */
const createUserMessage = (input) => ({ ...input, id: 'msg-1', role: 'user' });

function wire(overrides = {}) {
  const registered = [];
  const errors = [];
  const write = process.stderr.write.bind(process.stderr);
  process.stderr.write = (line) => { errors.push(String(line)); return true; };
  const ctx = {
    commands: { register: (definition) => { registered.push(definition); return () => {}; }, ...overrides },
    get(service) { return ctx[service]; },
  };
  return { ctx, registered, errors, restore: () => { process.stderr.write = write; } };
}

/** Capture what one command's handler sends to the agent. */
function invoke(definition, rawInput) {
  const sent = [];
  const agent = { followup: (message) => sent.push(message) };
  const result = definition.handler({ agent, rawInput, attachments: [], signal: new AbortController().signal });
  return { result, text: sent[0]?.content?.[0]?.text, sent };
}

test('only a body that uses arguments gets a command; dsh already serves the rest', async () => {
  const root = join(await tmp(), 'skills');
  await skill(root, 'with-args', 'name: with-args\ndescription: d', 'Review $ARGUMENTS.');
  await skill(root, 'plain', 'name: plain\ndescription: d', 'No tokens here.');
  const w = wire();
  try {
    await registerCommands(w.ctx, [root], createUserMessage);
    assert.deepEqual(w.registered.map((c) => c.name), ['with-args']);
  } finally { w.restore(); }
});

test('a user-invocable: false skill gets no command', async () => {
  const root = join(await tmp(), 'skills');
  await skill(root, 'model-only', 'name: model-only\ndescription: d\nuser-invocable: false', 'Use $ARGUMENTS.');
  const w = wire();
  try {
    await registerCommands(w.ctx, [root], createUserMessage);
    assert.deepEqual(w.registered, []);
  } finally { w.restore(); }
});

test('argument-hint becomes the command input hint dsh advertises', async () => {
  const root = join(await tmp(), 'skills');
  await skill(root, 'review', 'name: review\ndescription: Review a PR.\nargument-hint: <pr-url>', 'Review $ARGUMENTS.');
  const w = wire();
  try {
    await registerCommands(w.ctx, [root], createUserMessage);
    assert.deepEqual(w.registered[0].input, { hint: '<pr-url>' });
    assert.equal(w.registered[0].description, 'Review a PR.');
  } finally { w.restore(); }
});

test('the handler sends the expanded body as the user turn', async () => {
  const root = join(await tmp(), 'skills');
  await skill(root, 'review', 'name: review\ndescription: d', 'Review $1 against $ARGUMENTS.');
  const w = wire();
  try {
    await registerCommands(w.ctx, [root], createUserMessage);
    const { result, text, sent } = invoke(w.registered[0], 'main "two words"');
    assert.deepEqual(result, { kind: 'success' });
    assert.equal(text, 'Review main against main "two words".');
    assert.equal(sent[0].source.kind, 'user');
    assert.equal(sent[0].id, 'msg-1', 'the message must carry dsh-minted identity');
  } finally { w.restore(); }
});

test('a bare invocation leaves an unsupplied token verbatim', async () => {
  const root = join(await tmp(), 'skills');
  await skill(root, 'review', 'name: review\ndescription: d', 'Check $1.');
  const w = wire();
  try {
    await registerCommands(w.ctx, [root], createUserMessage);
    assert.equal(invoke(w.registered[0], '').text, 'Check $1.');
  } finally { w.restore(); }
});

test('a duplicate name across two roots is skipped with one line', async () => {
  const first = join(await tmp(), 'skills');
  const second = join(await tmp(), 'skills');
  await skill(first, 'review', 'name: review\ndescription: first', 'A $ARGUMENTS');
  await skill(second, 'review', 'name: review\ndescription: second', 'B $ARGUMENTS');
  const w = wire();
  try {
    await registerCommands(w.ctx, [first, second], createUserMessage);
    assert.equal(w.registered.length, 1);
    assert.equal(w.registered[0].description, 'first', 'the earlier root wins');
    assert.equal(w.errors.length, 1, JSON.stringify(w.errors));
    assert.match(w.errors[0], /command \/review .* skipped: that name is already registered/);
  } finally { w.restore(); }
});

test('a host-side name collision drops that command and nothing else', async () => {
  const root = join(await tmp(), 'skills');
  await skill(root, 'compact', 'name: compact\ndescription: d', 'A $ARGUMENTS');
  await skill(root, 'zeta', 'name: zeta\ndescription: d', 'B $ARGUMENTS');
  const w = wire({
    register(definition) {
      if (definition.name === 'compact') throw new Error('command "compact" already registered');
      return () => {};
    },
  });
  try {
    await registerCommands(w.ctx, [root], createUserMessage);
    assert.equal(w.errors.length, 1, JSON.stringify(w.errors));
    assert.match(w.errors[0], /command \/compact .* already registered/);
  } finally { w.restore(); }
});

test('a host with no commands service is not an error', async () => {
  const root = join(await tmp(), 'skills');
  await skill(root, 'review', 'name: review\ndescription: d', 'A $ARGUMENTS');
  const w = wire();
  try {
    await registerCommands({ get: () => undefined }, [root], createUserMessage);
    assert.deepEqual(w.errors, []);
  } finally { w.restore(); }
});

test('a failing followup settles as an error result, never a throw', async () => {
  const root = join(await tmp(), 'skills');
  await skill(root, 'review', 'name: review\ndescription: d', 'A $ARGUMENTS');
  const w = wire();
  try {
    await registerCommands(w.ctx, [root], createUserMessage);
    const agent = { followup() { throw new Error('agent is disposed'); } };
    const result = w.registered[0].handler({ agent, rawInput: 'x', attachments: [] });
    assert.equal(result.kind, 'error');
    assert.match(result.text, /agent is disposed/);
  } finally { w.restore(); }
});

test('the default message factory mints the shape followup requires', async () => {
  const root = join(await tmp(), 'skills');
  await skill(root, 'review', 'name: review\ndescription: d', 'Review $ARGUMENTS.');
  const w = wire();
  try {
    // No factory: this is the `link:`-install path, where importing
    // @deepseek-ai/dsh-llm used to fail and drop every command silently.
    await registerCommands(w.ctx, [root]);
    assert.equal(w.registered.length, 1, JSON.stringify(w.errors));
    const { result, sent } = invoke(w.registered[0], 'main');
    assert.deepEqual(result, { kind: 'success' });
    assert.equal(sent[0].role, 'user');
    assert.match(sent[0].id, /^[0-9a-f-]{36}$/, 'followup rejects a message without an identity');
    assert.deepEqual(sent[0].content, [{ type: 'text', text: 'Review main.' }]);
    assert.deepEqual(sent[0].source, { kind: 'user' });
    assert.ok(Object.isFrozen(sent[0]), 'a published message is frozen');
  } finally { w.restore(); }
});

test('metadata dsh-command false keeps a prose dollar amount off the command surface', async () => {
  const root = join(await tmp(), 'skills');
  await skill(root, 'budget', 'name: budget\ndescription: d\nmetadata:\n  dsh-command: false', 'We raised $5 million.');
  const w = wire();
  try {
    await registerCommands(w.ctx, [root], createUserMessage);
    assert.deepEqual(w.registered, []);
  } finally { w.restore(); }
});

test('metadata dsh-command true registers a token-free body', async () => {
  const root = join(await tmp(), 'skills');
  await skill(root, 'plain', 'name: plain\ndescription: d\nmetadata:\n  dsh-command: true', 'No tokens here.');
  const w = wire();
  try {
    await registerCommands(w.ctx, [root], createUserMessage);
    assert.deepEqual(w.registered.map((c) => c.name), ['plain']);
  } finally { w.restore(); }
});

test('a non-boolean dsh-command falls back to token detection, loudly', async () => {
  const root = join(await tmp(), 'skills');
  await skill(root, 'review', 'name: review\ndescription: d\nmetadata:\n  dsh-command: maybe', 'Review $ARGUMENTS.');
  const w = wire();
  try {
    await registerCommands(w.ctx, [root], createUserMessage);
    assert.deepEqual(w.registered.map((c) => c.name), ['review']);
    assert.equal(w.errors.length, 1, JSON.stringify(w.errors));
    assert.match(w.errors[0], /metadata\.dsh-command must be true or false/);
  } finally { w.restore(); }
});
