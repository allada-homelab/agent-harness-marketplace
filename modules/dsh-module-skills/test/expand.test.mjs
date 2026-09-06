// Argument substitution. dsh has none of this: the `/` menu only types
// `/<name> ` into the composer (@deepseek-ai/dsh-client-ui-skill lib/client.js,
// the trigger source's `onPick`), and the server matches the bare gesture
// (@deepseek-ai/dsh-tool-skill lib/index.js:352) and injects the body verbatim
// (:163). Everything below is behavior this module adds.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { splitArgs, expandArguments, usesArguments } from '../lib/expand.js';

test('quoted arguments are one word each', () => {
  assert.deepEqual(splitArgs('one "two three" four'), ['one', 'two three', 'four']);
  assert.deepEqual(splitArgs("  'a b'   c  "), ['a b', 'c']);
  assert.deepEqual(splitArgs('say"no space"here'), ['sayno spacehere']);
  assert.deepEqual(splitArgs(''), []);
  assert.deepEqual(splitArgs('""'), ['']);
});

test('$ARGUMENTS is the whole argument string, trimmed', () => {
  assert.equal(expandArguments('Review $ARGUMENTS now.', '  a "b c" '), 'Review a "b c" now.');
  assert.equal(expandArguments('Review $ARGUMENTS.', ''), 'Review .');
});

test('$N is the N-th whitespace/quote-aware word', () => {
  assert.equal(expandArguments('$1 then $2', 'alpha "beta gamma"'), 'alpha then beta gamma');
  assert.equal(expandArguments('$2', 'a b'), 'b');
});

test('an unsupplied $N is left verbatim so bare invocation still reads', () => {
  // A body may legitimately mention $1 inside a shell snippet.
  assert.equal(expandArguments('run "$1" for $2', 'only'), 'run "only" for $2');
  assert.equal(expandArguments('echo $1', ''), 'echo $1');
});

test('${N:-default} falls back, and $FOO is never touched', () => {
  assert.equal(expandArguments('${1:-main} branch', ''), 'main branch');
  assert.equal(expandArguments('${1:-main} branch', 'dev'), 'dev branch');
  assert.equal(expandArguments('$HOME and ${PATH} and $ARGUMENTSX', 'x'), '$HOME and ${PATH} and $ARGUMENTSX');
});

test('a body with no token is not worth shadowing dsh\'s native path', () => {
  assert.ok(usesArguments('Do $ARGUMENTS'));
  assert.ok(usesArguments('Do $1'));
  assert.ok(usesArguments('Do ${2:-x}'));
  assert.ok(!usesArguments('Plain body with no tokens.'));
  assert.ok(!usesArguments('Set $HOME.'));
});

// Known, deliberate false positive: a dollar amount looks exactly like $N.
// `$5` in prose makes the skill command-registered, and a bare invocation
// leaves it verbatim (the passthrough rule above), so the model still reads
// the original text. Documented rather than hidden.
test('a dollar amount is indistinguishable from $N, and survives unexpanded', () => {
  assert.ok(usesArguments('Cost is $5 million.'));
  assert.equal(expandArguments('Cost is $5 million.', ''), 'Cost is $5 million.');
  assert.equal(expandArguments('Cost is $5 million.', 'a b c d e'), 'Cost is e million.');
});
