// The front-matter parser and the skill fields dsh actually consumes.
// The shapes asserted here are dsh's, not this module's: see
// @deepseek-ai/dsh-skill-filesystem lib/index.js `parseSkillFile` /
// `parseInvocationPolicy` (name+description required, `user-invocable` and
// `disable-model-invocation` boolean-ish, `metadata` an object) and
// @deepseek-ai/dsh-skill lib/index.js:17 for the name grammar.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseFrontmatter } from '../lib/frontmatter.js';
import { parseSkill, admitsDsh, isSkillName } from '../lib/skills.js';

const doc = (fm, body = 'Body.') => `---\n${fm}\n---\n${body}\n`;

test('a file without front matter is not a skill', () => {
  assert.equal(parseFrontmatter('# Just a heading\n'), undefined);
  assert.equal(parseSkill('# Just a heading\n').reason, 'missing YAML frontmatter');
});

test('an unterminated front matter block is not a skill', () => {
  assert.equal(parseFrontmatter('---\nname: x\n'), undefined);
});

test('scalars, quotes, comments and CRLF line endings', () => {
  const { data, body } = parseFrontmatter(
    '---\r\nname: do-thing\r\ndescription: "A: colon, inside"\r\nuser-invocable: true # trailing\r\n---\r\nBody\r\n',
  );
  assert.equal(data.name, 'do-thing');
  assert.equal(data.description, 'A: colon, inside');
  assert.equal(data['user-invocable'], true);
  assert.match(body, /^Body/);
});

test('a value containing a colon survives unquoted', () => {
  const { data } = parseFrontmatter(doc('description: Run tests: fast'));
  assert.equal(data.description, 'Run tests: fast');
});

test('folded and literal block scalars', () => {
  const { data } = parseFrontmatter(doc('description: >-\n  one\n  two\nargument-hint: |\n  a\n  b'));
  assert.equal(data.description, 'one two');
  assert.equal(data['argument-hint'], 'a\nb');
});

test('flow and block sequences', () => {
  const { data } = parseFrontmatter(doc('harness: [claude, dsh]\ntags:\n  - review\n  - ci'));
  assert.deepEqual(data.harness, ['claude', 'dsh']);
  assert.deepEqual(data.tags, ['review', 'ci']);
});

test('metadata parses as a nested map and rides through untouched', () => {
  const { skill } = parseSkill(doc('name: a-skill\ndescription: d\nmetadata:\n  version: 2\n  owner: platform'));
  assert.deepEqual(skill.metadata, { version: 2, owner: 'platform' });
});

test('unknown keys are ignored silently, not rejected', () => {
  const { skill } = parseSkill(doc('name: a-skill\ndescription: d\nallowed-tools: Bash\nmodel: sonnet\nlicense: MIT'));
  assert.equal(skill.name, 'a-skill');
  assert.equal(skill.allowedTools, undefined);
});

test('name and description are both required', () => {
  assert.match(parseSkill(doc('name: a-skill')).reason, /requires name and description/);
  assert.match(parseSkill(doc('description: d')).reason, /requires name and description/);
  assert.match(parseSkill(doc('name: a-skill\ndescription: "   "')).reason, /requires name and description/);
});

test('the name must match dsh\'s kebab-case grammar', () => {
  assert.ok(isSkillName('do-a-thing-2'));
  assert.ok(!isSkillName('Do-Thing'));
  assert.ok(!isSkillName('do_thing'));
  assert.match(parseSkill(doc('name: Do_Thing\ndescription: d')).reason, /invalid skill name/);
});

test('invocation policy defaults to both surfaces and honors the kebab keys', () => {
  assert.deepEqual(parseSkill(doc('name: a\ndescription: d')).skill.invocation, {
    modelInvocable: true, userInvocable: true,
  });
  assert.deepEqual(
    parseSkill(doc('name: a\ndescription: d\ndisable-model-invocation: true\nuser-invocable: "no"')).skill.invocation,
    { modelInvocable: false, userInvocable: false },
  );
});

test('a non-boolean invocation value drops the skill instead of guessing', () => {
  assert.match(parseSkill(doc('name: a\ndescription: d\nuser-invocable: maybe')).reason, /must be booleans/);
});

test('the harness key is honored here even though every harness ignores it', () => {
  assert.ok(admitsDsh({}));
  assert.ok(admitsDsh({ harness: 'dsh' }));
  assert.ok(admitsDsh({ harness: ['pi', 'dsh'] }));
  assert.ok(!admitsDsh({ harness: ['claude'] }));
  assert.ok(!admitsDsh({ harness: 'pi' }));
  assert.equal(parseSkill(doc('name: a\ndescription: d\nharness: [claude, pi]')).skipped, true);
  assert.equal(parseSkill(doc('name: a\ndescription: d\nharness: [claude, dsh]')).skill.name, 'a');
});
