export const meta = {
  name: 'rules-sweep',
  description: 'Rebuild a best-practices rule set from its pinned upstream docs: extract checkable practices from every page, judge them per reference topic against the existing rules, live-check behavioral claims on the pinned versions, and write a coverage ledger',
  phases: [
    { title: 'Extract', detail: 'one reader per docs shard, every item quoted with path:line' },
    { title: 'Judge', detail: 'one judge per reference topic: keep, update, new or reject' },
    { title: 'Verify', detail: 'run behavioral claims on the pinned versions and find version floors' },
    { title: 'Assemble', detail: 'write ledger.json and ledger.md' },
  ],
}

// args: the JSON scripts/prepare.py prints — { domain, subject, out_of_scope, live, floors, root,
//   sources: [{name, repo, ref, sha}], shards: [{id, files: [{path, start, end}]}], topics, rulesDir, outDir }
const { domain, subject, out_of_scope, live, floors, root, sources, shards, topics, rulesDir, outDir } = args
const SRC = `these pinned upstream sources, checked out under ${root}: ${sources.map(s => `${s.name} (${s.repo} at ${s.ref}, commit ${s.sha.slice(0, 12)})`).join('; ')}`

const EXTRACT = {
  type: 'object',
  required: ['sections', 'items'],
  properties: {
    sections: {
      type: 'array',
      items: {
        type: 'object',
        required: ['path', 'heading', 'disposition'],
        properties: {
          path: { type: 'string' },
          heading: { type: 'string' },
          disposition: { enum: ['items', 'no-practice', 'out-of-scope'] },
        },
      },
    },
    items: {
      type: 'array',
      items: {
        type: 'object',
        required: ['practice', 'quote', 'source', 'topic', 'applies_when', 'behavioral', 'existing_rule'],
        properties: {
          practice: { type: 'string' },
          quote: { type: 'string' },
          source: { type: 'string' },
          topic: { enum: topics },
          applies_when: { type: 'string' },
          behavioral: { type: 'boolean' },
          existing_rule: { type: ['string', 'null'] },
        },
      },
    },
  },
}

const JUDGE = {
  type: 'object',
  required: ['verdicts', 'existing'],
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'item_ids', 'verdict', 'rule', 'title', 'rationale', 'applies_when', 'needs_live_check'],
        properties: {
          id: { type: 'string' },
          item_ids: { type: 'array', items: { type: 'string' } },
          verdict: { enum: ['keep', 'update', 'new', 'reject'] },
          rule: { type: ['string', 'null'] },
          title: { type: 'string' },
          rationale: { type: 'string' },
          change: { type: 'string' },
          sources: { type: 'array', items: { type: 'string' } },
          applies_when: { type: 'string' },
          needs_live_check: { type: 'boolean' },
          check_command: { type: 'string' },
        },
      },
    },
    existing: {
      type: 'array',
      items: {
        type: 'object',
        required: ['rule', 'docs'],
        properties: {
          rule: { type: 'string' },
          docs: { enum: ['supported', 'contradicted', 'silent'] },
          note: { type: 'string' },
        },
      },
    },
  },
}

const VERIFY = {
  type: 'object',
  required: ['checks'],
  properties: {
    checks: {
      type: 'array',
      items: {
        type: 'object',
        required: ['verdict_id', 'outcome', 'command', 'output_excerpt'],
        properties: {
          verdict_id: { type: 'string' },
          outcome: { enum: ['confirmed', 'refuted', 'inconclusive'] },
          command: { type: 'string' },
          output_excerpt: { type: 'string' },
          preview_feature: { type: ['string', 'null'] },
          introduced_in: { type: ['string', 'null'] },
          introduced_date: { type: ['string', 'null'] },
          note: { type: 'string' },
        },
      },
    },
  },
}

const ASSEMBLE = {
  type: 'object',
  required: ['json_path', 'md_path', 'counts', 'vocabulary'],
  properties: {
    json_path: { type: 'string' },
    md_path: { type: 'string' },
    counts: {
      type: 'object',
      required: ['keep', 'update', 'new', 'reject'],
      properties: { keep: { type: 'integer' }, update: { type: 'integer' }, new: { type: 'integer' }, reject: { type: 'integer' } },
    },
    vocabulary: {
      type: 'array',
      items: {
        type: 'object',
        required: ['tag', 'detect'],
        properties: { tag: { type: 'string' }, detect: { type: 'string' } },
      },
    },
  },
}

phase('Extract')
const extracted = await parallel(shards.map(s => () => agent(
  `Extract candidate best practices for ${subject} from ${SRC}.

Read every one of these line ranges in full; paths are relative to ${root}:
${s.files.map(f => `- ${f.path} lines ${f.start}-${f.end}`).join('\n')}

First read the current rule index in ${rulesDir}/SKILL.md so you can match items to existing rules.

A best practice is advice a reviewer can check against a real repository: a setting or command to use, a footgun to avoid, a deprecation, a security, reproducibility or CI measure, a publishing step. Not a best practice: a description of a feature with no recommendation, installing the tool itself, internals with no user-facing consequence.
Out of scope — record the section as out-of-scope and emit no item: ${out_of_scope}

For each item:
- quote: text copied verbatim from the file, 1-3 lines, that supports the item. No paraphrase. An item you cannot quote does not exist.
- source: <path relative to ${root}>:<line of the quote's first line>.
- topic: the closest of ${topics.join(', ')} (the reference files under ${rulesDir}/references/).
- applies_when: "always" when it holds for any project in this domain; otherwise the repository condition that makes it relevant, written so it can be checked from files.
- behavioral: true when correctness depends on what a tool does at runtime (a default value, a flag's effect, preview vs stable, an error) rather than on file content alone.
- existing_rule: the rule ID that already states this practice, or null.

List every heading you read in \`sections\` with its disposition (items, no-practice, out-of-scope). That list is the coverage record, so include headings that yielded nothing. Do not edit any file.`,
  { label: `extract:${s.id}`, phase: 'Extract', schema: EXTRACT, model: 'sonnet', effort: 'medium' },
)))

// Coverage: every file of every shard must appear in some section, or the gap is logged and handed on.
const gaps = []
shards.forEach((s, i) => {
  const r = extracted[i]
  if (!r) { gaps.push(...s.files.map(f => ({ path: f.path, reason: `extractor ${s.id} failed` }))); return }
  const seen = new Set(r.sections.map(x => x.path.replace(`${root}/`, '')))
  s.files.filter(f => !seen.has(f.path)).forEach(f => gaps.push({ path: f.path, reason: `no section reported by ${s.id}` }))
})
if (gaps.length) log(`coverage gaps: ${gaps.length} file(s) — ${gaps.map(g => g.path).join(', ')}`)

const items = extracted.flatMap((r, i) => (r ? r.items.map((it, j) => ({ ...it, id: `${shards[i].id}#${j + 1}` })) : []))
const sections = extracted.filter(Boolean).flatMap(r => r.sections)
log(`${items.length} candidate items from ${sections.length} sections`)

const perTopic = await pipeline(
  topics,
  topic => agent(
    `You judge the \`${topic}\` topic of the ${domain} rule set against ${SRC}.

Existing rules: ${rulesDir}/references/${topic}.md, indexed in ${rulesDir}/SKILL.md. Read both.
Candidates (JSON):
${JSON.stringify(items.filter(it => it.topic === topic))}

1. Confirm each candidate's quote is at its source in the checkout (Read or grep it). Reject a candidate whose quote is missing or does not support the practice, with rationale "unsupported-quote".
2. Cluster duplicates, then give each cluster one verdict:
   - keep: an existing rule already states it correctly (rule = that ID);
   - update: an existing rule is wrong, stale or incomplete (rule = that ID; change = exactly what to change);
   - new: worth a new rule (rule = null);
   - reject: true but not worth a rule — niche, obvious, or only describes a feature (rationale says which).
   The bar for new: a reviewer of a typical repository can check it, and violating it has a concrete cost. Coverage is proven by this ledger, not by the number of rules.
3. For every rule in ${topic}.md, report in \`existing\` whether the docs at these pins support it, contradict it, or are silent. Silent is not wrong: the rule may rest on another source.
4. Set needs_live_check on any keep, update or new verdict whose correctness depends on runtime behavior (a default, a flag's effect, preview vs stable, an error), and give check_command: the exact shell command that would show it, using the tools as named here: ${live}
Give verdict ids as ${topic}-1, ${topic}-2, …. Do not edit any file.`,
    { label: `judge:${topic}`, phase: 'Judge', schema: JUDGE, model: 'opus' },
  ),
  async (judged, topic) => {
    const claims = judged ? judged.verdicts.filter(v => v.needs_live_check && v.verdict !== 'reject') : []
    const checked = claims.length ? await agent(
      `Live-check these claims against the pinned versions in ${SRC}.

${live}
Work only inside a fresh directory under ${outDir}/live/${topic}/ (create it), never inside a git repository you did not create there.
Claims (JSON):
${JSON.stringify(claims.map(v => ({ verdict_id: v.id, title: v.title, rationale: v.rationale, change: v.change, check_command: v.check_command })))}

For each claim:
- Run the command, adapting it when needed, and quote the relevant output. For preview or experimental status, quote the warning the tool prints, or state that it printed none.
- outcome: confirmed, refuted or inconclusive. Never confirm from documentation alone.
- introduced_in / introduced_date: ${floors}
Do not edit any file outside ${outDir}/live/.`,
      { label: `verify:${topic}`, phase: 'Verify', schema: VERIFY, model: 'sonnet' },
    ) : { checks: [] }
    return { topic, judged, checks: checked ? checked.checks : null }
  },
)

const failed = topics.filter((t, i) => !perTopic[i] || !perTopic[i].judged)
if (failed.length) log(`judge failed for: ${failed.join(', ')} — those topics are missing from the ledger`)

phase('Assemble')
const ledger = await agent(
  `Assemble the ${domain} rule-set ledger from this sweep of ${SRC}.

Inputs (JSON): per-topic verdicts, existing-rule reviews and live checks:
${JSON.stringify(perTopic.filter(Boolean))}
Coverage gaps (files no extractor reported): ${JSON.stringify(gaps)}
Sections read: ${sections.length}; topics whose judge failed: ${JSON.stringify(failed)}.

Read the "Version floors" and "Applicability" sections of ${rulesDir}/../../CONVENTIONS.md and apply them.

1. A refuted live check turns its verdict into reject or update, with the observed output as the reason. An inconclusive one stays, marked unverified.
2. Resolve conflicts across topics: one practice, one rule, in the most fitting topic.
3. Define the applicability vocabulary: a small closed set of tags, each with a detect command an auditor can run on a repository (a file glob, a config key, a workflow step). Rules that apply to every project in this domain get the tag "core". Map every keep, update and new verdict's applies_when onto exactly one tag. If ${rulesDir}/SKILL.md already has an ## Applicability table, reuse its tags where they fit.
4. ledger.json: a JSON array, one entry per verdict: {id, topic, verdict, rule, title, change, rationale, sources, tag, requires, live: {outcome, command, output_excerpt} | null}, then one entry per existing rule the docs contradict or are silent on: {rule, docs, note}.
5. ledger.md: a human-readable report: a header (each source with its ref and commit, counts, coverage gaps), the vocabulary table, then per topic its new, update, keep and reject lists, each line citing sources.
Write both to ${outDir}/ledger.json and ${outDir}/ledger.md, and return their paths with the counts and the vocabulary.`,
  { label: 'assemble', phase: 'Assemble', schema: ASSEMBLE, model: 'opus' },
)

return {
  domain, sources,
  ledger: ledger ? { json: ledger.json_path, md: ledger.md_path, counts: ledger.counts, vocabulary: ledger.vocabulary } : null,
  items: items.length, sections: sections.length, gaps, failed_topics: failed,
}
