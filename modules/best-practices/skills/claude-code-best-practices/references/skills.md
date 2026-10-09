# CC skill rules

Detailed entries for `CC-029..CC-050` — skills and commands: frontmatter,
invocation control, body, supporting files, permissions and testing. Each
follows the four-part **What / Why / How / When NOT to apply** shape.

## Contents

Frontmatter
- CC-029 — Frontmatter on line 1, and it parses
- CC-030 — Field names spelled exactly
- CC-031 — `name` constraints
- CC-032 — `description` constraints
- CC-033 — New work is a skill folder, not a command file

Invocation control
- CC-034 — Side-effecting skills set `disable-model-invocation: true`
- CC-035 — Background knowledge sets `user-invocable: false`
- CC-036 — `context: fork` only for self-contained tasks
- CC-037 — `paths:` limits auto-activation

Body
- CC-038 — Body short, most important instructions first
- CC-039 — Standing instructions, not one-shot ones
- CC-040 — Freedom matches risk
- CC-041 — One default with an escape hatch
- CC-042 — Checklists and validation loops for multi-step work
- CC-043 — Show the expected output

Supporting files
- CC-044 — Supporting files one level deep, signposted
- CC-045 — Script hygiene
- CC-046 — Fully qualified MCP tool names

Permissions and dynamic context
- CC-047 — Narrow `allowed-tools`
- CC-048 — Injected commands are deterministic, fast and pre-approved

Testing
- CC-049 — Evaluate with the skill on and off
- CC-050 — Test triggering both ways, on every model

---

## CC-029 — Frontmatter on line 1, and it parses

**What.** The opening `---` is on line 1 of `SKILL.md`, and the YAML
between the fences parses.

**Why.** Malformed frontmatter doesn't fail loudly: the skill loads with
empty metadata, so `/skill-name` still works but Claude can never match a
task against its description — it never auto-triggers.

**How.** Run `claude plugin validate <skill-dir>`; it reports `SKILL.md`
files whose frontmatter doesn't parse. Quote values containing `: ` or
starting with `[`, `{`, `*` or `&`.

**When NOT to apply.** Never.

---

## CC-030 — Field names spelled exactly

**What.** Use only these frontmatter fields, spelled exactly: `name`,
`description`, `when_to_use`, `argument-hint`, `arguments`,
`disable-model-invocation`, `user-invocable`, `allowed-tools`,
`disallowed-tools`, `model`, `effort`, `context`, `agent`, `background`,
`hooks`, `paths`, `shell`, `metadata`, `license`, `compatibility`. A
skill uploaded to claude.ai or the Skills API may use only `name`,
`description`, `license`, `compatibility`, `metadata` and
`allowed-tools`.

**Why.** Claude Code ignores an unrecognized field without reporting an
error, so a typo (`disable-model-invokation`) silently disables the
setting. On claude.ai and the Skills API the opposite holds: any other
field is a hard upload error.

**How.** Compare each key against the list; `disable_model_invocation`
(underscores) is a different, unknown key.

**When NOT to apply.** A skill written for another harness follows that
harness's field list as well.

---

## CC-031 — `name` constraints

**What.** `name` is at most 64 characters of lowercase letters, digits
and hyphens, with no XML tags, and contains neither "anthropic" nor
"claude". Prefer a gerund (`processing-pdfs`) or noun phrase
(`pdf-processing`), never vague (`helper`, `utils`). Don't name a skill
folder `synced` or `anthropic-skills`.

**Why.** The character rules and reserved words are platform validation
for uploaded skills. The folder names are reserved by Claude Code:
`~/.claude/skills/synced/` holds skills downloaded from claude.ai (a
later sync can overwrite it, and an authored skill named `synced` in any
capitalization is skipped), and an `anthropic-skills` folder outside a
plugin doesn't load. A vague name gives Claude nothing to discriminate
on.

**How.**

```yaml
name: reviewing-migrations
```

**When NOT to apply.** A skill that only ever loads from disk in Claude
Code tolerates the reserved words (this library's own
`claude-code-best-practices` does), but can't be uploaded unchanged.

---

## CC-032 — `description` constraints

**What.** `description` is non-empty, at most 1,024 characters, has no
XML tags, is written in third person, states what the skill does and
when to use it in the words a user would actually say, puts the key use
case first, and doesn't overlap another skill's description so much that
Claude can't choose between them.

**Why.** The description is what Claude matches tasks against. Claude
Code truncates `description` plus `when_to_use` at 1,536 characters in
the skill listing, and the listing as a whole has a budget of about 1% of
the context window, so descriptions can be cut or dropped — whatever
comes first is what survives.

**How.**

```yaml
description: Reviews database migrations for locking and rollback risk. Use when a migration file is added or changed, or the user asks whether a migration is safe to deploy.
```

**When NOT to apply.** Never.

---

## CC-033 — New work is a skill folder, not a command file

**What.** Write new commands as skill folders (`.claude/skills/<name>/SKILL.md`)
rather than `.claude/commands/*.md`.

**Why.** Command files still work, but only a skill folder supports
supporting files and the full set of frontmatter fields.

**How.** Move `.claude/commands/deploy.md` to
`.claude/skills/deploy/SKILL.md` and add `disable-model-invocation: true`
(CC-034).

**When NOT to apply.** Existing working command files don't need
migrating until they need a skill-only feature.

---

## CC-034 — Side-effecting skills set `disable-model-invocation: true`

**What.** Any skill that deploys, commits, pushes, sends messages,
deletes or spends money sets `disable-model-invocation: true`.

**Why.** Without it Claude can decide on its own that the skill applies
and run it. With it, the skill runs only when the user invokes it — and
its description is also removed from context, so it stops costing tokens
every turn.

**How.**

```yaml
name: deploying
description: Deploys the current branch to staging.
disable-model-invocation: true
```

**When NOT to apply.** Read-only skills and skills whose side effects are
local and reversible can stay model-invocable.

---

## CC-035 — Background knowledge sets `user-invocable: false`

**What.** A skill that is reference knowledge, with nothing to "run",
sets `user-invocable: false`.

**Why.** It hides the skill from the `/` menu, where it makes no sense as
a command, while Claude can still load it when relevant.

**How.**

```yaml
name: billing-schema
user-invocable: false
```

**When NOT to apply.** Skills a user would reasonably call by name.

---

## CC-036 — `context: fork` only for self-contained tasks

**What.** Use `context: fork` only on a skill whose body is an explicit,
self-contained task. `agent` picks the subagent type; set
`background: false` when the steps need tools a background fork lacks or
the result is needed in the same turn.

**Why.** The forked subagent doesn't see the conversation, so a body that
assumes context ("fix the bug we discussed") fails. `background` defaults
to `true`, background forks get a narrower tool set, and edits a
background fork makes fall outside checkpoints, so `/rewind` doesn't undo
them.

**How.**

```yaml
context: fork
agent: Explore
background: false
```

**When NOT to apply.** Reference skills and skills that depend on the
conversation run inline.

---

## CC-037 — `paths:` limits auto-activation

**What.** A skill relevant only to some files sets `paths:` globs.

**Why.** With `paths` set, Claude loads the skill automatically only when
working with matching files, which avoids mis-triggering elsewhere.

**How.**

```yaml
paths: ["**/*.tf"]
```

**When NOT to apply.** Skills triggered by the user's intent rather than
by file type.

---

## CC-038 — Body short, most important instructions first

**What.** Keep the `SKILL.md` body under 500 lines — much shorter is
better — and put the most important instructions near the top.

**Why.** A loaded body stays in context for every later turn. After
compaction Claude Code re-injects only the first 5,000 tokens of each
invoked skill, within a 25,000-token budget shared by all re-attached
skills (oldest dropped first), so instructions at the end of a long body
are the first to disappear.

**How.** `wc -l SKILL.md`; move detail to supporting files (CC-044).

**When NOT to apply.** Never.

---

## CC-039 — Standing instructions, not one-shot ones

**What.** Phrase guidance as standing instructions covering the whole
task: "after every edit, run the tests", not "run the tests".

**Why.** Claude Code doesn't re-read the skill on later turns; a one-shot
instruction is followed once and then forgotten for the rest of the task.

**How.**

```markdown
For the rest of this task, run `make lint` after every file edit.
```

**When NOT to apply.** Steps that genuinely happen once (initial setup).

---

## CC-040 — Freedom matches risk

**What.** Fragile operations get exact commands; judgment calls get
heuristics.

**Why.** Loose prose on a fragile operation lets Claude improvise a flag
or skip a step; exact commands on a judgment task force steps that don't
fit the case.

**How.**

```markdown
Run exactly: `python scripts/migrate.py --verify --backup`. Do not add flags.
```

**When NOT to apply.** Never as a principle.

---

## CC-041 — One default with an escape hatch

**What.** Give one default approach and name the exception, not a menu of
equivalent options.

**Why.** A menu hands the choice back to Claude with no basis for it, so
it varies between runs.

**How.**

```markdown
Use pdfplumber. For scanned PDFs, use pdf2image with pytesseract instead.
```

**When NOT to apply.** When the choice depends on facts only the user has,
name the deciding factor.

---

## CC-042 — Checklists and validation loops for multi-step work

**What.** A multi-step workflow includes a checklist Claude copies and
ticks off, and a validate → fix → repeat loop for quality-critical steps.

**Why.** Without them Claude skips steps in long workflows and lets an
early error flow into everything built on it.

**How.**

```markdown
- [ ] 1. Generate fields.json
- [ ] 2. Run validate.py fields.json — fix and re-run until it passes
- [ ] 3. Fill the form
```

**When NOT to apply.** Single-step skills.

---

## CC-043 — Show the expected output

**What.** When format matters, give a template or input/output examples,
and say how strictly to follow them.

**Why.** Examples and templates fix the shape more reliably than a
description of it (CC-008).

**How.** An "ALWAYS use this exact template" block for machine-read
output; "a sensible default, adapt as needed" for documents.

**When NOT to apply.** Free-form output.

---

## CC-044 — Supporting files one level deep, signposted

**What.** Link every supporting file directly from `SKILL.md`, saying
what it contains and when to read it. Reference files over 100 lines
start with a table of contents. Use descriptive file names and forward
slashes.

**Why.** Files reached only through another file tend to be
partially read; an unsignposted file is never opened; a table of contents
shows the full scope even on a partial read.

**How.**

```markdown
- reference/schema.md — table definitions; read before writing any query.
```

**When NOT to apply.** Never.

---

## CC-045 — Script hygiene

**What.** `SKILL.md` says whether to *run* or *read* each script. Scripts
handle their own errors with specific messages, explain every constant,
state their dependencies, and are referenced through
`${CLAUDE_SKILL_DIR}` (or `${CLAUDE_PROJECT_DIR}` for project files).

**Why.** A raw traceback costs Claude turns to decode; a magic number
can't be adjusted safely; an undeclared dependency fails at import; a
relative path breaks when the working directory isn't the skill
directory. `${CLAUDE_SKILL_DIR}` resolves to the skill's own directory
(in a plugin, the skill's subdirectory, not the plugin root).

**How.**

```markdown
Run `python ${CLAUDE_SKILL_DIR}/scripts/validate.py fields.json` (needs `pip install pypdf`).
```

**When NOT to apply.** Skills with no scripts.

---

## CC-046 — Fully qualified MCP tool names

**What.** Name MCP tools by their fully qualified, server-prefixed names.

**Why.** With several servers connected, a bare tool name can be
ambiguous or not found.

**How.** Name the server and the tool (`github` server's `create_issue`),
in the spelling the harness exposes.

**When NOT to apply.** Never.

---

## CC-047 — Narrow `allowed-tools`

**What.** Grant the narrowest pattern that works: `Bash(git commit *)`,
not `Bash`.

**Why.** `allowed-tools` pre-approves those tools whenever the skill is
active. Claude Code documents that workspace trust doesn't gate this
field for a project skill in a `-p` run, so a broad grant in a
committed repository skill is a security finding: anyone running Claude
non-interactively in that checkout inherits it.

**How.**

```yaml
allowed-tools: Read Grep Bash(git diff *) Bash(git log *)
```

**When NOT to apply.** Never for committed skills; a personal skill's
grant is the user's own call.

---

## CC-048 — Injected commands are deterministic, fast and pre-approved

**What.** Dynamic context injection (an exclamation mark immediately
followed by a backticked command, which runs before Claude sees the
skill) uses only commands that are deterministic, finish well within the
Bash tool's 2-minute timeout, and are pre-approved — `allowed-tools` is
the recommended way. Append `|| true` to a check that is expected to fail
with exit code 2 or higher.

**Why.** Outside auto mode, a command whose permission check isn't
"allow" aborts the whole invocation; in auto mode it does too inside a
forked skill that sets `agent`. With the default `bash` shell any
non-zero exit fails the invocation — except exit 1 from search and
comparison commands, which counts as a normal result. A command killed at
the timeout also aborts it.

**How.** Inject `git status --short` and similar fast, read-only
commands, each matched by an `allowed-tools` pattern.

**When NOT to apply.** Skills with no injected commands.

---

## CC-049 — Evaluate with the skill on and off

**What.** Write at least three eval prompts that exercise real gaps. Run
each in a fresh session with the skill on, and again with it off
(`skillOverrides` set to `"off"` for it).

**Why.** Without the off run there's no evidence the skill changes
anything; a skill can cost context on every turn while adding nothing.

**How.**

```json
{ "skillOverrides": { "reviewing-migrations": "off" } }
```

**When NOT to apply.** Never. (`skillOverrides` doesn't apply to plugin
skills; use `claude plugin eval`, which runs a no-plugin baseline.)

---

## CC-050 — Test triggering both ways, on every model

**What.** Test with prompts that should trigger the skill and prompts
that shouldn't, on every model it will run on. Useful tools: the
`skill-creator` plugin (runs evals, tunes the description), `/skill-doctor`
(each skill's context cost and usage, to find unused ones), and
`claude plugin validate <dir>`.

**Why.** A description that fires too broadly costs context and
misdirects; one that never fires is dead weight. Behavior differs by
model.

**How.** Keep a list of should / should-not prompts beside the skill and
re-run it whenever the description changes.

**When NOT to apply.** Skills with `disable-model-invocation: true`
can't auto-trigger, so trigger tests don't apply; their evals still do
(CC-049).
