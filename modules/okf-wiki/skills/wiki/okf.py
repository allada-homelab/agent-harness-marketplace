#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""okf-wiki: deterministic operations on the OKF v0.2 bundle at <repo>/.wiki/.

Stdlib only. Every verb ends with one stable line `okf: <verb> <verdict> [detail]`.
Exit codes: 0 ok, 1 findings (validate errors, broken anchors), 2 refusal or usage error,
3 near-duplicate refused by `new`. The two hook verbs always exit 0 (fail open, loud).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import groupby
from pathlib import Path

TYPES = ("gotcha", "decision", "runbook", "convention", "architecture", "reference")
KEY_ORDER = ("type", "resource", "title", "description", "tags", "status", "generated",
             "verified", "stale_after", "sources", "usage_window")
BUNDLE = ".wiki"
OKF_VERSION = "0.2"
SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$")
ACTOR_RE = re.compile(r"^(okf-wiki/[a-z0-9.-]+|human:\S+|process:\S+)$")
DESC_MAX = 200
WORDS_MAX = 400
VERIFIED_KEEP = 5
FANOUT_DEFAULT, FANOUT_MIN, FANOUT_MAX = 4, 1, 16
DIGEST_VERSION = 1
DIGEST_BUDGET = 8000  # characters, roughly 2k tokens
REFLECT_SESSIONS, REFLECT_DAYS = 20, 14
STATE_TTL_DAYS = 7


class OkfError(Exception):
    """A refusal: printed as `okf: <verb> refused <message>`, exit 2."""


def status(verb: str, verdict: str, detail: str = "") -> None:
    print(f"okf: {verb} {verdict}" + (f" {detail}" if detail else ""))


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_ts(s: str) -> datetime | None:
    if not TS_RE.match(s):
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def git(root: Path, *args: str, check: bool = True, timeout: float = 10) -> str:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                       timeout=timeout)
    if check and r.returncode:
        raise OkfError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def repo_root(start: Path) -> Path | None:
    try:
        out = git(start, "rev-parse", "--show-toplevel", timeout=5)
    except (OkfError, OSError, subprocess.TimeoutExpired):
        return None
    return Path(out.strip())


def resolve_fanout(flag: int | None) -> tuple[int, str]:
    if flag is not None:
        value, source = flag, "flag"
    elif os.environ.get("OKF_WIKI_FANOUT"):
        raw = os.environ["OKF_WIKI_FANOUT"]
        if not raw.strip().isdigit():
            raise OkfError(f"OKF_WIKI_FANOUT={raw!r} is not a whole number")
        value, source = int(raw), "env"
    else:
        return FANOUT_DEFAULT, "default"
    if not FANOUT_MIN <= value <= FANOUT_MAX:
        raise OkfError(f"fanout {value} ({source}) must be between {FANOUT_MIN} and {FANOUT_MAX}")
    return value, source


def _root_and_bundle(args, need_bundle: bool = True) -> tuple[Path, Path]:
    start = Path(args.root).resolve() if args.root else Path.cwd()
    root = repo_root(start) or start
    bundle = root / BUNDLE
    if need_bundle and not bundle.is_dir():
        raise OkfError(f"no {BUNDLE}/ at {root}")
    return root, bundle


def cmd_fanout(args) -> int:
    n, source = resolve_fanout(args.fanout)
    status("fanout", str(n), f"({source})")
    return 0


# ---- frontmatter subset ------------------------------------------------------------
# Block mappings and sequences nested by space indentation, one-line flow collections
# `[a, b]` / `{k: v}` (nestable), plain / 'single' / "double" scalars, and `#` comments.
# Every scalar stays a string: YAML's implicit typing is the timestamp trap upstream OKF
# hit. Anything outside the subset raises FrontmatterError.

class FrontmatterError(ValueError):
    pass


_UNSUPPORTED_START = ("|", ">", "&", "*", "!", "%", "@", "`")
_KEY_RE = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*):(?:\s+(.*))?$")
_YAML_WORDS = {"true", "false", "yes", "no", "null", "on", "off", "~"}


def _strip_comment(s: str) -> str:
    out, quote = [], None
    for i, ch in enumerate(s):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"" and s[:i].rstrip()[-1:] in ("", ":", "-", "[", "{", ","):
            quote = ch  # a quote opens a string only where a value starts (it's ≠ 'x')
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(tok: str, line: int) -> str:
    tok = tok.strip()
    if not tok:
        return ""
    if tok[0] == '"':
        if len(tok) < 2 or tok[-1] != '"':
            raise FrontmatterError(f"line {line}: unterminated double-quoted string")
        esc = {'"': '"', "\\": "\\", "n": "\n", "t": "\t"}
        return re.sub(r'\\(["\\nt])', lambda m: esc[m.group(1)], tok[1:-1])
    if tok[0] == "'":
        if len(tok) < 2 or tok[-1] != "'":
            raise FrontmatterError(f"line {line}: unterminated single-quoted string")
        return tok[1:-1].replace("''", "'")
    if tok[0] in _UNSUPPORTED_START:
        raise FrontmatterError(f"line {line}: {tok[0]!r} is outside the okf-wiki YAML subset")
    return tok


def _skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i] == " ":
        i += 1
    return i


def _flow_token(s: str, i: int, line: int, stop: str) -> tuple[str, int]:
    i = _skip_ws(s, i)
    if i < len(s) and s[i] in "'\"":
        q, j = s[i], i + 1
        while True:
            j = s.find(q, j)
            if j == -1:
                raise FrontmatterError(f"line {line}: unterminated quoted string")
            if q == "'" and s[j + 1:j + 2] == "'":
                j += 2
                continue
            if q == '"':
                k, slashes = j - 1, 0
                while s[k] == "\\":
                    slashes, k = slashes + 1, k - 1
                if slashes % 2:
                    j += 1
                    continue
            return _scalar(s[i:j + 1], line), j + 1
    j = i
    while j < len(s) and s[j] not in stop:
        j += 1
    tok = s[i:j].strip()
    if not tok:
        raise FrontmatterError(f"line {line}: empty value in a flow collection")
    return _scalar(tok, line), j


def _flow_value(s: str, i: int, line: int):
    i = _skip_ws(s, i)
    if i >= len(s):
        raise FrontmatterError(f"line {line}: unexpected end of a flow collection")
    if s[i] == "[":
        items, i = [], _skip_ws(s, i + 1)
        if i < len(s) and s[i] == "]":
            return items, i + 1
        while True:
            value, i = _flow_value(s, i, line)
            items.append(value)
            i = _skip_ws(s, i)
            if i < len(s) and s[i] == ",":
                i += 1
            elif i < len(s) and s[i] == "]":
                return items, i + 1
            else:
                raise FrontmatterError(f"line {line}: expected ',' or ']' in a flow list")
    if s[i] == "{":
        mapping, i = {}, _skip_ws(s, i + 1)
        if i < len(s) and s[i] == "}":
            return mapping, i + 1
        while True:
            key, i = _flow_token(s, i, line, stop=":,}")
            i = _skip_ws(s, i)
            if i >= len(s) or s[i] != ":":
                raise FrontmatterError(f"line {line}: expected ':' in a flow mapping")
            value, i = _flow_value(s, i + 1, line)
            if key in mapping:
                raise FrontmatterError(f"line {line}: duplicate key {key!r}")
            mapping[key] = value
            i = _skip_ws(s, i)
            if i < len(s) and s[i] == ",":
                i += 1
            elif i < len(s) and s[i] == "}":
                return mapping, i + 1
            else:
                raise FrontmatterError(f"line {line}: expected ',' or '}}' in a flow mapping")
    return _flow_token(s, i, line, stop=",]}")


def _flow(s: str, line: int):
    value, i = _flow_value(s, 0, line)
    if s[i:].strip():
        raise FrontmatterError(f"line {line}: text after a flow collection")
    return value


def _value(rest: str, line: int):
    return _flow(rest, line) if rest[0] in "[{" else _scalar(rest, line)


def _is_item(text: str) -> bool:
    return text == "-" or text.startswith("- ")


def _block(lines, pos: int, indent: int):
    return _seq(lines, pos, indent) if _is_item(lines[pos][1]) else _map(lines, pos, indent)


def _map(lines, pos: int, indent: int):
    mapping = {}
    while pos < len(lines) and lines[pos][0] == indent and not _is_item(lines[pos][1]):
        _, text, n = lines[pos]
        m = _KEY_RE.match(text)
        if not m:
            raise FrontmatterError(f"line {n}: expected `key: value`")
        key, rest = m.group(1), (m.group(2) or "").strip()
        if key in mapping:
            raise FrontmatterError(f"line {n}: duplicate key {key!r}")
        pos += 1
        if rest:
            mapping[key] = _value(rest, n)
        elif pos < len(lines) and (lines[pos][0] > indent
                                   or (lines[pos][0] == indent and _is_item(lines[pos][1]))):
            mapping[key], pos = _block(lines, pos, lines[pos][0])
        else:
            mapping[key] = ""
    if pos < len(lines) and lines[pos][0] > indent:
        raise FrontmatterError(f"line {lines[pos][2]}: unexpected indentation")
    return mapping, pos


def _seq(lines, pos: int, indent: int):
    items = []
    while pos < len(lines) and lines[pos][0] == indent and _is_item(lines[pos][1]):
        _, text, n = lines[pos]
        rest = text[1:].strip()
        pos += 1
        if not rest:
            if pos < len(lines) and lines[pos][0] > indent:
                value, pos = _block(lines, pos, lines[pos][0])
                items.append(value)
            else:
                items.append("")
        elif rest[0] in "[{":
            items.append(_flow(rest, n))
        elif rest[0] not in "'\"" and _KEY_RE.match(rest):
            # `- key: value` opens a mapping whose further keys sit under the key.
            child = indent + (len(text) - len(rest))
            end = pos
            while end < len(lines) and lines[end][0] > indent:
                end += 1
            block = [(child, rest, n)] + lines[pos:end]
            value, used = _map(block, 0, child)
            if used != len(block):
                raise FrontmatterError(f"line {block[used][2]}: unexpected indentation")
            items.append(value)
            pos = end
        else:
            items.append(_scalar(rest, n))
    return items, pos


def parse_frontmatter(text: str) -> dict:
    lines = []
    for n, raw in enumerate(text.split("\n"), 1):
        lead = raw[: len(raw) - len(raw.lstrip())]
        if "\t" in lead:
            raise FrontmatterError(f"line {n}: tab indentation")
        body = _strip_comment(raw)
        if body.strip():
            lines.append((len(body) - len(body.lstrip(" ")), body.strip(), n))
    if not lines:
        return {}
    value, pos = _block(lines, 0, lines[0][0])
    if pos != len(lines):
        raise FrontmatterError(f"line {lines[pos][2]}: unexpected indentation")
    if not isinstance(value, dict):
        raise FrontmatterError("frontmatter must be a mapping")
    return value


def _needs_quote(s: str, flow: bool) -> bool:
    if s == "" or s != s.strip() or "\n" in s or s.lower() in _YAML_WORDS:
        return True
    if s[0] in "-?:,[]{}#&*!|>'\"%@`<":
        return True
    if ": " in s or " #" in s or s.endswith(":"):
        return True
    return flow and any(c in s for c in ",[]{}")


def _q(s: str, flow: bool = False) -> str:
    s = str(s)
    if not _needs_quote(s, flow):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _flow_dump(v) -> str:
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {_flow_dump(x)}" for k, x in v.items()) + "}"
    if isinstance(v, list):
        return "[" + ", ".join(_flow_dump(x) for x in v) + "]"
    return _q(v, flow=True)


def _flat(v) -> bool:
    return all(not isinstance(x, (dict, list)) for x in (v.values() if isinstance(v, dict) else v))


def _dump_entry(out: list[str], key: str, v, ind: int) -> None:
    pad = " " * ind
    if isinstance(v, (dict, list)) and (not v or _flat(v)):
        out.append(f"{pad}{key}: {_flow_dump(v)}")
    elif isinstance(v, dict):
        out.append(f"{pad}{key}:")
        for k, x in v.items():
            _dump_entry(out, k, x, ind + 2)
    elif isinstance(v, list):
        out.append(f"{pad}{key}:")
        for x in v:
            if isinstance(x, dict) and x and not _flat(x):
                sub: list[str] = []
                for k, y in x.items():
                    _dump_entry(sub, k, y, ind + 4)
                sub[0] = f"{pad}  - " + sub[0].lstrip()
                out.extend(sub)
            elif isinstance(x, (dict, list)):
                out.append(f"{pad}  - {_flow_dump(x)}")
            else:
                out.append(f"{pad}  - {_q(x)}")
    else:
        out.append(f"{pad}{key}: {_q(v)}")


def dump_frontmatter(meta: dict) -> str:
    out: list[str] = []
    for k in [k for k in KEY_ORDER if k in meta] + [k for k in meta if k not in KEY_ORDER]:
        _dump_entry(out, k, meta[k], 0)
    return "\n".join(out) + "\n"


def split(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        raise FrontmatterError("missing frontmatter (the file must start with ---)")
    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:])
    raise FrontmatterError("unterminated frontmatter")


def render(meta: dict, body: str) -> str:
    return "---\n" + dump_frontmatter(meta) + "---\n" + body


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8").lstrip("\ufeff").replace("\r\n", "\n")


# ---- CLI ----------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="okf.py", description="okf-wiki: deterministic operations on <repo>/.wiki/")
    p.add_argument("--root", help="repository root (default: the git toplevel of the cwd)")
    sub = p.add_subparsers(dest="verb", required=True)

    def verb(name, fn, *positional, **flags):
        s = sub.add_parser(name)
        for a in positional:
            s.add_argument(a, **({"nargs": "*"} if a == "ids" else {}))
        for flag, kw in flags.items():
            s.add_argument(flag.replace("_", "-"), **kw)
        s.set_defaults(fn=fn)

    verb("fanout", cmd_fanout, __fanout={"type": int})
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except OkfError as e:
        print(f"okf: {args.verb} refused {e}", file=sys.stderr)
        status(args.verb, "refused", str(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
