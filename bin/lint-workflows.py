#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Enforce the workflow contract on every module workflow script.

A module ships a dynamic workflow as `workflows/<name>.workflow.js` in Claude's
shape (see `workflow-contract/README.md`). Its `meta` export is read by three
consumers — Claude's Workflow tool and the pi and dsh `run_workflow` bridges —
and the bridges read it to build a catalog *without running the file*, so `meta`
must be a **pure object literal**: no identifier references, calls, template
strings or concatenation. This lint parses it the way a catalog builder would,
with no JS engine.

    uv run --script bin/lint-workflows.py [modules/<name> ...]   # default: modules/*

Exit 1 on any FAIL; WARNs are advisory and printed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
META_RE = re.compile(r"(?m)^\s*export\s+const\s+meta\s*=\s*")
NUM_RE = re.compile(r"-?\d+(\.\d+)?([eE][-+]?\d+)?")
IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")
AGENT_CALL_RE = re.compile(r"(?<![\w$.])agent\s*\(")
OPT_KEY_RE = re.compile(r"[{,]\s*([A-Za-z_$][\w$]*)\s*:")
# Options in the contract, plus the four Claude-only ones the fidelity table lists
# as ignored elsewhere. Anything else reaches no harness at all.
AGENT_OPTS = {"label", "phase", "schema", "agentType", "model",
              "effort", "isolation", "background", "resumeFromRunId"}
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0", "\n": ""}


def skip_string(src: str, i: int) -> int:
    """Index just past the string literal starting at src[i] (handles `${…}` nesting)."""
    quote, n = src[i], len(src)
    i += 1
    while i < n:
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if quote == "`" and c == "$" and src[i + 1:i + 2] == "{":
            i = skip_interpolation(src, i + 2)
            continue
        if c == quote:
            return i + 1
        i += 1
    return n


def skip_interpolation(src: str, i: int) -> int:
    depth, n = 1, len(src)
    while i < n and depth:
        c = src[i]
        if c in "'\"`":
            i = skip_string(src, i)
            continue
        depth += c == "{"
        depth -= c == "}"
        i += 1
    return i


def skip_call(src: str, i: int) -> int:
    """Index just past the `)` closing a call whose `(` ends at i. String-blanked source only."""
    depth, n = 1, len(src)
    while i < n and depth:
        depth += src[i] == "("
        depth -= src[i] == ")"
        i += 1
    return i


def strip_strings(src: str) -> str:
    """The source with every string literal and comment blanked, for structural scanning."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in "'\"`":
            out.append('""')
            i = skip_string(src, i)
        elif c == "/" and src[i + 1:i + 2] == "/":
            j = src.find("\n", i)
            i = n if j == -1 else j
        elif c == "/" and src[i + 1:i + 2] == "*":
            j = src.find("*/", i + 2)
            i = n if j == -1 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def decode(body: str) -> str:
    out, i, n = [], 0, len(body)
    while i < n:
        if body[i] == "\\" and i + 1 < n:
            nxt = body[i + 1]
            if nxt == "u":
                out.append(chr(int(body[i + 2:i + 6], 16)))
                i += 6
                continue
            out.append(ESCAPES.get(nxt, nxt))
            i += 2
            continue
        out.append(body[i])
        i += 1
    return "".join(out)


def literal_text(src: str) -> str:
    """The `export const meta = { … }` object literal, verbatim."""
    m = META_RE.search(src)
    if not m:
        raise ValueError("no `export const meta = {…}` export")
    start = m.end()
    if start >= len(src) or src[start] != "{":
        raise ValueError("meta must be assigned an object literal directly")
    end = skip_interpolation(src, start + 1)
    return src[start:end]


def to_json(lit: str) -> str:
    """The literal as JSON. Raises on anything that is not pure data."""
    toks: list[str] = []
    i, n = 0, len(lit)
    while i < n:
        c = lit[i]
        if c.isspace():
            i += 1
        elif c in "'\"":
            j = skip_string(lit, i)
            toks.append(json.dumps(decode(lit[i + 1:j - 1])))
            i = j
        elif c in "}]":
            if toks and toks[-1] == ",":
                toks.pop()  # trailing comma: legal JS, not JSON
            toks.append(c)
            i += 1
        elif c in "{[,:":
            toks.append(c)
            i += 1
        elif m := NUM_RE.match(lit, i):
            toks.append(m.group())
            i = m.end()
        elif m := IDENT_RE.match(lit, i):
            word, i = m.group(), m.end()
            rest = i
            while rest < n and lit[rest].isspace():
                rest += 1
            if word in ("true", "false", "null"):
                toks.append(word)
            elif rest < n and lit[rest] == ":":
                toks.append(json.dumps(word))  # unquoted key
            else:
                raise ValueError(f"{word!r} is a reference, not a literal")
        else:
            raise ValueError(f"unexpected {c!r}")
    return "".join(toks)


def parse_meta(src: str) -> dict:
    return json.loads(to_json(literal_text(src)))


def rel(path: Path) -> Path:
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def lint_workflow(path: Path, out: list[str]) -> int:
    rel_path = rel(path)
    fails = 0

    def fail(msg: str) -> None:
        nonlocal fails
        fails += 1
        out.append(f"  FAIL {rel_path}: {msg}")

    src = path.read_text()
    # The dispatch id off Claude is the filename, not meta.name.
    stem = path.name.removesuffix(".js").removesuffix(".workflow")
    if not NAME_RE.fullmatch(stem):
        fail(f"filename stem {stem!r} must be kebab-case; it is the `<module>:<name>` dispatch id")
    try:
        meta = parse_meta(src)
    except json.JSONDecodeError as e:
        fail(f"meta does not parse as data ({e})")
        return fails
    except ValueError as e:
        fail(f"meta is not a pure object literal — a catalog builder cannot read it without running the file ({e})")
        return fails
    if not isinstance(meta, dict):
        fail("meta must be an object")
        return fails

    name = meta.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        fail(f"meta.name {name!r} is required and must be kebab-case")
    if not str(meta.get("description") or "").strip():
        fail("meta.description is required — it is what the catalog shows the model")
    phases = meta.get("phases")
    if phases is not None:
        if not isinstance(phases, list) or not all(isinstance(p, dict) and isinstance(p.get("title"), str) for p in phases):
            fail("meta.phases must be a list of {title: string}")
    for key in meta:
        if key not in ("name", "description", "phases"):
            out.append(f"  WARN {rel_path}: unknown meta key {key!r} (no harness reads it)")

    stripped = strip_strings(src)
    seen = set()
    for m in AGENT_CALL_RE.finditer(stripped):
        end = skip_call(stripped, m.end())
        for opt in OPT_KEY_RE.findall(stripped[m.end():end]):
            if opt not in AGENT_OPTS and opt not in seen:
                seen.add(opt)
                out.append(f"  WARN {rel_path}: agent() option {opt!r} is outside the workflow contract")
    return fails


def main(argv: list[str]) -> int:
    targets = [Path(a).resolve() for a in argv] or sorted(p for p in (ROOT / "modules").iterdir() if p.is_dir())
    out: list[str] = []
    fails, n = 0, 0
    for module in targets:
        for wf in sorted((module / "workflows").glob("*.js")):
            n += 1
            fails += lint_workflow(wf, out)
    print("\n".join(out) if out else f"  ok ({n} workflows)")
    if out and not fails:
        print(f"  ok ({n} workflows, warnings above)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
