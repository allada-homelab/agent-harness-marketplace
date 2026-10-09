# SKILL script rules

Detailed entries for `SKILL-019..SKILL-023` — skills that bundle
executable code or call tools. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

## Contents

- SKILL-019 — Scripts handle expected errors with actionable messages
- SKILL-020 — No unexplained constants
- SKILL-021 — Utility scripts for deterministic work; say run or read
- SKILL-022 — Declare dependencies explicitly
- SKILL-023 — Fully qualified MCP tool names

---

## SKILL-019 — Scripts handle expected errors with actionable messages

**What.** A bundled script anticipates the error conditions it can
predict (missing input, permission denied, malformed data) and reports
each one with a specific message that says what failed and what to do,
then exits non-zero. It does not leave the model to decode a raw
traceback.

**Why.** "Just fail and let the model figure it out" spends the model's
turns and context on reverse-engineering a stack trace the script's
author could have explained in one line. The guide calls this "solve,
don't defer".

This entry departs from the guide's example on purpose. The guide's
example *recovers* from a missing file by creating an empty one and from
a permission error by returning an empty string. That swaps a loud failure
for silently wrong output, and the model then reports success on empty
data. Recover only when the fallback is genuinely correct for the task;
otherwise fail loudly with a clear message.

**How.**

```python
import sys

def read_input(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        sys.exit(f"error: {path} not found; run analyze_form.py first to create it")
    except PermissionError:
        sys.exit(f"error: cannot read {path}; check its permissions")
```

**When NOT to apply.** Unexpected errors — the ones the author cannot
predict — should still surface with their traceback rather than be
wrapped in a generic message.

---

## SKILL-020 — No unexplained constants

**What.** Every configuration value in a bundled script — timeouts, retry
counts, thresholds, sizes — carries a one-line comment saying why it has
that value.

**Why.** The guide cites Ousterhout's law against "voodoo constants": if
the author did not know why a timeout is 47, the model cannot know
either, and it has no basis for changing the value when the task needs a
different one — or for leaving it alone when it is load-bearing.

**How.**

```python
# HTTP requests typically finish within 30 s; the margin covers slow links.
REQUEST_TIMEOUT = 30
# Most transient failures clear by the second retry; three bounds the wait.
MAX_RETRIES = 3
```

Not `TIMEOUT = 47  # why 47?`.

**When NOT to apply.** Values whose meaning the name already states
completely (`SECONDS_PER_DAY = 86400`) need no comment.

---

## SKILL-021 — Utility scripts for deterministic work; say run or read

**What.** For any operation with one correct procedure — validating a
file, extracting fields, converting a format — bundle a script instead of
asking the model to write that code on each run. In the instructions, say
whether the model should **run** the script ("Run analyze_form.py to
extract the fields") or **read** it as a reference ("See analyze_form.py
for the extraction algorithm"). Running is the usual case. Where an input
can be rendered as an image, a script that renders it lets the model
inspect the layout visually.

**Why.** A tested script is more reliable and more consistent than code
generated fresh each time, and running it costs only its output in
context — the script's source never loads. An instruction that does not
say run-or-read leaves the model to guess, and a model that reads a
500-line script it was meant to run has spent the tokens the script was
meant to save.

**How.**

```markdown
## Utility scripts

**analyze_form.py** — extract every form field from a PDF:

    python scripts/analyze_form.py input.pdf > fields.json

Output: {"field_name": {"type": "text", "x": 100, "y": 200}}
```

**When NOT to apply.** One-off logic that varies with every task belongs
in the instructions; a script is worth shipping when the same procedure
repeats.

---

## SKILL-022 — Declare dependencies explicitly

**What.** List every package the skill's instructions or scripts need,
with the command that installs it, and check that the target runtime can
install it. Never write "use the pdf library" as though it were present.

**Why.** Runtimes differ: the guide notes that claude.ai can install
packages from npm and PyPI, while the Claude API's code-execution
environment has no network access and no runtime installs. An undeclared
dependency fails at the first import, and the model then improvises an
install (or a different library) that may not work in that environment.

**How.**

```markdown
Install the required package: pip install pypdf

    from pypdf import PdfReader
    reader = PdfReader("file.pdf")
```

**When NOT to apply.** The standard library of the language the script
uses needs no declaration.

---

## SKILL-023 — Fully qualified MCP tool names

**What.** When a skill tells the model to use an MCP tool, name it with
its server prefix, not the bare tool name. The guide's form is
`ServerName:tool_name` (`BigQuery:bigquery_schema`,
`GitHub:create_issue`).

**Why.** With several MCP servers connected, a bare `create_issue` can be
ambiguous or not found at all, and the guide reports "tool not found"
errors from exactly that.

**How.**

```markdown
Use the BigQuery:bigquery_schema tool to retrieve table schemas.
Use the GitHub:create_issue tool to create issues.
```

**When NOT to apply.** The exact spelling of a qualified name differs
between harnesses (Claude Code, for example, exposes MCP tools as
`mcp__<server>__<tool>`). In a skill that ships to more than one harness,
name the server and the tool in prose rather than one harness's spelling
of the qualified name.
