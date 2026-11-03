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
