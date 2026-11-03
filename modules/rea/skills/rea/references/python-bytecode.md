# Decompiling a Python bytecode target

REA's Ghidra provider does not decompile Python bytecode. For a `.pyc`/`.pyo`
target, the authoritative disassembler is the CPython interpreter that produced
the bytecode; this reference is the full technique. The general pipeline,
provenance and verification rules are in `./workflow.md`.

## The interpreter that produced the bytecode is the authoritative disassembler

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

## Decompilers are version-sensitive — verify one before building a pipeline on it

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

## Upstream matching — the largest time saver for a fork

If the bytecode is a fork of an open-source project (a QNAP S3 server forking
OpenStack Swift is a typical case), clone upstream and match **code-object
structure** — dotted path to `(co_argcount, co_nlocals)` — against upstream tags
to identify the exact base version. Unmodified modules can then be taken from
upstream source as-is (a structure match is robust across Python versions,
unlike bytecode); modified modules use upstream as a reference and you
reconstruct only the deltas from the disassembly.

## Prioritization

Production modules first, test files last or not at all: tests describe
expected behavior, not shipped logic, and their source of truth is often
upstream (or they are trivial). Identify test artifacts (`test/`, `tests/`,
`unit/`, `test_*.py`, `*_test.py`, fixtures) in the inventory, schedule them
last, and skip them entirely for behavior/bug/data-path analysis unless the
user asks — or unless they are the only way to confirm an API contract the
production code depends on.

## Fanning reconstruction out to a team

Give each worker the exact disassembler invocation, the module list with output
paths, any upstream reference paths, a read-only scope ("only the output `.py`
files you write"), "preserve the logic exactly", and the `ast.parse` verification
command to run at the end. Assign disjoint module sets; before re-assigning a
module, check what the previous pass produced. If the output files already exist
(a baseline pass created them), say that they must be read before they can be
overwritten — the read-before-write policy turns a blind overwrite into a
retry. On pi and dsh, dispatch the module's `rea:python-module-reconstructor`
agent instead of re-writing this brief every time.
