# REPO GitHub Actions rules

Detailed entries for `REPO-009..REPO-010`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

Citations point at the [zizmor docs](https://github.com/zizmorcore/zizmor/blob/v1.30.1/docs/index.md)
and GitHub's [secure use reference](https://docs.github.com/en/actions/reference/security/secure-use.md).

---

## REPO-009 — Statically audit GitHub Actions workflows (zizmor) for injection, over-broad permissions, persisted credentials and unpinned actions

**What.** zizmor runs as a pre-commit hook (and thus in CI via
`just hooks`, REPO-007) against every workflow file, flagging
template-injection, over-broad `permissions:`, persisted credentials, and
unpinned actions.

**Why.** These are exactly the classes of GitHub Actions vulnerabilities
that show up in real supply-chain incidents (a workflow that interpolates
untrusted `${{ }}` input into a shell step, a token with more scope than
the job needs, a checkout step that leaves credentials persisted for a
later malicious step to exfiltrate). Catching them statically, before
merge, is cheaper than an incident review.
Source: https://github.com/zizmorcore/zizmor/blob/v1.30.1/docs/index.md

> `zizmor` is a static analysis tool for your CI/CD.
> It can find and fix security issues in common CI/CD setups,
> including GitHub Actions, Dependabot, and pre-commit.

**How.** In `.pre-commit-config.yaml` (REPO-001):

```yaml
  # Static analysis of the workflows themselves: template injection, over-broad permissions,
  # credential persistence, unpinned actions.
  - repo: https://github.com/zizmorcore/zizmor-pre-commit
    rev: fa412071e4f5d44d44f9e365f4676f9df92456a2  # frozen: v1.30.1
    hooks:
      - id: zizmor
```

The findings it raises map to fixes like these in the workflow:

```yaml
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1 — full-SHA pin
        with:
          persist-credentials: false  # nothing here pushes; don't leave a token in .git/config
      - run: uv run --frozen just smoke-example "$EXAMPLE"
        env:
          EXAMPLE: ${{ matrix.example }}  # via env, never interpolated into the script
```

**When NOT to apply.** A repo with no `.github/workflows/` (no CI at all)
has nothing for zizmor to audit; a repo whose workflows are all generated
and reviewed by a platform team upstream may run this audit there instead
of per-repo.

---

## REPO-010 — Workflows start from `permissions: {}` and each job requests only the `GITHUB_TOKEN` scopes it needs

**What.** Workflow-level `permissions: {}` removes every default scope;
each job then declares exactly what it needs (for example
`contents: read`).

**Why.** The token's default scopes can be broad, and every step,
third-party actions included, can use the token. Starting from nothing
means a compromised or buggy step can do only what that job was
explicitly granted.
Source: https://docs.github.com/en/actions/reference/security/secure-use.md

> It's good security practice to set the default permission for the `GITHUB_TOKEN` to read access only for repository contents. The permissions can then be increased, as required, for individual jobs within the workflow file.

**How.**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

# Least privilege: nothing by default; each job asks for exactly what it needs.
permissions: {}

jobs:
  check:
    runs-on: ubuntu-24.04
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1
        with:
          persist-credentials: false
      - uses: astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7  # v10.2.0
      - run: uv sync --locked
      - run: uv run --frozen just test
```

**When NOT to apply.** Never skip it; a job that genuinely needs write
access (a release, a PR comment) declares that one scope on that one job.
