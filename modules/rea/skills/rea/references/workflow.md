# Decompilation workflow, provenance and verification

The discipline that makes a decompilation run trustworthy. A reconstructed
source tree without a provenance record is not evidence — it is a claim. This
reference is target-agnostic; the per-type techniques are in the sibling
references.

## Phases

1. **Identify and inventory.** List every target file. For a package: native
   libraries (`*.so`, ELF files), bundled interpreters, `.pyc` trees, archives,
   app bundles. Identify test artifacts (`test/`, `tests/`, `unit/`,
   `test_*.py`, `*_test.py`, fixtures) and set them aside — production modules
   first, tests last or not at all, and check with the user before spending a
   pass on tests.
2. **Baseline pass.** Decompile everything with the cheapest tool that runs
   (for Python: pycdc-class; see `python-bytecode.md`), each module under a
   `timeout`, and record per-module status. This is the starting point — it
   tells you what is already clean and what needs real work.
3. **Reconstruct the hard modules.** Manual reconstruction from authoritative
   disassembly, or fanned out to workers (see the module's reconstructor agent).
   Assign disjoint module sets; before re-assigning a module, check what the
   previous pass produced.
4. **Verify.** Re-check every module after reconstruction. See "Verification"
   below.
5. **Record.** Rewrite the manifest, then write the notes/report into the
   analyzed repo.

## The manifest

A `MANIFEST.tsv` beside the output tree, one row per module
(`module / status / bytes / notes`). Template: `./manifest.tsv.example`.

Statuses mean:

| Status | Meaning |
|---|---|
| `CLEAN` / `PARTIAL` / `FAIL` / `SEGFAULT` | baseline pass output (e.g. pycdc); `PARTIAL` means the tool emitted something but stopped early or garbled |
| `reconstructed` | written from authoritative disassembly (or upstream + deltas) by hand or a worker |
| `verified` | the file parses as valid source after reconstruction |
| `MATCH` | verified against the bytecode — structure match, or byte-exact where claimed |
| `broken` | does not parse; the known-hard tail |

**Rewrite the manifest after any reconstruction.** The status must describe the
final provenance, not the baseline: a stale row that still says `FAIL` for a
module that was since reconstructed is worse than no manifest, because readers
trust it. The same applies to the README beside the tree — its status table must
match the actual manifest.

Keep the derived tree out of git when the target is proprietary: add
`decompiled/` (or equivalent) to `.gitignore` and keep only the manifest, the
notes and the tooling in the repo.

## Verification

- **Parse check per file, via subprocess.** For Python:
  `python3 -c "import ast; ast.parse(open(f).read())"` per file. An in-process
  check can inherit cwd/import side effects and report false failures; run one
  subprocess per file, or one subprocess that loops and reports per file.
- **Scope includes `__init__.py`.** Package markers are modules too, and exactly
  the ones a "docstring-only" shortcut gets wrong. Reclassifying a file without
  looking at it (because the name suggested it was trivial) is how broken
  `__init__.py` files ship.
- **State the verification scope in the write-up.** "All N non-test modules
  parse" is meaningless if the reader cannot tell which N, or that `__init__.py`
  files were excluded.
- **Structure match, not bytecode match, to identify provenance.** A structure
  comparison — dotted code-object path to `(argcount, nlocals)` — is robust
  across interpreter versions and is the right way to test whether a module
  matches upstream source or a previous reconstruction. Bytecode equality is
  only meaningful when both sides were produced by the same interpreter.
- **Recompile and diff where the compiler can be reproduced.** The acceptance
  test is recompile-and-diff against the original: byte-identical, or a
  difference proven inert. "Parses" is `verified`, never `MATCH`.
- **Line placement is mechanical.** Line tables, first-line numbers and
  debug-info declaration lines depend on padding: use or write an aligner that
  inserts or removes it, run it once, re-verify. Never adjust blank lines by
  hand; edit tools cannot reliably count runs of blank lines.
- **Match the original toolchain and dependency versions exactly** before
  trusting any diff.
- **Keep an explicit accepted-residuals list.** Each entry names the function
  or code object, the exact difference, and the evidence (a note or a minimal
  repro) that no source produces the original bytes. Any difference not on that
  list is `NOT MATCH`, never "close enough".
- **Some compiler output is unreachable from any accepted source**, for example
  an artifact of one optimizer pass. When three structurally different attempts
  produce the same wrong shape, try to prove the artifact with a minimal repro,
  record it as a residual, and stop looping on it.
- **A recompile-and-diff match proves the machine code, not the behavior** that
  compilation erases or keeps only as data: string literals, struct tags or
  serialization field names, and generic instantiation shapes. When the
  reconstruction must run, add a second check: run it next to the original on an
  identical setup and diff the observable behavior.
- **Report per function or code object** as `k/N matched` with the failing
  names, never one pass/fail per module.
- **Re-verify after every pass** — baseline, reconstruction, fixes. The final
  state is the only state that counts.

## Progress tracking and the write-up

Track progress where the work lives: a notes file in the analyzed repo (e.g.
`NOTES-decompile.md`), plus the manifest. A session that tracks findings only in
its own context loses them at the end of the turn.

A useful notes/report skeleton:

```
# <Target> decompilation — findings

Target: <product/package, version, provenance of the artifact>
Tooling: <interpreter/disassembler, decompiler, versions — and the limitations
          of each, e.g. "pycdc is unreliable for CPython 3.11">
Method: <baseline pass, reconstruction, upstream matching>
Provenance: <where the reconstructed tree is, what the manifest rows mean>
Findings: <what the code does; bugs or behaviors found, with module:function
          references>
Open questions: <what static analysis could not decide, and what would decide
          it — a runtime read, a controlled repro>
Verification scope: <which modules parse, which are MATCH, which are broken>
```

Report the honest limitations next to the findings: state what was verified and
what was inferred, and never claim a root cause that only runtime data could
confirm.

## Running a campaign with many workers

- **Keep an attempts ledger:** one row per target per worker run (worker,
  target, verdict, sizes). A target with three attempts and no match is residue:
  re-assign it only with a hypothesis no earlier attempt tried, or once the
  target it was blocked on matches. Do not fill idle worker seats with residue.
- **Give each worker a card per target:** the unique key the verifier accepts,
  source file and line, expected size, current verdict, prior attempts, and the
  literal commands to run. Otherwise workers spend their first dozens of steps
  rediscovering this.
- **Scope each worker's finishing gate to its own targets** and print only its
  verdict block (full output to a log file). A gate that fails for reasons
  outside the worker's control is ignored.
- **One unit of work per brief.** The worker appends each finished item to a
  results file named in the brief, so an interrupted worker still leaves its
  results. Each worker uses its own scratch directory (`mktemp -d`), never
  shared temp paths.
- **Keep a symptom catalogue:** each recurring mismatch shape (what the diff
  shows) mapped to the source idiom that causes it. Workers check it before they
  form a hypothesis and add a row when they find a new one.
- **Per-worker build caches grow without bound** and nothing deletes them. Give
  each worker its own cache directory under one parent, and delete them when the
  campaign ends or before a large fan-out.
- **Concurrency:** measure model latency as workers are added and stop where
  latency climbs faster than total throughput (a few workers on one local model
  server).
