# Best-practices research — <DATE>

**Run:** weekly automation, <DATE>
**Scope:** the rule library in `modules/best-practices/skills/`
**Report-only:** no skill file was changed; this report is proposals.

## Executive summary

- **Rules validated:** _N_ of _N_ (per verdict: _X_ VALID · _Y_ UPDATE ·
  _Z_ SUPERSEDED · _W_ REMOVE · _U_ UNVERIFIED)
- **Candidates proposed:** _K_ new rules
- **Headline findings:** 2–4 sentences on what matters most this week — the
  largest drift, the most impactful candidate, anything the maintainer should
  act on first.

## Verdict totals

| Verdict | Count |
|---|---|
| VALID | _X_ |
| UPDATE | _Y_ |
| SUPERSEDED | _Z_ |
| REMOVE | _W_ |
| UNVERIFIED | _U_ |

## Per-domain findings

### containers-best-practices (DOCKER, DEVC, COMPOSE, BUILDX, SEC, UV)

_Rules checked: N._

#### Updates, supersessions, removals

| Rule | Verdict | What changed | Source |
|---|---|---|---|
| DOCKER-001 | VALID | — | https://docs.docker.com/build/building/multi-stage/ |
| … | … | … | … |

#### Candidates

- **DOCKER-NNN — Title** — rationale. https://source.example

#### Notes

Any domain-level observations (e.g. the whole audit flow, references that
needed no touching).

### uv-best-practices (UVP)

_(same shape as above)_

### python-best-practices (PY)

### fastapi-best-practices (FAPI, OBS, API)

### databases-best-practices (SQLITE, PG)

### repo-best-practices (REPO)

### go-best-practices (GO)

### grpc-best-practices (GRPC)

### meta-best-practices (format spec)

Format-rule drift notes, if any.

## Methodology

- How research was performed (sources consulted per domain, tools used).
- What `UNVERIFIED` means here and what was tried for those rules.
- Known limitations (e.g. no source reachable for a domain, time budget).

## Sources

- Domain — https://…, https://… (as consulted; the per-rule tables carry the
  specific links).
