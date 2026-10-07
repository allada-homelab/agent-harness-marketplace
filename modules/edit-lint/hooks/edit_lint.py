#!/usr/bin/env python3
"""PostToolUse: after an Edit/Write, run the one linter that fits the edited file and
hand its findings back to the model as additionalContext. Never blocks; always exits 0;
a linter that is not installed, times out or errors out is skipped silently.
Runs on Claude natively and on pi/dsh through their hook runners (same stdin shape)."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

TOOLS = {"Edit", "Write"}
MAX_CHARS = 4000
SHELLS = {"sh", "bash", "dash", "ksh"}  # shellcheck refuses zsh outright
SHELL_EXTS = {".sh", ".bash", ".ksh"}
JS_EXTS = {".js", ".mjs", ".cjs"}
TS_EXTS = {".ts", ".mts", ".cts"}
ANSIBLE_DIRS = {"ansible", "playbooks", "roles"}
# JSX in a .js file parses under these projects' bundlers but is a syntax error to `node --check`.
JSX_DEPS = ("react", "preact", "solid-js")
# Datree's catalog covers the CRDs a homelab cluster runs (Argo CD, cert-manager, CNPG, ...).
CRD_SCHEMAS = ("https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/"
               "{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json")


def cache_dir(*parts):
    d = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "edit-lint", *parts)
    os.makedirs(d, exist_ok=True)
    return d


def find_up(start, name):
    d = start
    while True:
        if os.path.exists(os.path.join(d, name)):
            return os.path.join(d, name)
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def shebang(path):
    try:
        with open(path, "rb") as f:
            first = f.readline(200).decode("utf-8", "replace")
    except OSError:
        return None
    if not first.startswith("#!"):
        return None
    words = [w for w in first[2:].split() if not w.startswith("-")]
    if not words:
        return None
    interp = os.path.basename(words[0])
    if interp == "env" and len(words) > 1:
        interp = os.path.basename(words[1])
    return interp


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def uses_jsx(path):
    pkg = find_up(os.path.dirname(path), "package.json")
    if not pkg:
        return False
    try:
        data = json.loads(read(pkg))
    except ValueError:
        return False
    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {}), **data.get("peerDependencies", {})}
    return any(d in deps for d in JSX_DEPS)


def pick(path):
    """(label, argv, cwd, finding_codes, output_filter) for the edited file, or None."""
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    parts = path.split(os.sep)
    d = os.path.dirname(path)
    in_claude = os.environ.get("CLAUDECODE") == "1"

    if ext in SHELL_EXTS or (ext == "" and shebang(path) in SHELLS):
        if shebang(path) not in (None, *SHELLS):
            return None  # e.g. a .sh file with a zsh shebang
        return "shellcheck", ["shellcheck", "-f", "gcc", "-S", "warning", path], d, {1}, None

    if ext in (".yml", ".yaml"):
        if len(parts) >= 3 and parts[-3:-1] == [".github", "workflows"]:
            root = os.path.dirname(os.path.dirname(d))
            return "actionlint", ["actionlint", "-no-color", "-oneline", path], root, {1}, None
        text = read(path)
        if re.search(r"(?m)^apiVersion:\s*\S", text) and re.search(r"(?m)^kind:\s*\S", text):
            if "{{" in text:
                return None  # Helm/Jinja template: not valid YAML until rendered
            return ("kubeconform", ["kubeconform", "-ignore-missing-schemas", "-cache", cache_dir("kubeconform"),
                                    "-schema-location", "default", "-schema-location", CRD_SCHEMAS, path],
                    d, {1}, lambda line: "could not find schema" not in line and "failed downloading" not in line)
        if ANSIBLE_DIRS.intersection(parts[:-1]) or re.search(r"(?m)^- (hosts|import_playbook):", text):
            cfg = find_up(d, ".ansible-lint") or find_up(d, "ansible.cfg")
            root = os.path.dirname(cfg) if cfg else d
            return ("ansible-lint", ["ansible-lint", "--offline", "--nocolor", "-q", "-f", "brief", path],
                    root, {2}, None)
        return None

    # Claude gets JS/TS diagnostics from the typescript-lsp plugin; don't double-report there.
    if in_claude:
        return None
    if ext in JS_EXTS:
        if uses_jsx(path):
            return None
        return "node --check", ["node", "--check", path], d, {1}, None
    if ext in TS_EXTS:
        tsconfig = find_up(d, "tsconfig.json")
        if not tsconfig:
            return None
        root = os.path.dirname(tsconfig)
        local = os.path.join(root, "node_modules", ".bin", "tsc")
        tsc = local if os.access(local, os.X_OK) else "tsc"
        info = os.path.join(cache_dir("tsc"), hashlib.sha1(root.encode()).hexdigest()[:16] + ".tsbuildinfo")
        rel = os.path.relpath(path, root)
        return ("tsc", [tsc, "--noEmit", "--pretty", "false", "-p", tsconfig,
                        "--incremental", "--tsBuildInfoFile", info],
                root, {1, 2}, lambda line: line.startswith(rel + "("))
    return None


# pi and dsh await PostToolUse before returning the edit, so every second here is felt per edit.
TIMEOUTS = {"ansible-lint": 25, "tsc": 25, "kubeconform": 15}


def lint(ev):
    if ev.get("tool_name") not in TOOLS:
        return None
    fp = (ev.get("tool_input") or {}).get("file_path")
    if not fp:
        return None
    if not os.path.isabs(fp):
        fp = os.path.join(ev.get("cwd") or os.getcwd(), fp)
    fp = os.path.abspath(fp)
    if not os.path.isfile(fp):
        return None
    choice = pick(fp)
    if not choice:
        return None
    label, argv, cwd, finding_codes, keep = choice
    if not (os.path.isabs(argv[0]) or shutil.which(argv[0])):
        return None
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUTS.get(label, 15))
    except (subprocess.TimeoutExpired, OSError):
        return None
    if p.returncode not in finding_codes:
        return None  # clean, or the linter itself failed (bad config, no network): say nothing
    lines = [ln for ln in (p.stdout + p.stderr).splitlines() if ln.strip()]
    if keep:
        lines = [ln for ln in lines if keep(ln)]
    if not lines:
        return None
    out = "\n".join(lines)
    if len(out) > MAX_CHARS:
        out = out[:MAX_CHARS] + "\n… (truncated)"
    return f"edit-lint: {label} reported issues in {fp} — fix them before moving on:\n{out}"


def main():
    try:
        msg = lint(json.load(sys.stdin))
    except Exception:
        return 0  # fail open: a linter hook must never break an edit
    if msg:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
