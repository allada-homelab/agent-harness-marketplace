---
name: qpkg-best-practices
description: Use when building, packaging, debugging or modifying a QNAP QPKG for QTS or QuTS hero — qpkg.cfg, package_routines, the QDK qbuild tool, a QPKG service (init) script, qpkg.conf, App Center install, upgrade and uninstall behavior, code signing, cross-compiling a server binary for x86_64 or ARM QNAP NAS models, or unpacking and patching a vendor .qpkg, or checking a QPKG build tree section by section against these rules. Covers the QPKG- rule family. Container packaging lives in containers-best-practices.
user-invocable: true
argument-hint: "[path]"
---

# QPKG best practices

A curated rule set for building and maintaining QNAP QPKG packages with the
QDK (`qbuild`) for QTS 5.x and QuTS hero. Each rule has a stable ID and a
one-line summary. Full **What / Why / How / When-not-to-apply** entries live
in `references/`.

The QDK's own reference is `docs/QDK-Developer-Guide.md` in
[qnap-dev/QDK](https://github.com/qnap-dev/QDK). Where that guide and the
QDK code disagree, these rules follow the code and say so. A container
alternative to a native package is covered by
[`containers-best-practices`](../containers-best-practices/SKILL.md).

## When to apply this skill

Activate when any of these are true:

- A `qpkg.cfg`, `package_routines`, QPKG service script (`shared/<name>.sh`), `.qpkg` file or QDK build tree is in context.
- The user mentions QNAP, QTS, QuTS hero, App Center, QDK, `qbuild`, `getcfg`/`setcfg`, `qpkg.conf` or `.qpkg`.
- The user wants to package a server or binary for a QNAP NAS, or cross-compile for one.
- The user wants to unpack, inspect or patch an installed or downloaded vendor QPKG.
- The user references a `QPKG-` rule ID.

## How to use the rule index

1. Scan the relevant section(s) below for rule IDs that apply to the current file or task.
2. For each rule you intend to apply or flag, open the corresponding `references/` file and read **only that rule's entry** — they're keyed by ID.
3. Cite the rule ID when you explain a change to the user (e.g. "Moving the data dir out of `.qpkg` — QPKG-021").

## Checking a package

Invoked by name (`/qpkg-best-practices [path]`), check the QPKG build tree at
the path given — the current directory when none is — one section at a time.

1. **Find the tree.** Locate `qpkg.cfg`, `package_routines`, the service
   script `QPKG_SERVICE_PROGRAM` names (normally `shared/<name>.sh`),
   `icons/`, the architecture directories, any qbuild hook scripts, the
   command CI builds with, and any `.qpkg` under `build/`. With no
   `qpkg.cfg`, say so and stop.
2. **Walk the sections below in order.** For each one, open its reference
   file and check every rule in it against the inputs its **Check** line
   names. Mark each rule:
   - **pass** — cite the `file:line` that satisfies it;
   - **fail** — cite the `file:line` and give the fix from the rule's **How**;
   - **n/a** — say why, usually the rule's **When NOT to apply**;
   - **needs-judgment** — the files cannot decide it; ask the question.
3. **Stay static.** Read files and run read-only inspectors (`file`,
   `readelf`); use `qbuild --query` or `--extract` only on a package built
   from this tree, never on anyone else's (QPKG-036). Never install or run a
   `.qpkg`, and edit nothing until the user picks fixes from the report.
4. **Report per section**: a table of rule ID · result · evidence, then the
   fails ordered by impact (data loss and security first).

The QDK 2.0 Reference Manual (2010) and QDK Cookbook (2011) by Michael
Nordström, linked from QNAP's
[QPKG Development Guidelines](https://www.qnap.com/en/how-to/tutorial/article/qpkg-development-guidelines),
are the origin of much of this rule set; the current QDK guide supersedes
both. Every Cookbook recipe maps to a rule: faster builds → QPKG-045;
unknown config files, external config files, configs created at install →
QPKG-022; `.qdksave` files → QPKG-047; disabled service restarted at reboot
→ QPKG-012; options repeated at every build → QPKG-043; repository meta
files in the package → QPKG-042; Optware dependencies (official or not) →
QPKG-007, QPKG-040; symbolic link when enabled → QPKG-014, QPKG-015;
per-architecture extra files → QPKG-041, QPKG-004; run-time data directory
→ QPKG-021.

## Rules — Build and metadata

See [`references/build.md`](./references/build.md). **Check:** `qpkg.cfg`, the tree layout and `icons/`, qbuild hook scripts, the build command CI runs, and a `.qpkg` you built if one exists.

- **QPKG-001** — Choose a native QPKG or a Container Station app on purpose; a native package earns its cost only for host integration, small footprint, or a model with no container support.
- **QPKG-002** — Set `QPKG_NAME` (≤20 chars), `QPKG_VER` (≤10 chars, dotted numeric) and `QPKG_AUTHOR` with no whitespace.
- **QPKG-003** — Build with `qbuild --strict` (or `QDK_STRICT=TRUE`) so metadata warnings fail the build.
- **QPKG-004** — Put shared files in `shared/`, only per-arch overrides in arch dirs, and keep only the arch dirs you really ship (`x86_64`, `arm_64`, `arm-x41`).
- **QPKG-005** — Set `QTS_MINI_VERSION`; set `QTS_MAX_VERSION` only for a known break.
- **QPKG-006** — Check the built package with `qbuild --query` before release.
- **QPKG-007** — Bundle your runtime; never require QNAP's Python, Python3, JRE or MariaDB QPKGs, or Optware.
- **QPKG-040** — Declare QPKG requirements and conflicts in `QPKG_REQUIRE` / `QPKG_CONFLICT`; a requirement counts only when installed and enabled.
- **QPKG-041** — End qbuild hook scripts (setup, pre-build, post-build, teardown) with `return`, never `exit`; they are sourced.
- **QPKG-042** — Exclude `.git` and build leftovers with `--exclude`; qbuild excludes only `.svn`.
- **QPKG-043** — Keep the release `qbuild` options in the repository (`QDK_*` in `qpkg.cfg`), not typed per build or kept only in the per-user `.qdkrc`.
- **QPKG-044** — Name icons `<QPKG_NAME>.gif` (64×64), `_gray.gif` (64×64) and `_80.gif` (80×80); other names are silently dropped.
- **QPKG-045** — Iterate on `package_routines` by rerunning `sh qinstall.sh` from an extracted build on a test NAS.

## Rules — Binaries for QNAP hardware

See [`references/binaries.md`](./references/binaries.md). **Check:** native binaries in the architecture directories (`file`, `readelf -lW`) and the script that builds or downloads them.

- **QPKG-008** — Ship statically linked (musl) binaries; QTS glibc is old (2.21, some models 2.17).
- **QPKG-009** — Treat kernel page size as a build input on ARM: `getconf PAGESIZE` on the target, and no allocator built for 4 KiB pages.
- **QPKG-010** — Check ARM ELF `LOAD` segment alignment with `readelf -lW` against the largest target page size.
- **QPKG-011** — When repackaging an upstream release, verify it against the published checksums at build time.

## Rules — Service script

See [`references/service.md`](./references/service.md). **Check:** the service script `QPKG_SERVICE_PROGRAM` names, and `qpkg.cfg` for `QPKG_TIMEOUT`.

- **QPKG-012** — Guard `start` (and only `start`) with the template's `Enable` check from `qpkg.conf`.
- **QPKG-013** — Implement `start`, `stop`, `restart` and `remove`; uninstall calls `stop` then `remove`.
- **QPKG-014** — Resolve the install dir at runtime with `getcfg <name> Install_Path`; never hard-code a volume path.
- **QPKG-015** — Recreate everything outside the `.qpkg` dir on every `start` and remove it on `stop`; the root filesystem resets at boot.
- **QPKG-016** — `start` returns success only after the service answers: PID alive and port polled under a bounded timeout, never a bare `&`.
- **QPKG-017** — A `start` that finds one component already running still starts the rest; never `exit` from a helper.
- **QPKG-018** — Declare package dependencies with `Dependency=` and wait for them with a bounded retry; `QPKG_RC_NUM` ordering does not hold.
- **QPKG-019** — Export `QNAP_QPKG=<name>` in the service script so Resource Monitor attributes child processes.
- **QPKG-020** — Keep the PID file in `/var/run` and logs on a data volume, with a size cap.

## Rules — Install, upgrade and uninstall

See [`references/lifecycle.md`](./references/lifecycle.md). **Check:** `package_routines` (every `pkg_*` hook and `PKG_*_REMOVE` block) and the `QPKG_CONFIG` entries in `qpkg.cfg`.

- **QPKG-021** — Keep mutable data in hook-created dirs, and data that must outlive the package on a share, never in shipped files.
- **QPKG-022** — List every shipped config file in `QPKG_CONFIG` so upgrades keep user edits (`.qdksave` / `.qdkorig`).
- **QPKG-023** — Detect an upgrade in `pkg_pre_install` from the old `Version` in `qpkg.conf`; `$SYS_QPKG_DIR` already exists there.
- **QPKG-024** — Abort an install with `err_log`, never `exit` or a return code.
- **QPKG-025** — Escape runtime values in `PKG_*_REMOVE` blocks as `\$VAR`; they are expanded at build time.
- **QPKG-026** — Uninstall removes exactly what the package added outside its `.qpkg` dir, and says whether user data survives.
- **QPKG-027** — A fresh install is enabled and started by default; set `SYS_QPKG_SERVICE_ENABLED=FALSE` when the service needs setup first.
- **QPKG-046** — Put each step in the hook that runs at the right moment: `pkg_init` → `pkg_check_requirement` → `pkg_pre_install` → `pkg_install` → `pkg_post_install`.
- **QPKG-047** — Migrate a changed shipped config in `pkg_init` and record its new MD5 with `set_qpkg_config`, so the user's file is not replaced and saved as `.qdksave`.
- **QPKG-048** — Use the installer's `SYS_*_PATH` / `get_share_path` for shares and `is_less` / `is_greater` for versions; never hard-code share paths or compare versions as strings.

## Rules — System integration

See [`references/integration.md`](./references/integration.md). **Check:** the web, volume and port fields in `qpkg.cfg`, and logging and cron handling in the service script and `package_routines`.

- **QPKG-028** — Declare the web UI with `QPKG_WEBUI`, `QPKG_WEB_PORT` and the proxy fields; keep `QPKG_DESKTOP_APP="0"` unless the UI tolerates an iframe.
- **QPKG-029** — Set `QPKG_VOLUME_SELECT` deliberately so a large app does not land on the system volume.
- **QPKG-030** — Choose default ports outside QNAP's published port list and make them configurable.
- **QPKG-031** — Log events with `log_tool` at the right level (`-t0` info, `-t1` warning, `-t2` error).
- **QPKG-032** — Persist cron entries in the QTS config copy of the crontab (`config/crontab`) and reload; `crontab -e` is lost at reboot.

## Rules — Security and vendor packages

See [`references/security.md`](./references/security.md). **Check:** the whole tree for credentials and file modes, signing fields in `qpkg.cfg`, and any vendor package the project patches.

- **QPKG-033** — Never depend on `autorun.sh` or silently edit system init or cron state.
- **QPKG-034** — Plan for signature enforcement: unsigned packages are blocked by default and `QNAP_CODE_SIGNING` works only inside QNAP's pipeline.
- **QPKG-035** — Never repack a vendor-signed QPKG; patch its runtime files at `start`, verify the patch, and restore on `stop`.
- **QPKG-036** — Unpack untrusted packages with `head`/`tail` and `tar`, never `qbuild --extract` or by running the file.
- **QPKG-037** — Never ship default credentials; generate them at install time into a `0600` file.
- **QPKG-038** — Give package dirs least-privilege modes; never `chmod 777`.
- **QPKG-039** — Do not redistribute a modified QNAP package or decompiled QNAP code.
