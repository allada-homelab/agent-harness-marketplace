# CC output-style rules

Detailed entries for `CC-066..CC-067` — output styles and appended system
prompts. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## CC-066 — Custom output styles keep coding instructions deliberately

**What.** A custom output style for coding work sets
`keep-coding-instructions: true`. Check the built-in styles before writing
a custom one.

**Why.** A custom output style replaces Claude Code's default
software-engineering instructions — scoping changes, comments, security,
running tests — unless it sets `keep-coding-instructions: true`. A style
written only to change tone silently removes all of that.

**How.**

```markdown
---
name: terse
description: Short answers
keep-coding-instructions: true
---
Answer in at most three sentences unless asked for more.
```

**When NOT to apply.** A style for non-coding work (writing, research)
can drop them on purpose.

---

## CC-067 — Keep `--append-system-prompt` short

**What.** Use `--append-system-prompt` for a short, invocation-specific
addition.

**Why.** It adds to the default prompt for that invocation only.
Adherence drops as the appended volume grows and when it conflicts with
other instructions.

**How.**

```bash
claude -p "…" --append-system-prompt "Reply in JSON matching schema.json."
```

**When NOT to apply.** Durable session-wide format belongs in an output
style (CC-018).
