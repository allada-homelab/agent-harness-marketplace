# Native binary analysis with REA (ELF/PE/Mach-O)

REA's Ghidra provider decompiles native machine code to C. This reference covers
the native workflow; the general pipeline is in `./workflow.md`.

## Start

- `rea doctor --provider ghidra` — a provider/JDK mismatch surfaces here, not
  as an empty result later.
- `rea inspect /analysis/<binary>` — format, architecture, imports, entry. This
  is also the fast way to learn you are **not** looking at a native program
  (a Go binary or a bundled Python app should be handled by the sibling
  references).
- `rea inspect-binary-layout /analysis/<binary>` — file/linked layout without
  executing the target.

## Decompiling

- `rea decompile /analysis/<binary> --provider ghidra --procedure <name>` — one
  function as C. A selector is required: pass `<name>` (or an address) as the
  second positional, or `--procedure=<name>`. `--file-offset` is the alternative
  when you have an offset instead of a symbol.
- `rea function /analysis/<binary> --provider ghidra --procedure <name>` — one
  complete function with evidence.
- `rea decompile-all /analysis/<binary> --provider ghidra` — every function's
  pseudocode into a directory plus a manifest.

## Tracing data flow

- `rea search /analysis/<binary> --pattern <re>` — search analyzed
  strings/procedures.
- `rea xrefs /analysis/<binary> --address <addr>` — references to one address.
- `rea trace /analysis/<binary> --query <literal>` — trace a feature through
  references.

When the analysis dead-ends at "this resource is written by native code" (the
Python layer only reads a file, a register, a device), that is the moment to
switch to the native side: `xrefs`/`trace` on the writer is often the decisive
evidence, and it is a mistake to conclude the answer is unrecoverable without
looking.

## Reading the output

REA returns Evidence, not raw text. Treat the `normalized_result` (the recovered
pseudocode or summary) as the finding, and report the `limitations` alongside it.
Distinguish what REA observed from what it inferred. A decompile that the
provider rejects surfaces as a provider error, not an empty result. Use
`--format json` (or `--filter-output <key>` and `--full-output`) for a
machine-readable result.

## Scope notes

- The image is amd64-only. On an arm64 host, request a re-published arm64 image
  before running deep analysis.
- APK native libraries are Ghidra targets; the Java/Kotlin layer is not.
- REA never executes the target; a command that would run it (observe/launch/
  debug) needs the target's own runtime and is out of scope here.
