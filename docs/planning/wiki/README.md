# wiki module — planning notes (superseded)

Superseded by `docs/superpowers/specs/2026-09-25-okf-wiki-design.md`, which the
`okf-wiki` module implements. Kept as the OKF research record: the spec summary,
the upstream reference implementation review and the vendored `acme_retail`
sample that `modules/okf-wiki/test/test_okf_frontmatter.py` parses. The
decision log below predates the design and its "no hooks, no scripts" premise was
wrong: modules may ship `hooks/hooks.json` with command scripts.

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
