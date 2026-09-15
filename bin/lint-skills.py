#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""Enforce the portable SKILL.md contract on every module skill.

A skill in this marketplace is read by three parsers with different tolerances.
The contract is the intersection they all honour, plus the things one of them
silently gets wrong (dsh drops `allowed-tools`, hands flat skills the wrong
resourceBase, never shows `whenToUse`; pi ignores unknown keys; Claude needs
name == dirname). A skill scoped with `harness:` to a subset may use that
subset's extras: `harness: [claude]` unlocks Claude-only keys and `${CLAUDE_*}`.
One Claude key is portable on its own: `context: fork` — see FORK_UNLOCKS below.

    uv run --script bin/lint-skills.py [modules/<name> ...]   # default: modules/*

Exit 1 on any FAIL; WARNs are advisory and printed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
HARNESSES = {"claude", "pi", "dsh"}
NAME_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")

ALLOWED = {
    "name", "description", "argument-hint", "user-invocable", "disable-model-invocation",
    "license", "compatibility", "metadata", "harness", "tags",
}
# Keys that only Claude honours. Present in a portable skill they either vanish
# (dsh: allowed-tools, model) or change semantics per harness — worse than absent.
CLAUDE_ONLY = {"context", "agent", "hooks", "effort", "model", "allowed-tools",
               "disallowed-tools", "background", "paths", "shell", "arguments", "when_to_use"}
UNRENDERED = {"whenToUse", "when_to_use"}  # parsed by dsh, shown nowhere (A11)
# `context: fork` is portable: the pi and dsh bridges dispatch such a skill as an
# isolated agent of type <module>:<skill> (persona = body, tools = the
# `allowed-tools` tokens, model = the `model` alias), so those keys carry meaning
# off Claude and are unlocked with it. `agent` names the Claude child type only.
FORK_UNLOCKS = {"allowed-tools", "model", "agent"}
CLAUDE_BUILTIN_AGENTS = ("Explore", "Plan", "general-purpose")
AGENT_TYPE_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*:[a-z0-9]+(-[a-z0-9]+)*")

CLAUDE_TOKEN = re.compile(r"\$\{CLAUDE_[A-Z_]+\}")
ABS_PATH = re.compile(r"(?<![\w./-])(?:~|/home|/Users|/usr|/opt|/etc)/[\w./-]+")
BANG_CMD = re.compile(r"(?m)^\s*!`|```!")
SUBST = re.compile(r"\$(ARGUMENTS|[0-9]+)\b")


def frontmatter(text: str) -> tuple[dict | None, str]:
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 4)
    if end == -1:
        return None, text
    data = yaml.safe_load(text[4:end])
    return (data if isinstance(data, dict) else None), text[end + 4:]


def rel(path: Path) -> Path:
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def lint_skill(path: Path, out: list[str]) -> int:
    rel_path = rel(path)
    fails = 0

    def fail(msg: str) -> None:
        nonlocal fails
        fails += 1
        out.append(f"  FAIL {rel_path}: {msg}")

    def warn(msg: str) -> None:
        out.append(f"  WARN {rel_path}: {msg}")

    fm, body = frontmatter(path.read_text())
    if fm is None:
        fail("no YAML frontmatter")
        return fails
    name, desc = fm.get("name"), (fm.get("description") or "").strip()
    if not name:
        fail("missing name (dsh has no dirname fallback)")
    elif not NAME_RE.fullmatch(str(name)):
        fail(f"invalid name {name!r}")
    elif name != path.parent.name:
        fail(f"name {name!r} != directory {path.parent.name!r} (Claude requires it)")
    if not desc:
        fail("missing description (every harness drops the skill)")
    elif len(desc) > 1024:
        fail(f"description {len(desc)} chars > 1024 (pi warns; it is sent on every request)")

    harness = fm.get("harness")
    if isinstance(harness, str):
        harness = [harness]
    if harness is not None:
        if not isinstance(harness, list) or not set(harness) <= HARNESSES:
            fail(f"harness must be a list drawn from {sorted(HARNESSES)}, got {harness!r}")
            harness = None
    scope = set(harness) if harness else HARNESSES
    claude_only = scope == {"claude"}

    context = fm.get("context")
    forked = context == "fork"
    if "context" in fm and not claude_only and not forked:
        fail(f"context: {context!r} is Claude-only; only `context: fork` is portable "
             "(drop it or scope the skill with `harness: [claude]`)")

    for key in fm:
        if key in ALLOWED:
            continue
        if key in CLAUDE_ONLY:
            if claude_only or key == "context" or (forked and key in FORK_UNLOCKS):
                continue
            fail(f"key {key!r} is Claude-only; drop it or scope the skill with `harness: [claude]`")
        elif key in UNRENDERED:
            warn(f"{key!r} reaches no catalog or UI on dsh; fold it into description")
        else:
            warn(f"unknown key {key!r} (ignored by every harness)")

    agent = fm.get("agent")
    if forked and not claude_only and agent is not None:
        if str(agent) not in CLAUDE_BUILTIN_AGENTS and not AGENT_TYPE_RE.fullmatch(str(agent)):
            warn(f"agent {agent!r} is neither a Claude built-in ({', '.join(CLAUDE_BUILTIN_AGENTS)}) "
                 "nor a <module>:<agent> type; only Claude honours the key")

    if not claude_only:
        for m in CLAUDE_TOKEN.finditer(body):
            fail(f"{m.group(0)} in body; only Claude expands it")
        for m in ABS_PATH.finditer(body):
            fail(f"absolute path {m.group(0)!r} in body; reference assets skill-relative")
        if BANG_CMD.search(body):
            fail("dynamic !`cmd` injection is Claude-only")
        if "dsh" in scope and SUBST.search(body) and not fm.get("user-invocable"):
            warn("$ARGUMENTS/$N in a skill that is not user-invocable is never expanded")
        if fm.get("user-invocable") and not fm.get("argument-hint") and SUBST.search(body):
            warn("command takes $ARGUMENTS but has no argument-hint")

    # Assets the body names must exist beside the skill.
    for m in re.finditer(r"(?<![\w./])\./([\w./-]+)", body):
        if not (path.parent / m.group(1)).exists():
            fail(f"references ./{m.group(1)} which does not exist in the skill directory")
    # A sibling skill's asset: it must exist and stay inside the same module.
    module_dir = path.parent.parent.parent.resolve()
    for m in re.finditer(r"(?<![\w/])\.\./([\w./-]+)", body):
        target = (path.parent / ".." / m.group(1)).resolve()
        if not target.exists() or module_dir not in target.parents:
            fail(f"references ../{m.group(1)} which does not exist inside this module")
    return fails


def lint_root(skills_root: Path, out: list[str]) -> int:
    fails = 0
    for flat in sorted(skills_root.glob("*.md")):
        out.append(f"  FAIL {rel(flat)}: flat skill file; dsh gives it the root as resourceBase — use {flat.stem}/SKILL.md")
        fails += 1
    for d in sorted(p for p in skills_root.iterdir() if p.is_dir()):
        skill = d / "SKILL.md"
        if not skill.exists():
            out.append(f"  FAIL {rel(d)}: directory without SKILL.md")
            fails += 1
        else:
            fails += lint_skill(skill, out)
    return fails


def main(argv: list[str]) -> int:
    targets = [Path(a).resolve() for a in argv] or sorted(p for p in (ROOT / "modules").iterdir() if p.is_dir())
    out: list[str] = []
    fails = 0
    n = 0
    for module in targets:
        skills_root = module / "skills"
        if not skills_root.is_dir():
            continue
        n += len(list(skills_root.glob("*/SKILL.md")))
        fails += lint_root(skills_root, out)
    print("\n".join(out) if out else f"  ok ({n} skills)")
    if out and not fails:
        print(f"  ok ({n} skills, warnings above)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
