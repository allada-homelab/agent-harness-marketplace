// get-shit-done — the spine workflow (static-checked by scripts/checks.sh; smoke-tested end-to-end).
//
// Shape: Research ∥ Plan  →  per-subtask Implement (at the assigned tier)  →  adversarial Verify.
// Implement→Verify is a pipeline (NO barrier): each subtask is verified the moment its
// implementation finishes, while other subtasks are still being built. Only the subtasks that
// declare a shared file are serialized (as a group); the disjoint remainder keeps its parallelism,
// and both groups run concurrently with each other.
//
// Invoked by /get-shit-done-claude:run via Workflow({ scriptPath, args }). args:
//   { task: string,
//     subtasks?: [{ title, prompt, tier: "sonnet"|"opus", effort?, files? }],   // orchestrator's triage
//     researchTopics?: string[],
//     isolate?: boolean }   // true → each implement runs in its own git worktree (see SAFETY)
// If subtasks are omitted, the spine plans them itself (Opus, which must declare each subtask's `files`).
// Standalone-runnable with just { task }. Returns
// { task, subtaskCount, research, confirmed, flagged, serialized, isolated }, where each result carries
// { title, tier, implOutput, verdicts, confirmed, refutedBy, unverified } and `serialized` is the
// titles of the subtasks that were run sequentially due to a declared file collision (empty if none),
// and `isolated` echoes whether worktree isolation was on.
// `files` (declared or planned) drives collision detection: subtasks sharing a file are serialized as
// a group, while the file-disjoint remainder still pipelines.
//
// SAFETY: implement subagents run in the live tree. Hand the spine FILE-DISJOINT subtasks, or set
// `isolate: true` (the escape hatch), when parallel units would edit the same files. With `isolate`
// on, every subtask runs in its own worktree so same-file edits are safe, collision-serialization is
// skipped, and merging the worktree branches back is the orchestrator's job. Without it, a declared
// `files` collision only serializes the colliding subset, not the whole run — subtasks that do not
// declare their files are treated as unknown and are NOT protected from clobbering each other.

export const meta = {
  name: 'get-shit-done',
  description: 'Decompose a task, research it, implement each subtask at the cheapest capable tier, and adversarially verify before done.',
  phases: [
    { title: 'Research' },
    { title: 'Plan' },
    { title: 'Implement' },
    { title: 'Verify' },
  ],
}

const PLAN = {
  type: 'object',
  additionalProperties: false,
  properties: {
    subtasks: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          title: { type: 'string' },
          prompt: { type: 'string' },
          tier: { type: 'string', enum: ['sonnet', 'opus'] },
          effort: { type: 'string', enum: ['low', 'medium', 'high', 'xhigh', 'max'] },
          files: { type: 'array', items: { type: 'string' } },
        },
        required: ['title', 'prompt', 'tier', 'files'],
      },
    },
  },
  required: ['subtasks'],
}

const RESEARCH = {
  type: 'object',
  additionalProperties: false,
  properties: {
    summary: { type: 'string' },
    sources: { type: 'array', items: { type: 'string' } },
  },
  required: ['summary'],
}

const IMPL = {
  type: 'object',
  additionalProperties: false,
  properties: {
    summary: { type: 'string' },
    changedFiles: { type: 'array', items: { type: 'string' } },
  },
  required: ['summary', 'changedFiles'],
}

const VERDICT = {
  type: 'object',
  additionalProperties: false,
  properties: {
    verdict: { type: 'string', enum: ['confirmed', 'refuted', 'couldnt_verify'] },
    reason: { type: 'string' },
  },
  required: ['verdict', 'reason'],
}

// --- pure logic (extracted & tested by scripts/spine_logic_test.mjs) ---
// Nothing below may reference host globals (agent/parallel/pipeline/log/args/budget) — this region is
// evaluated in isolation by the unit test.

// Validate orchestrator-provided subtasks (the Promise.resolve path bypasses the PLAN schema).
// Returns human-readable defect strings; empty array means valid.
function validateSubtasks(sts) {
  const efforts = ['low', 'medium', 'high', 'xhigh', 'max']
  const defects = []
  sts.forEach((st, i) => {
    if (typeof st !== 'object' || st === null || Array.isArray(st)) {
      defects.push(`subtask ${i}: must be an object`)
      return
    }
    if (typeof st.title !== 'string' || st.title.trim() === '')
      defects.push(`subtask ${i}: title must be a nonempty string`)
    if (typeof st.prompt !== 'string' || st.prompt.trim() === '')
      defects.push(`subtask ${i}: prompt must be a nonempty string`)
    if (st.tier !== 'sonnet' && st.tier !== 'opus')
      defects.push(`subtask ${i}: tier must be exactly 'sonnet' or 'opus'`)
    if (st.effort !== undefined && !efforts.includes(st.effort))
      defects.push(`subtask ${i}: effort must be one of ${efforts.join('|')}`)
    if (st.files !== undefined &&
        (!Array.isArray(st.files) || st.files.some((f) => typeof f !== 'string' || f.trim() === '')))
      defects.push(`subtask ${i}: files must be an array of nonempty strings`)
  })
  return defects
}

// Compute the SET of subtask indices involved in ANY declared file overlap, plus the shared file
// names (for logging). Two subtasks collide iff both declare the same path in `files`; a subtask with
// no/absent `files` array is unknown → never marked colliding (a file listed twice by ONE subtask is
// not a self-collision). Only the colliding subset is serialized — the disjoint remainder keeps its
// parallelism.
function collisionInfo(sts) {
  const byFile = new Map() // file → [declaring subtask indices]
  for (let i = 0; i < sts.length; i++) {
    if (!Array.isArray(sts[i].files)) continue
    for (const f of sts[i].files) {
      if (!byFile.has(f)) byFile.set(f, [])
      byFile.get(f).push(i)
    }
  }
  const colliding = new Set()
  const sharedFiles = []
  for (const [f, idxs] of byFile) {
    const uniq = [...new Set(idxs)]
    if (uniq.length > 1) {
      sharedFiles.push(f)
      for (const i of uniq) colliding.add(i)
    }
  }
  return { colliding, sharedFiles }
}

// The verify gate: two live Opus verifiers with distinct lenses must BOTH positively confirm.
// Takes the raw verdicts array (may contain nulls from dead verifiers); confirmed requires exactly
// 2 live verdicts, zero 'refuted', zero 'couldnt_verify'.
function judgeVerdicts(verdicts) {
  const live = verdicts.filter(Boolean)
  const refutes = live.filter((v) => v.verdict === 'refuted')
  const unverified = live.filter((v) => v.verdict === 'couldnt_verify')
  const confirmed = live.length === 2 && refutes.length === 0 && unverified.length === 0
  return {
    live,
    refutedBy: refutes.map((v) => v.reason),
    unverified: unverified.map((v) => v.reason),
    confirmed,
  }
}
// --- end pure logic ---

// ---- inputs ----
const task = (args && args.task) || (typeof args === 'string' ? args : null)
const isolated = !!(args && args.isolate === true)
if (!task) {
  log('gsd spine: no task in args.task — nothing to do')
  return { error: 'no task provided', isolated }
}
const providedSubtasks =
  args && Array.isArray(args.subtasks) && args.subtasks.length ? args.subtasks : null
// Fail loud on malformed orchestrator-provided subtasks BEFORE spawning any agent (they bypass PLAN).
if (providedSubtasks) {
  const defects = validateSubtasks(providedSubtasks)
  if (defects.length) {
    log('gsd spine: invalid provided subtasks:\n' + defects.map((d) => '  - ' + d).join('\n'))
    return {
      task,
      error: 'invalid subtasks: ' + defects.join('; '),
      subtaskCount: 0,
      research: null,
      confirmed: [],
      flagged: [],
      serialized: [],
      isolated,
    }
  }
}
const researchTopics =
  args && Array.isArray(args.researchTopics) && args.researchTopics.length
    ? args.researchTopics
    : [task]

// ---- Research ∥ Plan (both run at once; plan may be pre-supplied by the orchestrator) ----
const [research, plan] = await parallel([
  () =>
    agent(
      `Gather the external knowledge the upcoming subtasks depend on. FIRST check whether this project has a local knowledge wiki at ./llm-wiki/index.md; if it exists, read it (and any concepts it links that look relevant to the task) — this is curated, project-specific knowledge you should summarize up front and TRUST OVER generic web results when they conflict. THEN use WebSearch/WebFetch (load via ToolSearch) for current best-practices; for any specific library/framework/tool, also use context7 docs tools (resolve-library-id then query-docs, load via ToolSearch). Be concrete and cite what you consulted.\n\nTask: ${task}\n\nTopics:\n${researchTopics.map((t, i) => `${i + 1}. ${t}`).join('\n')}\n\nReturn a compact summary an implementer can act on directly, plus sources.`,
      { label: 'research', phase: 'Research', model: 'sonnet', schema: RESEARCH },
    ),
  () =>
    providedSubtasks
      ? Promise.resolve({ subtasks: providedSubtasks })
      : agent(
          `Decompose this task into the smallest set of INDEPENDENTLY-executable subtasks that are STRICTLY FILE-DISJOINT — no two subtasks may create or modify the same file. For each, give: a self-contained prompt (inputs, exact deliverable, done-criteria); a model tier — "sonnet" for well-scoped/mechanical/clearly-specified work, "opus" for open-ended/high-stakes/hard-reasoning work (default to "sonnet" wherever it plausibly suffices); an effort level; and \`files\` — the complete list of file paths that subtask will create or modify.\n\nTask: ${task}`,
          { label: 'plan', phase: 'Plan', model: 'opus', schema: PLAN },
        ),
])

const subtasks = plan && Array.isArray(plan.subtasks) ? plan.subtasks : []
if (!subtasks.length) {
  log('gsd spine: planning produced no subtasks')
  return { task, subtaskCount: 0, research, confirmed: [], flagged: [], serialized: [], isolated }
}
const researchNote =
  research && research.summary
    ? `\n\n--- Research context (verify before relying on it) ---\n${research.summary}`
    : ''
log(
  `gsd spine: ${subtasks.length} subtasks — ` +
    `${subtasks.filter((s) => s.tier === 'sonnet').length} sonnet / ` +
    `${subtasks.filter((s) => s.tier !== 'sonnet').length} opus`,
)

// ---- stage helpers (shared by the concurrent pipeline and the sequential fallback) ----
// Implement one subtask at its assigned tier; returns { summary, changedFiles } or null if it died.
const runImplement = (st) =>
  agent(
    `${st.prompt}${researchNote}\n\nWhen done, return a one-paragraph summary of what you did plus the complete list of files you created or modified (empty array if none).`,
    {
      label: `impl:${st.title}`,
      phase: 'Implement',
      model: st.tier === 'sonnet' ? 'sonnet' : 'opus',
      effort: st.effort,
      schema: IMPL,
      ...(isolated ? { isolation: 'worktree' } : {}),
    },
  )

// Adversarial Verify: two live Opus verifiers with DISTINCT lenses must BOTH positively confirm.
// Any refutation, any 'couldnt_verify', or a dead verifier (only one live vote) withholds confirmed —
// a lone skeptic suffices, because confident-but-wrong survives lenient majority votes; and
// 'couldnt_verify' ("couldn't check") is not refutation but still can't count as confirmation.
// Single-pass-then-escalate: no generator<->verifier refinement loop (avoids infinite loops / silent
// auto-approval). Verifiers see requirements + the changed-file list only — NOT the implementer's
// narrative — for independence, and effort is pinned so the strongest-critic claim holds regardless
// of session effort.
async function runVerify(implOutput, st) {
  if (implOutput == null) {
    // Implementer died or was skipped — nothing to verify; withhold confirmation.
    return {
      title: st.title,
      tier: st.tier,
      implOutput: null,
      verdicts: [],
      confirmed: false,
      refutedBy: ['implementer returned no output'],
      unverified: [],
    }
  }
  const changed =
    Array.isArray(implOutput.changedFiles) && implOutput.changedFiles.length
      ? implOutput.changedFiles.map((f) => `- ${f}`).join('\n')
      : '(none reported)'
  const lenses = [
    'Your lens: COMPLETENESS vs the brief — check that every stated deliverable and done-criterion is actually present and correct in the changed files.',
    'Your lens: REGRESSIONS & side-effects — check the change did not break adjacent behavior, callers, or tests; look beyond the listed files.',
  ]
  const verdicts = await parallel(
    lenses.map((lens, i) => () =>
      agent(
        `You are an adversarial verifier — try to REFUTE that this subtask was done correctly and completely. Inspect the actual artifacts (read the changed files, check their callers/tests, run any quick check available); do NOT trust any claim — verify against the requirements and the real code.\n\n${lens}\n\nRequirements (the subtask):\n${st.title}\n${st.prompt}\n\nFiles the implementer reports it created/modified:\n${changed}${researchNote}\n\nReturn verdict 'refuted' ONLY with concrete evidence of a defect — state that evidence in reason. Return 'couldnt_verify' when you cannot positively confirm (missing access, ambiguous criteria); do NOT use 'refuted' for mere uncertainty. Return 'confirmed' only when you positively confirmed the deliverables are present and correct.`,
        { label: `verify:${st.title}#${i + 1}`, phase: 'Verify', model: 'opus', effort: 'high', schema: VERDICT },
      ),
    ),
  )
  const { live, refutedBy, unverified, confirmed } = judgeVerdicts(verdicts)
  return {
    title: st.title,
    tier: st.tier,
    implOutput,
    verdicts: live,
    confirmed,
    refutedBy,
    unverified,
  }
}

// ---- budget guard: stop before spending on the fan-out if we're nearly out ----
if (budget.total && budget.remaining() < 30_000) {
  log('gsd spine: budget nearly exhausted — stopping before fan-out')
  return {
    task,
    subtaskCount: subtasks.length,
    error: 'budget exhausted before implement',
    research,
    confirmed: [],
    flagged: [],
    serialized: [],
    isolated,
  }
}

// ---- Implement → adversarial Verify ----
// File-disjoint subtasks pipeline (no barrier: each is verified the moment its implement finishes).
// Subtasks that declare a shared file could clobber each other, so ONLY those are serialized (as a
// group) — the disjoint remainder still pipelines, and both groups run concurrently with each other.
const runPair = async (st) => runVerify(await runImplement(st), st)
// seqRun is defensive: runImplement/runVerify already tolerate a null implOutput, so a dead
// implementer yields a shaped withheld-confirmation result rather than throwing.
const seqRun = async (group) => {
  const out = []
  for (const st of group) out.push(await runPair(st))
  return out
}

const { colliding: collidingIdx, sharedFiles } = collisionInfo(subtasks)
const colliding = subtasks.filter((_, i) => collidingIdx.has(i))
const disjoint = subtasks.filter((_, i) => !collidingIdx.has(i))
// Isolation makes same-file edits safe, so nothing is serialized under it.
const serialized = isolated ? [] : colliding.map((s) => s.title)

let results
if (isolated) {
  log(
    'gsd spine: worktree isolation ON — every subtask pipelines in its own worktree (no collision ' +
      'serialization); merging the worktree branches back is the orchestrator\'s job',
  )
  results = await pipeline(
    subtasks,
    (st) => runImplement(st),
    (implOutput, st) => runVerify(implOutput, st),
  )
} else if (colliding.length) {
  log(
    `gsd spine: file collision on ${sharedFiles.join(', ')} — serializing ` +
      `${serialized.join(', ')}; the other ${disjoint.length} subtask(s) still pipeline`,
  )
  // parallel is a barrier: a throwing thunk resolves to null, so guard each group's result before
  // flattening. seqRun's own elements are never null (runVerify always returns a shaped object).
  const [seqResults, pipeResults] = await parallel([
    () => seqRun(colliding),
    () =>
      disjoint.length
        ? pipeline(disjoint, (st) => runImplement(st), (implOutput, st) => runVerify(implOutput, st))
        : [],
  ])
  results = [...(seqResults || []), ...(pipeResults || [])].filter(Boolean)
} else {
  results = await pipeline(
    subtasks,
    (st) => runImplement(st),
    (implOutput, st) => runVerify(implOutput, st),
  )
}

const done = results.filter(Boolean)
const confirmed = done.filter((r) => r.confirmed)
const flagged = done.filter((r) => !r.confirmed)
log(`gsd spine: ${confirmed.length} confirmed, ${flagged.length} flagged of ${done.length}`)
return { task, subtaskCount: subtasks.length, confirmed, flagged, research, serialized, isolated }
