# wiki module — planning notes

Status: **planning, nothing shippable yet.** This directory holds research
for a content-only module that creates, recalls, updates and maintains an
Open Knowledge Format (OKF) v0.2 knowledge bundle for a directory, usually a
git repo, from Claude Code, pi and dsh.

Greenfield. No prior implementation is being ported.

| File | What |
|---|---|
| `decisions.md` | The decision log: one entry per open question, filled in as we decide. |
| `okf-v0.2-summary.md` | The spec distilled, plus what it settles for us and what it leaves open. |
| `reference-implementations.md` | What the upstream repo ships, what is reusable, what is not, and the upstream inconsistencies. |
| `okf-upstream/SPEC.md` | Verbatim spec, commit `ad30107` (2026-08-21). |
| `okf-upstream/README.md`, `LICENSE.md` | Upstream README and Apache-2.0 licence. |
| `okf-upstream/prompt-*.md` | The upstream producer agent's two system prompts. |
| `okf-upstream/sample-bundle-acme_retail/` | The one upstream sample that exercises every v0.2 family. Fixture material. |

Upstream: https://github.com/GoogleCloudPlatform/open-knowledge-format

These notes live here, not under `modules/`: every `modules/<name>/` must be a
real module (the gate requires `package.json` and the manifests beside it), and
planning material is not part of the module contract. Before building the
module, read `.agents/skills/adding-a-module/SKILL.md`.

Local edits to vendored files: the sample bundle's three fictional policy
URLs had their hostname suffix changed to `.example` because this repo's gate
rejects private-looking hostnames. Nothing else was changed.
