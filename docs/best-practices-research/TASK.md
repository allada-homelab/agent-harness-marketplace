# Weekly best-practices research task

You are the weekly research automation for the best-practices library in this
repository. The driver passes today's date in the task prompt — use that date
everywhere a date is needed. This run is **report-only**: you validate the
library, you do not change it.

## Deliverables

1. `docs/best-practices-research/reports/<DATE>.md` — the report, written
   against [`REPORT_TEMPLATE.md`](./REPORT_TEMPLATE.md).
2. A branch `best-practices-research/<DATE>` pushed to origin, with a pull
   request to `main` containing exactly that report file.

## Scope: the rule skills

Read each `SKILL.md` (its rule index) and the `references/` files it points
at. The rule skills are:

| Skill | Prefixes |
|---|---|
| `modules/best-practices/skills/containers-best-practices/` | DOCKER, DEVC, COMPOSE, BUILDX, SEC, UV |
| `modules/best-practices/skills/uv-best-practices/` | UVP |
| `modules/best-practices/skills/python-best-practices/` | PY |
| `modules/best-practices/skills/fastapi-best-practices/` | FAPI, OBS, API |
| `modules/best-practices/skills/databases-best-practices/` | SQLITE, PG |
| `modules/best-practices/skills/repo-best-practices/` | REPO |
| `modules/best-practices/skills/go-best-practices/` | GO |
| `modules/best-practices/skills/grpc-best-practices/` | GRPC |

`meta-best-practices` is the format spec, not a rule domain: only verify that
its format rules still describe the library (rule-ID shape, four-part entry
structure, severity scale) and report any drift as a note.

## Per-domain procedure

For each domain, in this order:

1. Read the `SKILL.md` rule index and list every rule ID (the one-line
   summaries are enough to plan; the `references/` entries carry the detail).
2. Research the latest authoritative guidance for the domain. Prefer primary
   sources and official release notes; the reference files already do, so
   match that bar:
   - containers: Docker docs and buildx docs, the dev container and Compose
     specifications, Docker security guidance
   - uv: the uv docs and changelog
   - python: python.org docs and PEPs, packaging.python.org, ruff, mypy/pyright
   - fastapi: FastAPI and Pydantic docs, uvicorn
   - databases: sqlite.org, postgresql.org, psycopg, SQLAlchemy
   - repo: GitHub Actions and security docs, zizmor, pre-commit, gitleaks
   - go: go.dev docs and release notes, golangci-lint, staticcheck, the Go
     security model
   - grpc: grpc.io, protobuf.dev, buf docs
3. Classify **every** rule:
   - `VALID` — still the recommended practice.
   - `UPDATE` — right in substance, details changed. Name the change and cite
     the source that proves it.
   - `SUPERSEDED` — a newer tool or practice replaced it. Name the
     replacement and cite it.
   - `REMOVE` — no longer applicable or now harmful. Cite what makes it so.
   - `UNVERIFIED` — no source found this run; say what you tried.
4. Propose candidate rules. For each domain, up to five candidates that are
   not already covered by any rule in the library. Give each:
   - a proposed `PREFIX-NNN` ID (next free number in the prefix, per the
     library's first-come-first-served rule),
   - a one-line title in the library's style,
   - a 2–4 sentence rationale (the failure mode it prevents),
   - at least one source URL.

## Report template

Follow [`REPORT_TEMPLATE.md`](./REPORT_TEMPLATE.md) exactly: title, date,
executive summary, per-domain sections with the verdict table, the candidate
list, a methodology note, and the sources list. Fill every section; do not
leave `_FILL IN_` markers.

## Guardrails

- **Report-only.** The only file you may create or modify is
  `docs/best-practices-research/reports/<DATE>.md`. Never edit a skill,
  `SKILL.md`, `references/`, `INDEX.md`, `CONVENTIONS.md`, or any other file.
- **Cite a source** for every verdict and every candidate. No source, no
  claim — mark the rule `UNVERIFIED` instead.
- **Never force-push, never merge, never touch `modules/`.**
- **Blocked domain** = mark its rules `UNVERIFIED` (with what you tried) and
  continue with the rest.
- **Honesty over confidence.** A confident guess is worse than an honest
  `UNVERIFIED`.

## Pull request steps

1. `git add docs/best-practices-research/reports/<DATE>.md`
2. `git commit -m "best-practices research <DATE>: validate the rule library"`
3. `git push -u origin best-practices-research/<DATE>`
4. Open the PR:

   ```
   gh pr create --base main --head best-practices-research/<DATE> \
     --title "best-practices research <DATE>" \
     --body "<summary of the report: totals per verdict + candidate count>"
   ```

5. If the branch already exists on origin (a re-run of the same week), do not
   force-push: fetch, review what the branch has, and either update it with a
   new commit (if the report is incomplete) or report that the run is already
   done.

End your final answer with: the report path, the verdict totals, the candidate
count, and the PR URL (or the exact reason no PR was possible).
