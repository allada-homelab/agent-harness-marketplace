---
name: rea
description: Reverse-engineer a binary with REA (Reverse Engineer Anything). Use when the task is understanding what a compiled program, library, firmware or Go/JS/APK target does — decompiling a function to C, reading a binary's layout, tracing calls, or extracting Go build metadata. REA runs as a container image; this skill gives the exact commands to drive its Ghidra provider and read its Evidence output.
harness: [pi, dsh]
tags: [reverse-engineering, ghidra, decompile, native-binary, go]
---

# REA (Reverse Engineer Anything)

REA is a local reverse-engineering tool that turns a compiled target into
Evidence: decompiled pseudocode, binary layout, references, and metadata. In this
module it runs as the published container image `ghcr.io/allada-homelab/rea`
(pinned REA 6.8.0 with Ghidra 12.1.4 headless and a full JDK 25). The image has
no `curl` and runs as a non-root user, so run every REA command through `docker
run` with the target directory mounted, and check readiness first.

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
