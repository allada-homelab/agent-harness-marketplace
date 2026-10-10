# Reviewing a Claude Code configuration

The procedure for auditing configuration and prompts against the `CC-`
and `PROMPT-` rules. Report only findings that would change Claude's
behavior, reliability, safety or context cost.

## Contents

1. Find the targets
2. Review with fresh eyes
3. Calibration and severity
4. Report
5. Apply fixes

## 1. Find the targets

Review exactly the paths or globs the user gave. Otherwise discover
everything below that exists, in the project and in `~/.claude`:

| Artifact | Where to look | Rules |
|---|---|---|
| Memory files | `CLAUDE.md`, `CLAUDE.local.md`, nested `**/CLAUDE.md`, `~/.claude/CLAUDE.md` | CC-019..CC-024 |
| Rules | `.claude/rules/**/*.md`, `~/.claude/rules/**/*.md` | CC-025..CC-028 |
| Skills and commands | `.claude/skills/*/` (whole folder), `~/.claude/skills/*/`, `.claude/commands/**/*.md`, plugin `skills/` | CC-029..CC-050 |
| Subagents | `.claude/agents/*.md`, `~/.claude/agents/*.md`, plugin `agents/` | CC-051..CC-057 |
| Hooks and permissions | `hooks`, `permissions`, `skillOverrides` in `.claude/settings.json`, `.claude/settings.local.json`, `~/.claude/settings.json`; plugin `hooks/hooks.json`; `hooks:` in skill or agent frontmatter | CC-058..CC-065 |
| Output styles | `.claude/output-styles/`, `~/.claude/output-styles/` | CC-066..CC-067 |
| Plugins and marketplaces | `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, the plugin's component folders | CC-068..CC-075 |
| MCP config | `.mcp.json` | CC-076..CC-079 |
| Prompts in application code | grep for `system=`, `system_prompt`, `SYSTEM_PROMPT`, `messages.create`, `prompts/`, `*.prompt.md`, `*.prompt.txt` | PROMPT-001..PROMPT-020 |

CC-001..CC-010 (all instructions) and CC-011..CC-018 (choosing the
mechanism) apply to every artifact.

Skip `~/.claude/skills/synced/` (synced from claude.ai and overwritten on
the next sync) and `~/.claude/plugins/` (the installed plugin cache). If
one of those has a problem, name the source the user would edit instead.

## 2. Review with fresh eyes

Delegate the review to a subagent when either holds:

- The artifacts were written or edited earlier in this conversation — a
  reviewer that saw the reasoning behind them grades its own work.
- There are more than about 10 files. Use one subagent per artifact type
  so each loads only its rule file.

Give each subagent the file list, the path to this skill's rule files and
the rule IDs that apply, the report format from step 4, and the
calibration rules in step 3. Merge their findings into one report. For a
handful of files you did not write, review inline.

For every artifact:

1. **Apply its rules**, plus CC-001..CC-018.
2. **Measure instead of estimating.** `wc -l` for line counts; count
   characters for `name` and `description`.
3. **Check the mechanics:** frontmatter starts on line 1 and parses;
   field names exactly match CC-030 (unknown fields are silently
   ignored); every linked or referenced file exists; scripts are
   referenced through `${CLAUDE_SKILL_DIR}`, `${CLAUDE_PROJECT_DIR}` or
   `${CLAUDE_PLUGIN_ROOT}` — unless the skill must also load on another
   harness that lacks those variables, where skill-relative paths
   (`./scripts/x.py`) are correct (CC-045).
4. **Validate plugins and skill folders** with `claude plugin validate
   <dir>`. If the command isn't available, say so once and continue.
5. **Look across artifacts:** the same instruction duplicated in files
   that load together; instructions that contradict each other (CC-009);
   skill descriptions that overlap so much Claude can't choose (CC-032);
   instructions in the wrong mechanism (CC-011..CC-018).

## 3. Calibration and severity

A reviewer asked to find problems always finds some. Hold every finding
to this bar:

- **Name a concrete consequence** — the skill never auto-triggers, the
  rule loads into every session, the guardrail can be skipped. Leave out
  style preferences and wording you would merely have chosen differently.
- **Prefer cutting to adding.** Recommend new content only where its
  absence has caused, or will plausibly cause, a specific failure.
- **Don't flag a deliberate trade-off** that the artifact or its comments
  explain.

Severity:

- **Critical** — the artifact fails to load or parse, poses a security
  risk, or relies on prose for a guardrail. Security risks include broad
  `allowed-tools` in a committed skill (CC-047), secrets in a file
  (CC-010, CC-079), and a hook that interpolates untrusted input into a
  shell command (CC-061). A prose guardrail is a "never do X" that is
  only an instruction (CC-013).
- **High** — an instruction is likely to be ignored or mis-triggered, or
  something adds significant always-on context cost: CLAUDE.md over 200
  lines (CC-019), a vague skill description (CC-032), a side-effecting
  skill Claude can invoke on its own (CC-034).
- **Medium** — structure or clarity problems that make the artifact less
  reliable.
- **Low** — optional polish. List at most five.

## 4. Report

```markdown
# Agent config review — <scope> — <date>

**Summary:** <N files reviewed>. <counts by severity>. <the single most important fix in one sentence>.

## Critical
- **<file>:<line>** — <what is wrong>. <consequence>. *Fix:* <specific change>. *(CC-0NN)*

## High
…

## Medium
…

## Low (optional)
…

## Clean
<artifacts with no findings, one line each>
```

Quote at most one line of the offending text per finding. Group repeated
issues into one finding that lists every location.

## 5. Apply fixes

After the report, ask which findings to apply. Then make those edits,
re-run the mechanical checks from step 2 on the changed files, and
summarize what changed, file by file. Never edit synced skills or the
installed plugin cache.
