# Best-practices research automation

A weekly research pass over the best-practices rule library in
[`modules/best-practices/`](../../modules/best-practices/README.md). Once a
week it re-checks every rule against the latest authoritative guidance,
proposes new rule candidates, and opens a pull request with a markdown report
of the findings. It is **report-only**: it never edits a skill.

## How it works

1. A weekly systemd user timer (maintained in the homelab dotfiles layer)
   starts the run wrapper.
2. The wrapper drives a one-shot DeepSeek Harness automation session over ACP
   (`dsh --profile acp`), with this repository as the workspace.
3. The agent follows [`TASK.md`](./TASK.md) in that session: for each rule
   skill it validates every rule ID, classifies each one
   (VALID / UPDATE / SUPERSEDED / REMOVE / UNVERIFIED), and proposes candidate
   rules.
4. It writes the report to
   [`reports/<DATE>.md`](./reports/<DATE>.md) — the shape comes from
   [`REPORT_TEMPLATE.md`](./REPORT_TEMPLATE.md) — commits it on a branch
   `best-practices-research/<DATE>`, pushes, and opens a PR to `main`.

Nothing in this repository schedules or runs the automation by itself: the
timer lives in the maintainer's dotfiles layer (the same pattern as the
transcript export/ingest timer), because a repo change here is only live on
the fleet after the paired dotfiles change.

## Files

| File | Purpose |
|---|---|
| [`TASK.md`](./TASK.md) | The task the weekly session executes. |
| [`REPORT_TEMPLATE.md`](./REPORT_TEMPLATE.md) | The report skeleton every run fills in. |
| [`reports/`](./reports/) | One dated report per weekly run, added by the run's PR. |

## Running it manually

Run the driver by hand (any day; it is idempotent per date):

```bash
# from the homelab dotfiles repo
./scripts/best-practices-research-run.sh
```

Or skip the wrapper and run the task in an interactive session: open a shell in
this repository and run `dsh --profile acp` with the driver from
`scripts/best-practices-research-driver.mjs`, or simply ask an agent to
"execute `docs/best-practices-research/TASK.md`".

## Interpreting a report

- **VALID / UPDATE / SUPERSEDED / REMOVE** are claims with sources — the
  report cites where each verdict comes from.
- **UNVERIFIED** means no source was found that run; the rule was not checked
  against the current state of the world. Treat it as "still believed, needs a
  check", not "false".
- **Candidates** are proposals, not rules: they carry an ID, a title, a
  rationale and sources, but nothing in the library changes until a
  maintainer turns one into a real rule entry (see the format spec in
  `meta-best-practices`).

## Notes

- The run's PR is the report, nothing else. A human reviews it and decides
  which findings become rule changes.
- A run that cannot reach a source marks the affected rules UNVERIFIED and
  still produces the report; the automation fails only when no report could be
  written at all.
