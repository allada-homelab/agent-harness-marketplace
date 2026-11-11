# Go binary analysis with REA

Go binaries keep rich build metadata and (unless stripped) function names in
their own runtime tables, so start with metadata before decompiling.

## Build metadata

- `rea inspect-go-binary /analysis/<binary>` — answers which Go compiler
  version, modules, replacements and build settings are embedded in the binary.
  It reads the file without running it and needs no Go installation. The CLI
  resolves relative paths against the caller's working directory, so run it from
  the directory containing the binary.
- If a stable read completes but descriptor finalization fails, the error keeps
  the selected path and a `file-snapshot-hash` partial observation — it does not
  claim the metadata was decoded. Report it as partial, not as a failure of the
  whole analysis.

## Beyond metadata: function-level analysis

- `inspect-go-binary` covers **build metadata only** — function names, source
  mappings, types and decompiled code are outside its coverage. Those questions
  go through the native workflow (`./native-ghidra.md`), not this command.
- Go binaries usually keep their function name table (pclntab) unless stripped.
  If present, `rea search --pattern` finds procedures by name pattern and
  `rea decompile --procedure <pkg.Func>` works with the fully qualified name.
  If stripped, fall back to addresses and `rea xrefs`/`trace`.
- Go binaries are usually large; `rea decompile-all` can take a long time.
  Prefer targeted `decompile`/`function` calls once `search` identified the
  procedures of interest.

## Reconstructing source that recompiles to match

- Functions must sit on their debug-info declaration line, so realign padding
  mechanically after any edit that changes line counts.
- Match the Go toolchain and module versions of the binary (read them with
  `inspect-go-binary`) before comparing.
- Compare per function, not per package.
