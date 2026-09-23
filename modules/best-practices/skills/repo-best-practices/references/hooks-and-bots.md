# REPO hooks, bots and review-routing rules

Detailed entries for `REPO-001`, `REPO-002`, `REPO-004`, `REPO-007` and
`REPO-008`. Each follows the four-part **What / Why / How / When NOT to
apply** shape. (`REPO-003`, `REPO-005` and `REPO-006` are reserved.)

Citations point at the [Ruff integrations docs](https://github.com/astral-sh/ruff/blob/0.16.8/docs/integrations.md),
the [Dependabot options reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference.md),
the [gitleaks README](https://github.com/gitleaks/gitleaks/blob/v8.30.1/README.md),
the [just manual](https://github.com/casey/just/blob/1.58.0/README.md) and
[About code owners](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners.md).

---

## REPO-001 — pre-commit as a first-class, incident-commented config artifact

**What.** `.pre-commit-config.yaml` is its own maintained artifact —
remote hooks pinned to full commit SHAs, local hooks that run the
project's own tools, and a comment on every hook explaining why it's
there — not a one-off snippet buried inside another rule's example.

**Why.** A hook config that's only ever shown as an inline example inside
some other rule's docs drifts silently: nobody owns it, so a hook can go
stale, lose its pin, or stop matching what CI actually runs. Treating it
as a first-class file with its own incident comments (why gitleaks, why
zizmor, why this hook order) means the reasoning survives the person who
wrote it.
Source: https://github.com/astral-sh/ruff/blob/0.16.8/docs/integrations.md

> Ruff can be used as a [pre-commit](https://pre-commit.com) hook via [`ruff-pre-commit`](https://github.com/astral-sh/ruff-pre-commit):

**How.**

```yaml
# One hook config runs everywhere: on commit (after `uv run pre-commit install`), in `just hooks`, and in CI.
# Remote hooks are pinned to full commit SHAs (`pre-commit autoupdate --freeze` writes this form; the
# `# frozen:` comment is the tag). A tag can be moved to different code; a SHA can't.
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: 3e8a8703264a2f4a69428a0aa4dcb512790b2c8c  # frozen: v6.0.0
    hooks:
      - id: check-merge-conflict
      - id: end-of-file-fixer
      - id: trailing-whitespace

  # Secret scanning (REPO-004): a leaked token is caught before it reaches a commit.
  - repo: https://github.com/gitleaks/gitleaks
    rev: 83d9cd684c87d95d656c1458ef04895a7f1cbd8e  # frozen: v8.30.1
    hooks:
      - id: gitleaks

  # Local hooks run the project's own tools at the versions in uv.lock, so hook, CI and editor agree.
  # --frozen: a hook must never re-resolve and rewrite uv.lock.
  - repo: local
    hooks:
      # Lint (with fixes) before format: a lint fix can leave code the formatter then rewrites.
      - id: ruff-check
        name: ruff check
        entry: uv run --frozen ruff check --force-exclude --fix --exit-non-zero-on-fix
        language: system
        types_or: [python, pyi]
        require_serial: true
      - id: ruff-format
        name: ruff format
        entry: uv run --frozen ruff format --force-exclude
        language: system
        types_or: [python, pyi]
        require_serial: true
```

The ruff hook order is its own rule: see PY-024 in
[`python-best-practices`](../../python-best-practices/references/linting.md).

**When NOT to apply.** A single-purpose script or a project with no CI to
mirror doesn't need the full `repos:`/local-hooks split; a couple of
ungrouped, uncommented hooks are fine until the config grows enough that
"why is this here" stops being obvious from the hook id alone.

---

## REPO-002 — One dependency bot (Dependabot) maintains every pin, with a cooldown and no auto-merge

**What.** A single `dependabot.yml` with one `updates` entry per
ecosystem (`uv`, `github-actions`, `pre-commit`, `devcontainers`) covers
every pin in the repo — `uv.lock`, SHA-pinned actions and pre-commit
revs, dev container Features — each with a cooldown and no auto-merge.

**Why.** One bot means no overlap to manage between two tools proposing
the same bump. The cooldown lets a bad release get yanked or flagged
before a version-update PR proposes it; security updates ignore the
cooldown by design so a vulnerable pin isn't left waiting.
Source: https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference.md

> Defines a **cooldown period** for dependency updates, allowing updates to be delayed for a configurable number of days. The `cooldown` option is only available for *version* updates, not *security* updates.

**How.**

```yaml
# Dependabot alone keeps every pin current: uv.lock, SHA-pinned actions (it rewrites the SHA and the
# same-line `# vX.Y.Z` comment), SHA-pinned pre-commit revs, and dev container Features.
# No auto-merge: every update is reviewed.
version: 2
updates:
  - package-ecosystem: "uv"
    directory: "/"
    schedule:
      interval: "weekly"
    cooldown:
      default-days: 7
    groups:
      python-minor-and-patch:
        update-types: ["minor", "patch"]

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    cooldown:
      default-days: 7
    groups:
      actions:
        patterns: ["*"]

  - package-ecosystem: "pre-commit"
    directory: "/"
    schedule:
      interval: "weekly"
    cooldown:
      default-days: 7
    groups:
      pre-commit-hooks:
        patterns: ["*"]

  - package-ecosystem: "devcontainers"
    directory: "/"
    schedule:
      interval: "monthly"
    cooldown:
      default-days: 7
```

For the `uv` ecosystem to cover the repo's tooling, the tools themselves
are dev dependencies pinned in `uv.lock`, not global installs:

```toml
[dependency-groups]
dev = ["pre-commit>=4.6.2", "rust-just>=1.58.0", "ruff>=0.16.8"]
```

**When NOT to apply.** A common alternative splits the work: Dependabot
for actions and pre-commit, Renovate for everything else. That split
earns its second tool when a repo needs Renovate-only features (custom
regex managers, grouped PRs across ecosystems Dependabot doesn't cover
well); a small repo where Dependabot's four ecosystems already cover
every pin doesn't need the second bot.

Workflow CLIs such as `pre-commit` go in `[dependency-groups]` too, as
UVP-040 in
[`uv-best-practices`](../../uv-best-practices/references/tools.md) says.
Pinning them in `uv.lock` means Dependabot bumps them with
everything else and hooks, CI and the dev container all run one version;
the cost is that they join the project's dependency resolution, so
their own dependencies must be compatible with the project's. A tool
that conflicts has to be pinned some other way (a pinned `uvx`
invocation), and nothing Dependabot reads records that version.

---

## REPO-004 — Secret-scan the repo itself (detect-secrets with a baseline, gitleaks, or trufflehog)

**What.** Scan twice. A secret-scanning pre-commit hook (for example
gitleaks) checks staged changes at commit time, so a token never reaches a
commit in the first place. CI scans every commit in the history, to catch
anything committed with the hook skipped or not installed.

**Why.** ruff's S-rule family and SAST tools catch code-level issues but
don't scan for literal credential strings; a leaked key in a commit is a
real-world incident, and catching it pre-commit is far cheaper than
rotating a credential after it's already in git history (and possibly
mirrored). The stock gitleaks hook alone is no CI gate: its entry is
`gitleaks git --pre-commit --staged`, and on a clean CI checkout nothing is
staged. With a fake token committed via `--no-verify`, `pre-commit run
--all-files` passes and reports "0 commits scanned".
Source: https://github.com/gitleaks/gitleaks/blob/v8.30.1/README.md

> Gitleaks is a tool for **detecting** secrets like passwords, API keys, and tokens in git repos, files, and whatever else you wanna throw at it via `stdin`.

> The `git` command lets you scan local git repos. Under the hood, gitleaks uses the `git log -p` command to scan patches.

**How.**

```yaml
  # Secret scanning of the repo itself: a leaked token is caught before it reaches a commit.
  - repo: https://github.com/gitleaks/gitleaks
    rev: 83d9cd684c87d95d656c1458ef04895a7f1cbd8e  # frozen: v8.30.1
    hooks:
      - id: gitleaks
      # The hook above scans only staged changes. This manual-stage copy
      # scans every commit; CI runs it.
      - id: gitleaks
        alias: gitleaks-history
        name: Detect hardcoded secrets (git history)
        entry: gitleaks git --redact --verbose
        stages: [manual]
```

```yaml
# CI job: full history, then the history scan (a `just secrets` recipe, REPO-007)
- uses: actions/checkout@<sha>  # vX.Y.Z
  with:
    persist-credentials: false
    fetch-depth: 0
- run: uv run --frozen pre-commit run gitleaks-history --hook-stage manual --all-files
```

Install the commit-time hook locally with `uv run pre-commit install`.

**When NOT to apply.** A repo with no secrets ever handled locally (e.g.
all credentials injected only at deploy time, never touching a
developer's working tree) gets less value, though the hook is cheap
enough that skipping it is rarely worth the risk.

---

## REPO-007 — justfile/task-runner recipes track CI 1:1, each with generated `--list` help text enforced by a test

**What.** Every CI step is a `just` recipe (`uv run --frozen just
<recipe>`), and `just check` runs every recipe CI runs, so
a green local `just check` means a green CI job.

**Why.** When CI has its own inline commands, the local loop and CI drift
apart, and people find out in CI. A test fails if a CI step names a
recipe that doesn't exist, if CI runs a recipe that `check` doesn't, or
if a recipe has no doc comment for `just --list`. It checks membership, not order.
Source: https://github.com/casey/just/blob/1.58.0/README.md

> Comments immediately preceding a recipe will appear in `just --list`:

**How.** The `justfile`:

```just
# Fail if uv.lock is out of date with pyproject.toml
lock-check:
    uv lock --check

# Run every pre-commit hook on every file
hooks:
    uv run --frozen pre-commit run --all-files --show-diff-on-failure

# Strict type check
typecheck:
    uv run --frozen basedpyright

# Tests under coverage, with the fail_under gate
test:
    uv run --frozen coverage run -m pytest
    uv run --frozen coverage report

# Everything CI runs
check: lock-check hooks typecheck test
```

The workflow calls only recipes:

```yaml
      - run: uv sync --locked
      - run: uv run --frozen just lock-check
      - run: uv run --frozen just hooks
      - run: uv run --frozen just typecheck
      - run: uv run --frozen just test
```

And a test keeps them honest:

```python
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECIPE = re.compile(r"^(?P<name>[a-z][a-z0-9-]*)(?:\s[^:]*)?:(?!=)")
CI_STEP = re.compile(r"^\s*- run: uv run --frozen just (?P<name>[a-z][a-z0-9-]*)(?:\s.*)?$")


def recipes(justfile: str) -> dict[str, str | None]:
    """Recipe name -> the comment line right above it (what `just --list` shows), or None."""
    found: dict[str, str | None] = {}
    previous = ""
    for line in justfile.splitlines():
        if m := RECIPE.match(line):
            found[m["name"]] = previous[1:].strip() if previous.startswith("#") else None
        previous = line
    return found


def ci_recipes(workflow: str) -> list[str]:
    return [m["name"] for line in workflow.splitlines() if (m := CI_STEP.match(line))]


def check_runs(justfile: str) -> set[str]:
    """Recipes `just check` runs: its dependencies plus any `just <recipe>` in its body."""
    block = re.search(r"^check:(?P<deps>.*)\n(?P<body>(?:[ \t]+.*\n?)*)", justfile, re.MULTILINE)
    assert block is not None
    return set(block["deps"].split()) | set(re.findall(r"\bjust ([a-z][a-z0-9-]*)", block["body"]))


def test_every_recipe_has_list_help() -> None:
    assert [n for n, doc in recipes((ROOT / "justfile").read_text()).items() if not doc] == []


def test_ci_steps_are_existing_recipes() -> None:
    defined = recipes((ROOT / "justfile").read_text())
    used = ci_recipes((ROOT / ".github/workflows/ci.yml").read_text())
    assert used, "ci.yml should run its checks through just recipes"
    assert [name for name in used if name not in defined] == []


def test_check_recipe_runs_everything_ci_runs() -> None:
    ci = set(ci_recipes((ROOT / ".github/workflows/ci.yml").read_text()))
    assert ci <= check_runs((ROOT / "justfile").read_text())
```

Pin the runner itself in `uv.lock` (the `rust-just` package) so CI and
the dev loop run the same `just` (REPO-002).

**When NOT to apply.** When a CI step genuinely can't run locally
(publishing, deploy credentials). Keep those out of `check` and say so in
the recipe's comment.

---

## REPO-008 — A `CODEOWNERS` file for review routing

**What.** A `CODEOWNERS` file (for example `.github/CODEOWNERS`) names
who is requested for review when a pull request touches a given path.

**Why.** Without it, review routing depends on someone remembering to
add a reviewer by hand, so reviews either go to whoever happens to be
watching or don't happen at all. It also enables requiring code-owner
approval once branch protection is turned on.
Source: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners.md

> Code owners are automatically requested for review when someone opens a pull request that modifies code that they own.

**How.**

```text
# Review routing: every path needs an owner's review once branch protection requires code-owner review.
* @myorg/maintainers
```

**When NOT to apply.** A solo repo with no other reviewers, or one where
every path already has the same single owner by convention, gets little
from a file that would just say `* @same-person` — though such a file is
a cheap placeholder for when a second owner joins.
