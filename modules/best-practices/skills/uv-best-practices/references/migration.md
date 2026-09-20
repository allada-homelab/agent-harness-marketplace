# UVP migration rules

Detailed entries for `UVP-060..UVP-062`. Covers migrating to uv from
pip / poetry / pdm / hatch, the `uv export` escape hatch for
downstream consumers that need `requirements.txt`, and the newer
`pylock.toml` (PEP 751) export format.

Citations point at
[Astral's `migrate-to-uv` tool](https://github.com/astral-sh/migrate-to-uv),
the
[Rippling migration write-up](https://www.rippling.com/blog/rippling-migration-to-uv-from-poetry-python-dependency-management-at-scale),
and
[uv export docs](https://docs.astral.sh/uv/concepts/projects/export/).

---

## UVP-060 — Use `migrate-to-uv` for poetry / pip-tools / PDM / Hatch — manually verify the resolver-output diff

**What.** For migrating an existing project to uv, use the official
migration tool:

```bash
# one-shot migration
uvx migrate-to-uv

# or install locally
uv tool install migrate-to-uv
migrate-to-uv
```

It detects the existing tool (Poetry, pip-tools, PDM, Hatch, etc.)
from `pyproject.toml` and rewrites the relevant sections. **Then —
critically — diff the resolved lockfile vs. the old one** before
committing.

**Why.** uv's resolver and Poetry's resolver are **not equivalent**.
For the same `pyproject.toml`, they can pick different concrete
versions for transitive dependencies. Rippling published the
canonical write-up of this problem: they shipped different packages
to production mid-migration and only caught it via a custom
lockfile-diff tool (`cksync`). ([Rippling blog post](https://www.rippling.com/blog/rippling-migration-to-uv-from-poetry-python-dependency-management-at-scale))

Specific structural differences that cause drift:

1. **Caret version specifiers (`^5.1.3`)** are Poetry-only. `migrate-to-uv` converts them to PEP 508 ranges (`>=5.1.3,<6.0.0`), but the resulting range can resolve differently — Poetry's caret semantics include some pre-release behavior that uv's ranges don't.
2. **Dependency-group semantics differ.** Poetry's `[tool.poetry.group.<name>]` is similar to PEP 735 `[dependency-groups]` but not identical. Optional vs. dev vs. extras get conflated in conversion.
3. **`tool.poetry` vs PEP 621 `[project]`** — older Poetry projects put all metadata under `[tool.poetry]`. Migration moves it to `[project]`; hand-written specifications like `python = "^3.12"` need to become `requires-python = ">=3.12"` and easy to miss.

**How.**

```bash
# 1. Run the migration
uvx migrate-to-uv

# 2. Generate the new lockfile
uv lock

# 3. Verify resolver output — compare deps before and after
#    For a poetry project:
poetry export --without-hashes > /tmp/poetry-resolved.txt
uv export --no-hashes --no-dev > /tmp/uv-resolved.txt
diff <(sort /tmp/poetry-resolved.txt) <(sort /tmp/uv-resolved.txt)

# 4. For each differing package, decide:
#    - Is the new version safe? (read changelog)
#    - Should pyproject.toml constrain it more tightly?
#    - Or accept the drift and run the test suite to catch regressions

# 5. Run full test suite on the uv-resolved environment
uv sync --locked
uv run pytest

# 6. Stage and commit pyproject.toml + uv.lock + .python-version together
git add pyproject.toml uv.lock .python-version
git rm poetry.lock requirements.txt   # whatever the old tool used
git commit -m "Migrate to uv"
```

For complex projects, do the migration **on a branch** and run it
through staging before merging. The Rippling write-up describes
running the old and new environments in parallel for a period to
catch differences.

**When NOT to apply.** Brand-new projects use `uv init` directly,
not the migration tool. The migration tool is for *existing*
projects with a non-uv lockfile/manifest.

---

## UVP-061 — `uv export --format requirements.txt --no-hashes --no-dev` for downstream consumers; generate, never commit

**What.** When a downstream consumer (AWS Lambda layers,
old-school PaaS deploys, some CI gates) requires `requirements.txt`,
generate it from the lockfile via `uv export` as a build artifact —
don't commit it.

```bash
uv export --format requirements.txt \
  --no-hashes \
  --no-dev \
  --no-emit-project \
  -o requirements.txt
```

**Why.** Two failure modes from committing it:

1. **Drift from `uv.lock`** — both files describe deps, but only `uv.lock` is updated by `uv` operations. A committed `requirements.txt` becomes stale the moment someone runs `uv add` and forgets to regenerate. Deploys silently install old versions; tests pass against the current lockfile but production runs against the stale requirements.
2. **It's redundant.** The lockfile is the source of truth. Committing the export adds a second source that can disagree.

uv's docs are explicit: "In general, we recommend against using both
a `uv.lock` and a `requirements.txt` file."
([uv export docs](https://docs.astral.sh/uv/concepts/projects/export/))

The newer `pylock.toml` format (PEP 751) is supported by `uv export`
since 0.6.15 and is preferred over `requirements.txt` when downstream
tools support it — same "generate, don't commit" rule applies. See
UVP-062 for the pylock-specific guidance; this rule continues to
cover `requirements.txt` for Lambda / PaaS / legacy targets that
haven't adopted PEP 751.

**How.**

```yaml
# .github/workflows/deploy.yml
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>
      - uses: astral-sh/setup-uv@<sha> # v8.1.0
      - name: Export requirements for Lambda layer
        run: |
          uv export \
            --format requirements.txt \
            --no-hashes \
            --no-dev \
            --no-emit-project \
            -o requirements.txt
      - name: Build Lambda deployment artifact
        run: |
          pip install -r requirements.txt --target ./package
          cd package && zip -r ../layer.zip .
      - name: Publish layer
        run: aws lambda publish-layer-version ...
```

If your CI gate or organization *insists* on a committed
`requirements.txt`, verify it matches the lockfile-generated version
on every PR:

```yaml
- name: Check requirements.txt is current
  run: |
    uv export --format requirements.txt --no-hashes --no-dev \
      -o /tmp/requirements.txt
    diff requirements.txt /tmp/requirements.txt || \
      { echo "requirements.txt is stale; regenerate with 'uv export'"; exit 1; }
```

That makes the lockfile remain the source of truth even when a
copy is committed.

Flag rationale:

- `--no-hashes` — Lambda layer install via `pip install -r` doesn't need hash verification (the wheel is already trusted via the lockfile); hashes make the file noisy.
- `--no-dev` — Strip dev-group deps from the export. Critical: without this, `pytest` and friends ship to production.
- `--no-emit-project` — Don't include the project itself as a `-e .` line. Lambda layer / deploy artifacts install the project separately.

**When NOT to apply.** Pure interop scripts that generate, use, and
discard `requirements.txt` in one CI step — no commit, no
persistence. The rule is about *committed* `requirements.txt`
alongside the lockfile.

---

## UVP-062 — Prefer `uv export --format pylock.toml` over `requirements.txt` when downstream supports PEP 751

**What.** [PEP 751](https://peps.python.org/pep-0751/) defines
`pylock.toml` as a standard, tool-neutral lockfile format. uv supports
exporting to it since 0.6.15:

```bash
uv export --format pylock.toml --no-dev -o pylock.toml
```

When the downstream tool (a CI gate, a deploy step, another package
manager) understands `pylock.toml`, prefer it over `requirements.txt`.
Same "generate, don't commit" rule as UVP-061 applies.

`pylock.toml` does **not** replace `uv.lock`. Keep `uv.lock` as the
project's lockfile; export `pylock.toml` only as an interchange
artifact for consumers.

**Why.** `pylock.toml` is a structural upgrade over `requirements.txt`:

1. **Standard TOML, hashes mandatory.** Every entry has a content hash, package source URL, and Python/platform markers. `requirements.txt` has all of this as ad-hoc text the consumer's tool has to parse heuristically; `pylock.toml` is a real schema you can validate.
2. **Multi-Python / multi-platform in one file.** A single `pylock.toml` can express "on Linux+3.12 use these versions, on macOS+3.13 use those." `requirements.txt` requires one file per target or messy marker syntax. For libraries / CLIs distributed across platforms, this is significant.
3. **Tool-neutral by design.** pip 25.1+ installs from `pylock.toml`. Other resolvers (Poetry, PDM) are adopting it. uv's own export round-trips correctly. The format is no longer "the uv format" or "the pip format" — it's *the* format, when downstream tooling has caught up.

The blocker in 2026 is still **adoption gaps in deploy targets**:

- AWS Lambda's `pip install -r requirements.txt` path doesn't yet consume `pylock.toml`.
- Google App Engine, Heroku-style PaaS — same.
- Older self-hosted private registries / proxies that read requirements files.

For *those* targets, UVP-061 (`requirements.txt`) is still correct.
For modern targets — `pip install` ≥ 25.1, Nix's Python infra, most
new tooling — `pylock.toml` is preferred.

Critically, **do not replace `uv.lock` with `pylock.toml`**. The PEP
intentionally doesn't capture everything uv encodes (per-fork
resolution, conflict markers from UVP-016, source-of-truth metadata
for git deps, workspace member topology). A round-trip
`uv.lock → pylock.toml → uv.lock` is lossy.

**How.**

```yaml
# .github/workflows/deploy.yml — pylock-aware target
- name: Export pylock.toml for deploy
  run: |
    uv export --format pylock.toml \
      --no-dev \
      --no-emit-project \
      -o pylock.toml
- name: Install into deploy artifact via pip ≥25.1
  run: |
    pip install --target ./package -r pylock.toml
```

For platforms still on `requirements.txt`, generate both as needed:

```yaml
- name: Export pylock.toml (preferred)
  run: uv export --format pylock.toml --no-dev -o pylock.toml
- name: Export requirements.txt (fallback for Lambda)
  run: uv export --format requirements.txt --no-hashes --no-dev -o requirements.txt
```

`pylock.toml` from `uv export` includes hashes by default (PEP 751
requires them); there's no `--no-hashes` equivalent because removing
hashes would violate the spec.

If you must commit a `pylock.toml` (some CI gates), verify it matches
the lockfile on every PR:

```yaml
- name: Check pylock.toml is current
  run: |
    uv export --format pylock.toml --no-dev -o /tmp/pylock.toml
    diff pylock.toml /tmp/pylock.toml || \
      { echo "pylock.toml is stale; regenerate with 'uv export'"; exit 1; }
```

**When NOT to apply.** Deploy targets that don't yet understand
`pylock.toml` — Lambda, older PaaS, anything pinned to a pre-25.1
pip. For those, stay on UVP-061 (`requirements.txt`) until the
target catches up.

---

## UVP-074 — Generate a CycloneDX SBOM with `uv export --format cyclonedx`

**What.** Since uv 0.9.11, `uv export --format cyclonedx` emits a
CycloneDX Software Bill of Materials from the resolved lockfile. This is
distinct from `pylock.toml` (UVP-062): a lockfile is for *reproducible
installs*; an SBOM is for *attestation and audit* (CVE scanning, license
inventory, SBOM-aware deploy gates).

**Why.** Supply-chain compliance regimes (SLSA, CRA, US EO 14028)
increasingly require a build-time SBOM. Generating it from `uv.lock` is
the most accurate source — it covers the full resolved graph including
exact transitive versions — and being first-party it doesn't depend on a
separate scanner that might misparse uv's lock format.

**How.**

```bash
uv export --format cyclonedx --no-dev -o sbom.json   # CI artifact
```

**When NOT to apply.** Projects with no supply-chain compliance
requirement and no consumer for the artifact — generating an SBOM nobody
reads just adds CI time.

---
