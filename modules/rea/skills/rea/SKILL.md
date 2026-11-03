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

## Organize the work

Decompilation is a pipeline, not one command. Run it in phases and record
evidence at each step — the write-up is only as trustworthy as the manifest
that supports it. The full process, templates and verification rules are in
`./references/workflow.md`; read it once before a multi-module run.

1. **Identify the target type.** One `rea doctor` and one `rea inspect` tell you
   what you have. REA/Ghidra only decompiles native code — confirm before
   anything else. Then read the reference for your type:
   - ELF/PE/Mach-O (also APK native libs) → `./references/native-ghidra.md`
   - Go binary → `./references/go-binaries.md`
   - JS/Electron app → `./references/js-electron.md`
   - Python bytecode (`.pyc`/`.pyo`) → `./references/python-bytecode.md`
   A bundled app (a QPKG, an appliance image) may mix several types: list the
   files first and handle each type with its own reference.
2. **Inventory.** Enumerate every target file: native libraries, bundled
   interpreters, `.pyc` trees, archives. Identify test artifacts
   (`test/`, `tests/`, `unit/`, `test_*.py`, `*_test.py`, fixtures) and
   deprioritize them — production modules first, tests last or not at all.
3. **Pick the approach per type.** Read only the reference for your target.
4. **Baseline + provenance.** Run a batch pass with per-module `timeout` and
   record statuses in a `MANIFEST.tsv` (see `./references/manifest.tsv.example`).
   Never start manual reconstruction without knowing what the baseline produced.
5. **Reconstruct.** Do the hard modules yourself, or fan out with the module's
   reconstructor agent (below) — give each worker disjoint module sets and the
   exact interpreter invocation.
6. **Verify and record.** Re-verify every module after reconstruction, rewrite
   the manifest, and write the notes/report into the analyzed repo — findings
   and progress belong to the project, not to this module.

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

Check REA and the Ghidra provider are ready before a deep analysis:

```
docker run --rm -v "$PWD:/analysis" ghcr.io/allada-homelab/rea:latest \
  rea doctor --provider ghidra
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

## Reconstructing a Python bytecode target

For a Python target, REA itself is not the tool — the authoritative
disassembler is the CPython interpreter that produced the bytecode. The full
technique (marshal/dis recipe, decompiler caveats, upstream matching,
verification) is in `./references/python-bytecode.md`; read it before touching a
`.pyc`.

For module-by-module reconstruction, fan out with the module's reconstructor
agent instead of re-writing the brief every time:

- **pi and dsh**: `delegate_agent` with `agent_type` set to
  `rea:python-module-reconstructor`. On pi the tool is inactive until this skill
  is invoked; if it is missing, run `/agents` once.
- **No delegation tool at all**: do it yourself, using
  `./../../agents/python-module-reconstructor.md` as your brief.

Every child sees none of this conversation: give it the module list with output
paths, the bundled interpreter path, and any upstream reference paths.

## Reading the output

REA returns Evidence, not raw text. Treat the `normalized_result` (the recovered
pseudocode or summary) as the finding, and report the `limitations` alongside it.
Distinguish what REA observed from what it inferred. A decompile that REA's
provider rejects (for example a Ghidra/JDK version mismatch) surfaces as a
provider error, not an empty result — check `rea doctor --provider ghidra`.

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
