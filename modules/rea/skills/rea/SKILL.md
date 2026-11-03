---
name: rea
description: Reverse-engineer a compiled target with REA (Reverse Engineer Anything). Use when the task is understanding what a binary, library, firmware, Go binary, JS/Electron app or Python bytecode (.pyc) target does — decompiling native functions to C, reading binary layout, tracing references, extracting Go build metadata, or recovering Python source from bytecode. REA's Ghidra provider decompiles native code only; this skill covers target-type selection first, then the exact REA commands, the CPython marshal/dis technique for bytecode, and the provenance/verification discipline that keeps reconstructed source trustworthy.
harness: [pi, dsh]
tags: [reverse-engineering, ghidra, decompile, native-binary, go, python-bytecode]
---

# REA (Reverse Engineer Anything)

REA is a local reverse-engineering tool that turns a compiled target into
Evidence: decompiled pseudocode, binary layout, references, and metadata. In this
module it runs as the published container image `ghcr.io/allada-homelab/rea`
(pinned REA 6.8.0 with Ghidra 12.1.4 headless and a full JDK 25). The image has
no `curl` and runs as a non-root user, so run every REA command through `docker
run` with the target directory mounted, and check readiness first.

## Choose the target type first

REA's Ghidra provider turns **native machine code** into C (ELF/PE/Mach-O, Go
binaries, APK native libraries). It does **not** decompile an interpreted target
back to its source language. Before investing in a deep analysis, confirm what
you have:

- `rea doctor --provider ghidra` first — a provider/JDK mismatch surfaces here,
  not as an empty result later.
- `rea inspect /analysis/<binary>` reports `format` and `architecture` — the
  fast way to learn you are not looking at a native program.
- If the target is **Python bytecode** (`.pyc`/`.pyo`, or a `cpython-<ver>`
  filename), do **not** run `rea decompile` on it — Ghidra produces no useful
  pseudocode. Use the Python-bytecode section below instead.
- A Go binary: `rea inspect-go-binary` for build metadata, then Ghidra for
  functions. A JS/Electron app: `rea analyze-javascript-application`.
- A bundled-app package (a QPKG, an appliance image) may mix all of these: list
  the files first, find the bundled interpreter and the `.pyc` tree, and only
  then pick the tool. When the Python side only *reads* a resource and you need
  its writer, the writer is often native code — pursue it with `rea xrefs` and
  `rea trace` on the native helpers rather than concluding the answer is
  unrecoverable.

## Run one command against a target

From the directory that contains the target binary (the mount must expose the
file, and the file must be readable by uid 1000 — the container's non-root
user):

```
docker run --rm -v "$PWD:/analysis" ghcr.io/allada-homelab/rea:latest rea <command>
```

Inside the container the target lives at `/analysis/<filename>`. For example,
decompile a function:

```
docker run --rm -v "$PWD:/analysis" ghcr.io/allada-homelab/rea:latest \
  rea decompile /analysis/<binary> --provider ghidra --procedure <name>
```

## Commands that cover the common reverse-engineering tasks

- `rea inspect /analysis/<binary>` — app overview (what it is, imports, entry).
- `rea inspect-binary-layout /analysis/<binary>` — file/linked layout, no execution.
- `rea decompile /analysis/<binary> --provider ghidra --procedure <name>` — one
  function as C. A selector is required: pass `<name>` (or an address) as the
  second positional, or `--procedure=<name>`. `--file-offset` is the alternative.
- `rea function /analysis/<binary> --provider ghidra --procedure <name>` —
  one complete function with evidence.
- `rea decompile-all /analysis/<binary> --provider ghidra` — every function's
  pseudocode into a directory plus a manifest.
- `rea search /analysis/<binary> --pattern <re>` — search analyzed strings/procedures.
- `rea xrefs /analysis/<binary> --address <addr>` — references to one address.
- `rea trace /analysis/<binary> --query <literal>` — trace a feature through references.
- `rea inspect-go-binary /analysis/<binary>` — Go build metadata (compiler, module,
  build settings) without executing the binary.
- `rea analyze-javascript-application /analysis/<path>` — static JS/Electron reconstruction.
- `rea capabilities` and `rea providers` — what the current setup can do and which
  provider is bound.

Use `--format json` (or `--filter-output <key>` and `--full-output`) to get a
machine-readable result; default output is the human-readable Evidence envelope.

## Reading the output

REA returns Evidence, not raw text. Treat the `normalized_result` (the recovered
pseudocode or summary) as the finding, and report the `limitations` alongside it.
Distinguish what REA observed from what it inferred. A decompile that REA's
provider rejects (for example a Ghidra/JDK version mismatch) surfaces as a
provider error, not an empty result — check `rea doctor --provider ghidra`.

## Decompiling a Python bytecode target instead

### The interpreter that produced the bytecode is the authoritative disassembler

The `marshal` format and the opcode numbers are per-CPython-version. A `.pyc`
from 3.11 must be disassembled with 3.11: a newer host interpreter can
`marshal.loads` the code object but labels the opcodes wrong, so `dis` output is
not authoritative. Bundled apps ship their own interpreter (a QPKG: `data/
python-3.11.2/bin/python3.11`, with its `lib` on `LD_LIBRARY_PATH`) — use that
one. If none is bundled, identify the version from the 4-byte magic at the start
of the file.

Header: CPython 3.7+ writes 16 bytes (magic, flags, mtime, size), so the code
object starts at offset 16; older versions use 8 or 12 bytes.

```python
import marshal, types, dis
code = marshal.loads(open("module.pyc", "rb").read()[16:])

def walk(co, prefix=""):
    if co.co_name != "<module>":
        print(prefix + co.co_name)
    for c in co.co_consts:
        if isinstance(c, types.CodeType):
            walk(c, prefix + "  ")

walk(code)      # inventory every function/class first
dis.dis(code)   # disassemble the module root; recurse into nested code objects
```

For a large module, extract the single function you need (walk `co_consts` to the
named code object, then `dis.dis(code_obj)`) instead of reading the whole module
— the surrounding code is noise and decompilers often abort mid-module.

### Decompilers are version-sensitive — verify one before building a pipeline on it

- **pycdc / Decompyle++ is unreliable for CPython 3.11+**: it mis-decodes the new
  `CACHE`/`PRECALL`/`CALL` words (emitting `<INVALID>`), truncates at the first
  unsupported opcode, and can segfault on large modules. `pycdas` disassembly is
  cache-word-buggy too. Treat its output as a rough baseline only.
- Survey the field **before** committing to one — pycdc, decompyle3, unpyc3,
  pylingual, the interpreter's own `dis`. Verify the package is installable first:
  a failed package resolution usually means a different PyPI name or a
  GitHub-only tool, and that check takes seconds compared to a broken pipeline.
- If no decompiler handles the version cleanly, reconstruct from authoritative
  disassembly: read names/constants/opcodes per function and write faithful
  Python. Preserve the logic exactly — do not "improve" it — and mark uncertain
  spots `# TODO(verify): <func>`.

### Batch pipeline and provenance

Decompile many modules with one script: per-module `timeout`, a status
classification (`CLEAN`/`PARTIAL`/`FAIL`/`SEGFAULT`), and a `MANIFEST.tsv` of
`module / status / bytes / notes` so the run is repeatable and every module
carries evidence. Then:

- **Rewrite the manifest after any manual or subagent reconstruction.** The
  status must describe the final provenance (`pycdc` output, `reconstructed`,
  `verified MATCH`). A stale manifest that still says `FAIL` for a module that
  was since reconstructed is worse than no manifest — readers will trust it.
- **Verify per file with `ast.parse` through a subprocess** (`python3 -c "import
  ast; ast.parse(open(f).read())"` per file). An in-process check can report
  false failures from cwd/import side effects. Include `__init__.py` files in the
  scope — they are modules too, and exactly the ones a "docstring-only" shortcut
  gets wrong.
- Record the verification scope in the write-up: "all N non-test modules parse"
  means nothing if the reader cannot tell which N.

### Prioritize production modules over test files

A decompile-all sweep covers test files too, but they are the lowest-value
output: tests describe expected behavior, not shipped logic, and their source of
truth is often upstream (or they are trivial). By default:

- identify test artifacts first (`test/`, `tests/`, `unit/`, `test_*.py`,
  `*_test.py`, fixtures) and schedule them **last**;
- if the analysis targets behavior, a bug, or a data path, skip them entirely
  until the production modules are reconstructed and verified — and check with
  the user before spending a pass on them;
- decompile tests only when the user asks, or when they are the only way to
  confirm an API contract the production code depends on.

### Upstream matching — the largest time saver for a fork

If the bytecode is a fork of an open-source project (a QNAP S3 server forking
OpenStack Swift is a typical case), clone upstream and match **code-object
structure** — dotted path to `(co_argcount, co_nlocals)` — against upstream tags
to identify the exact base version. Unmodified modules can then be taken from
upstream source as-is (a structure match is robust across Python versions,
unlike bytecode); modified modules use upstream as a reference and you
reconstruct only the deltas from the disassembly.

### Fanning reconstruction out to a team

When several modules need reconstruction, give each agent the exact
disassembler invocation, the module list with output paths, any upstream
reference paths, a read-only scope ("only the output `.py` files you write"),
"preserve the logic exactly", and the `ast.parse` verification command to run at
the end. Assign disjoint module sets; before re-assigning a module, check what
the previous pass produced. If the output files already exist (a baseline pass
created them), say that they must be read before they can be overwritten — the
read-before-write policy turns a blind overwrite into a retry.

## Boundaries

- The analysis provider is **Ghidra**. REA can use other providers (IDA, Hopper,
  JEB, Cutter) but they are not in this image, so `--provider ghidra` (or omitting
  `--provider` to let REA auto-select) is the supported path here.
- The image is amd64-only. On an arm64 host, request a re-published arm64 image
  before running deep analysis.
- REA is a local-only tool. The image's MCP HTTP endpoint is unauthenticated — use
  it only on a trusted network, never expose it to the internet.
- REA never executes the target for the static analysis commands above; a command
  that would run it (observe/launch/debug) needs the target's own runtime and is
  out of scope here.
