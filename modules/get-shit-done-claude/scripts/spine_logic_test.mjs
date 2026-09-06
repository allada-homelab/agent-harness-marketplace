#!/usr/bin/env node
// Unit tests for the spine's pure logic. Extracts the fenced region from gsd.workflow.js by its
// exact marker strings and evaluates it in isolation (no host globals), then asserts behavior.
// Plain node, no dependencies. Exit 0 all-pass with a one-line summary; nonzero on the first failure.

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const START = '// --- pure logic (extracted & tested by scripts/spine_logic_test.mjs) ---'
const END = '// --- end pure logic ---'

const here = dirname(fileURLToPath(import.meta.url))
const wfPath = join(here, '..', 'workflows', 'gsd.workflow.js')
const src = readFileSync(wfPath, 'utf8')

const s = src.indexOf(START)
if (s === -1) {
  console.error(`FAIL: start marker not found in ${wfPath}\n  expected: ${START}`)
  process.exit(1)
}
const e = src.indexOf(END, s + START.length)
if (e === -1) {
  console.error(`FAIL: end marker not found in ${wfPath}\n  expected: ${END}`)
  process.exit(1)
}
const region = src.slice(s + START.length, e)

// Evaluate the extracted region in isolation and hand back the three pure functions.
const { validateSubtasks, collisionInfo, judgeVerdicts } = new Function(
  region + '\nreturn { validateSubtasks, collisionInfo, judgeVerdicts };',
)()

let failed = 0
let passed = 0
function check(name, cond) {
  if (cond) {
    passed++
  } else {
    failed++
    console.error(`FAIL: ${name}`)
  }
}

// ---- collisionInfo: the six known cases ----
{
  // 1. no files declared → none colliding
  const { colliding } = collisionInfo([{ title: 'a' }, { title: 'b' }])
  check('collisionInfo: no files declared → none colliding', colliding.size === 0)
}
{
  // 2. one colliding pair among disjoint (0 and 2 share x; 1 is on its own)
  const { colliding } = collisionInfo([{ files: ['x'] }, { files: ['y'] }, { files: ['x'] }])
  check(
    'collisionInfo: one colliding pair among disjoint',
    colliding.size === 2 && colliding.has(0) && colliding.has(2) && !colliding.has(1),
  )
}
{
  // 3. three-way collision (all share z)
  const { colliding } = collisionInfo([{ files: ['z'] }, { files: ['z'] }, { files: ['z'] }])
  check(
    'collisionInfo: three-way collision',
    colliding.size === 3 && colliding.has(0) && colliding.has(1) && colliding.has(2),
  )
}
{
  // 4. all disjoint
  const { colliding } = collisionInfo([{ files: ['a'] }, { files: ['b'] }, { files: ['c'] }])
  check('collisionInfo: all disjoint → none colliding', colliding.size === 0)
}
{
  // 5. same file listed twice by ONE subtask → not a self-collision
  const { colliding } = collisionInfo([{ files: ['x', 'x'] }, { files: ['y'] }])
  check('collisionInfo: same file twice by one subtask → not self-collision', colliding.size === 0)
}
{
  // 6. absent-files subtask never marked (0 and 2 collide on x; 1 has no files)
  const { colliding } = collisionInfo([{ files: ['x'] }, { title: 'no-files' }, { files: ['x'] }])
  check(
    'collisionInfo: absent-files subtask never marked',
    colliding.size === 2 && colliding.has(0) && colliding.has(2) && !colliding.has(1),
  )
}

// ---- judgeVerdicts ----
const V = (verdict, reason) => ({ verdict, reason })
{
  const r = judgeVerdicts([V('confirmed', 'ok1'), V('confirmed', 'ok2')])
  check('judgeVerdicts: [confirmed,confirmed] → confirmed', r.confirmed === true && r.live.length === 2)
}
{
  const r = judgeVerdicts([V('confirmed', 'ok'), null])
  check('judgeVerdicts: [confirmed,null] → not confirmed', r.confirmed === false && r.live.length === 1)
}
{
  const r = judgeVerdicts([V('refuted', 'broke it'), V('confirmed', 'ok')])
  check(
    'judgeVerdicts: [refuted,confirmed] → not confirmed + reason in refutedBy',
    r.confirmed === false && r.refutedBy.includes('broke it'),
  )
}
{
  const r = judgeVerdicts([V('couldnt_verify', 'no access'), V('confirmed', 'ok')])
  check(
    'judgeVerdicts: [couldnt_verify,confirmed] → not confirmed + reason in unverified',
    r.confirmed === false && r.unverified.includes('no access'),
  )
}
{
  const r = judgeVerdicts([null, null])
  check('judgeVerdicts: [null,null] → not confirmed, live empty', r.confirmed === false && r.live.length === 0)
}

// ---- validateSubtasks ----
{
  const valid = [
    { title: 't1', prompt: 'do a', tier: 'sonnet' },
    { title: 't2', prompt: 'do b', tier: 'opus', effort: 'high', files: ['a.js', 'b.js'] },
  ]
  check('validateSubtasks: fully valid list → []', validateSubtasks(valid).length === 0)
}
{
  const bad = [
    { prompt: 'p', tier: 'sonnet' }, // 0: missing title
    { title: 't', prompt: 'p', tier: 'gpt' }, // 1: bad tier
    { title: 't', prompt: 'p', tier: 'sonnet', files: 'a.js' }, // 2: files as string
    { title: 't', prompt: '', tier: 'sonnet' }, // 3: empty prompt
  ]
  const d = validateSubtasks(bad)
  check(
    'validateSubtasks: missing title → defect names title + index 0',
    d.some((x) => x.includes('title') && x.includes('0')),
  )
  check(
    'validateSubtasks: bad tier → defect names tier + index 1',
    d.some((x) => x.includes('tier') && x.includes('1')),
  )
  check(
    'validateSubtasks: files as string → defect names files + index 2',
    d.some((x) => x.includes('files') && x.includes('2')),
  )
  check(
    'validateSubtasks: empty prompt → defect names prompt + index 3',
    d.some((x) => x.includes('prompt') && x.includes('3')),
  )
}

if (failed) {
  console.error(`\nspine_logic_test: ${passed} passed, ${failed} FAILED`)
  process.exit(1)
}
console.log(`spine_logic_test: all ${passed} assertions passed`)
