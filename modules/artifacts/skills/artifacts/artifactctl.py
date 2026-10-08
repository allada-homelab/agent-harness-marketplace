#!/usr/bin/env python3
"""artifactctl — the local artifacts helper: prepare | check | render | open.

Stdlib only. Exit codes: 0 ok, 1 check failures, 2 usage or missing file.
"""
from __future__ import annotations

import html
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SIZE_CAP = 16 * 1024 * 1024
SCRIPT_HOSTS = {"cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com", "cdn.tailwindcss.com", "code.jquery.com"}
STYLE_HOST = "fonts.googleapis.com"
FORBIDDEN = ("window.claude", "claude.ai", "claude.use(", "ArtifactData")

_DOCTYPE = re.compile(r"<!doctype\s+html", re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_VIEWPORT = re.compile(r"<meta\s[^>]*name\s*=\s*[\"']viewport[\"']", re.I)
_ROOT = re.compile(r":root\s*\{")
_DARK = re.compile(r"prefers-color-scheme\s*:\s*dark|\[data-theme\s*=\s*[\"']dark[\"']\]", re.I)
_VAL = r"(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'>]+))"  # double-quoted, single-quoted or bare attribute value
_SCRIPT_SRC = re.compile(r"<script\s[^>]*?\bsrc\s*=\s*" + _VAL, re.I)
_LINK = re.compile(r"<link\s[^>]*>", re.I)
_ATTR = re.compile(r"\b(rel|href)\s*=\s*" + _VAL, re.I)
_SCRIPT_BODY = re.compile(r"<script\b[^>]*>(.*?)</script\s*>", re.I | re.S)
_STYLE_BODY = re.compile(r"<style\b[^>]*>(.*?)</style\s*>", re.I | re.S)
_JS_IMPORT = re.compile(
    r"""\bimport\s*\(\s*(["'])([^"']*)\1"""  # dynamic import("x")
    r"""|\bimport\s+(?:[\w$*{},\s]+?\s*\bfrom\s*)?(["'])([^"']*)\3""")  # import x from "y" / import "y"
_CSS_IMPORT = re.compile(r"""@import\s+(?:url\(\s*(?:"([^"]*)"|'([^']*)'|([^)\s]*))\s*\)|"([^"]*)"|'([^']*)')""", re.I)
_SUBMIT_LISTENER = re.compile(r"""addEventListener\(\s*(["'])submit\1""")
_ONSUBMIT = re.compile(r"\bonsubmit\s*=", re.I)  # .onsubmit = f  and  <form onsubmit=...>
_FORM_TAG = re.compile(r"<form\b[^>]*>", re.I)
_FORM_SEND = re.compile(r"(?<![\w-])(action|method)\s*=", re.I)  # not data-action=
_SUBMIT_CONTROL = re.compile(r"<(button|input)\b[^>]*?(?<![\w-])type\s*=\s*" + _VAL, re.I)
_CODE_BODY = re.compile(r"(<(pre|code)\b[^>]*>).*?(</\2\s*>)", re.I | re.S)
_CSS_STRING = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", re.S)
_SANDBOX_WHY = (" — form submission never fires in the dsh preview (sandbox lacks allow-forms); "
                'use type="button" with a click handler and Enter on keydown')
_SCHEME = re.compile(r"^[a-z][\w+.-]*:", re.I)
_URL = re.compile(r"^(?:https?:)?//([^/]+)(/.*)?$", re.I)
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_CSS_URL = re.compile(r"\burl\([^)]*\)", re.I)
_COLOR_LITERAL = re.compile(
    r"(?<![\w-])#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{3,4})(?![\w-])"
    r"|\b(?:rgba?|hsla?|oklch|oklab|color-mix)\([^()]*(?:\([^()]*\)[^()]*)*\)", re.I)
_THEME_WARN_CAP = 10


def _host(url: str) -> tuple[str, str] | None:
    """(host, path) for an external URL; None only for a scheme-less, backslash-free (relative) value.
    Any other scheme (data:, javascript:, https:\\\\x) yields an empty host, which no allowlist matches."""
    url = url.strip()
    m = _URL.match(url)
    if m:
        return m.group(1).lower(), m.group(2) or "/"
    if _SCHEME.match(url) or "\\" in url:
        return "", url
    return None


def _script_host_ok(host: str, path: str) -> bool:
    if host not in SCRIPT_HOSTS:
        return False
    # normpath first: /npm/../gh/... must not ride the /npm/ prefix
    return host != "cdn.jsdelivr.net" or posixpath.normpath(path).startswith("/npm/")


def _theme_literals(css: str) -> list[tuple[str, str]]:
    """(literal, selector) for each declaration holding a color literal outside the token blocks.
    Allowed: a block whose prelude contains :root, or any block under @media (prefers-color-scheme)."""
    css = _CSS_COMMENT.sub(" ", css)
    hits: list[tuple[str, str]] = []
    stack: list[str] = []
    buf: list[str] = []
    paren = 0
    quote = ""
    escaped = False

    def declaration(decl: str) -> None:
        if not stack or ":" not in decl:
            return
        prop, value = decl.split(":", 1)
        if prop.strip().lower() == "color-scheme":
            return
        if ":root" in stack[-1].lower() or any(
                p.lower().startswith("@media") and "prefers-color-scheme" in p.lower() for p in stack):
            return
        m = _COLOR_LITERAL.search(_CSS_STRING.sub(" ", _CSS_URL.sub("", value)))
        if m:
            hits.append((m.group(0), " ".join(stack[-1].split())))

    for ch in css:
        if quote:
            buf.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == "(":
            paren += 1
            buf.append(ch)
        elif ch == ")":
            paren = max(paren - 1, 0)
            buf.append(ch)
        elif paren:  # inside url(...) and friends, ; { } are data, not structure
            buf.append(ch)
        elif ch == "{":
            stack.append("".join(buf).strip())
            buf = []
        elif ch == "}":
            declaration("".join(buf))
            if stack:
                stack.pop()
            buf = []
        elif ch == ";":
            declaration("".join(buf))
            buf = []
        else:
            buf.append(ch)
    return hits


def _local(kind: str, value: str) -> str:
    return f'local: {kind} references a local file "{value}"; the artifact is one self-contained file, inline it'


def check_html(text: str, size: int) -> tuple[list[str], list[str]]:
    """Static gate for one page. Returns (failures, warnings); one line per finding."""
    text = text.lstrip("﻿")
    fails: list[str] = []
    warns: list[str] = []
    if not _DOCTYPE.search(text):
        fails.append("doctype: missing <!doctype html>; the page is a standalone file, nothing wraps it")
    m = _TITLE.search(text)
    title = " ".join(m.group(1).split()) if m else ""
    if not title:
        fails.append("title: missing <title>; name the page in two to four words")
    elif len(title) > 60:
        fails.append(f"title: {len(title)} chars; a name, not a summary (max 60)")
    if not _VIEWPORT.search(text):
        fails.append("viewport: missing <meta name=\"viewport\">; the page must work at phone width")
    if not _ROOT.search(text):
        fails.append("tokens: no :root { } block; every color is a token defined there first")
    elif not _DARK.search(text):
        warns.append("theme: no dark-mode rule; fine only for a deliberately single-theme design")
    for needle in FORBIDDEN:
        if needle in text:
            fails.append(f"forbidden: {needle!r} is hosted-only; see references/runtime-seam.md")
            break
    for groups in _SCRIPT_SRC.findall(text):
        src = "".join(groups)
        h = _host(src)
        if h is None:
            fails.append(_local("script", src))
        elif not _script_host_ok(*h):
            fails.append(f"host: script from {src} is not on the CDN allowlist")
    for tag in _LINK.findall(text):
        attrs = {k.lower(): "".join(v) for k, *v in _ATTR.findall(tag)}
        rels = attrs.get("rel", "").lower().split()
        if "href" not in attrs:
            continue
        href = attrs["href"]
        h = _host(href)
        if "stylesheet" in rels:
            if h is None:
                fails.append(_local("stylesheet", href))
            elif h[0] != STYLE_HOST:
                fails.append(f"host: stylesheet from {href} is not {STYLE_HOST}")
        if "modulepreload" in rels:
            if h is None:
                fails.append(_local("modulepreload", href))
            elif not _script_host_ok(*h):
                fails.append(f"host: modulepreload from {href} is not on the CDN allowlist")
    for body in _SCRIPT_BODY.findall(text):
        for m in _JS_IMPORT.finditer(body):
            url = m.group(2) if m.group(1) else m.group(4)
            h = _host(url)
            if h is None:
                fails.append(_local("import", url))
            elif not _script_host_ok(*h):
                fails.append(f"host: import from {url} is not on the CDN allowlist")
    for body in _STYLE_BODY.findall(text):
        for m in _CSS_IMPORT.finditer(body):
            url = next(g for g in m.groups() if g is not None)
            h = _host(url)
            if h is None:
                fails.append(_local("@import", url))
            elif h[0] != STYLE_HOST:
                fails.append(f"host: @import from {url} is not {STYLE_HOST}")
    code_free = _CODE_BODY.sub(r"\1 \3", text)  # a code sample about submit listeners is not one
    for _ in _SUBMIT_LISTENER.finditer(code_free):
        fails.append("sandbox: a submit listener" + _SANDBOX_WHY)
    for _ in _ONSUBMIT.finditer(code_free):
        fails.append("sandbox: an onsubmit handler" + _SANDBOX_WHY)
    for tag in _FORM_TAG.findall(code_free):
        for m in _FORM_SEND.finditer(tag):
            fails.append(f"sandbox: <form {m.group(1).lower()}=>" + _SANDBOX_WHY)
    for m in _SUBMIT_CONTROL.finditer(code_free):
        if "".join(g or "" for g in m.groups()[1:]).strip().lower() == "submit":
            fails.append(f'sandbox: <{m.group(1).lower()} type="submit">' + _SANDBOX_WHY)
    if size > SIZE_CAP:
        fails.append(f"size: {size} bytes exceeds the 16 MB cap")
    literals = [hit for body in _STYLE_BODY.findall(text) for hit in _theme_literals(body)]
    for literal, selector in literals[:_THEME_WARN_CAP]:
        warns.append(f'theme: color literal {literal} in rule "{selector}" — '
                     "define it as a token on :root so both themes stay readable")
    return fails, warns


def exclude_path(directory: Path) -> Path | None:
    """The git exclude file that governs `directory`, or None outside a repo.
    `--git-path` resolves to the COMMON dir, so a linked worktree shares main's info/exclude."""
    try:
        out = subprocess.run(["git", "-C", str(directory), "rev-parse", "--git-path", "info/exclude"],
                             check=True, text=True, capture_output=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    p = Path(out)
    return p if p.is_absolute() else (directory / p).resolve()


def project_path(directory: Path) -> Path:
    """The main checkout when `directory` is in a git repo (every worktree of a repo shares one
    folder), else `directory` itself; resolved."""
    try:
        common = subprocess.run(["git", "-C", str(directory), "rev-parse", "--git-common-dir"],
                                check=True, text=True, capture_output=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return directory.resolve()
    c = Path(common)
    c = c if c.is_absolute() else (directory / c)
    return c.resolve().parent


def project_key(path: Path | str) -> str:
    """dsh's project directory name for `path` — a port of `projectKey` in
    @deepseek-ai/dsh-session-persistence-jsonl, so artifacts and sessions share one key per
    project: a run of `/`, `\\` or `:` becomes one `-`, any other character outside
    [A-Za-z0-9._-] becomes `~XXXX`, leading `-` are dropped, and the result is wrapped in `--`."""
    out: list[str] = []
    in_separator = False
    for ch in str(path):
        if ch in "/\\:":
            if not in_separator:
                out.append("-")
            in_separator = True
        elif ch != "~" and ch.isascii() and (ch.isalnum() or ch in "._-"):
            out.append(ch)
            in_separator = False
        else:
            out.append(f"~{ord(ch):04X}")
            in_separator = False
    readable = "".join(out).lstrip("-") or "root"
    return f"--{readable[:251]}--"


def dsh_home(env: dict) -> Path:
    """$DSH_HOME, else ~/.dsh — dsh-home-paths' resolveDshHome; a blank value counts as unset."""
    configured = (env.get("DSH_HOME") or "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".dsh"


def artifacts_root(env: dict) -> Path:
    """$AGENT_ARTIFACTS_DIR, else <dsh home>/artifacts — a sibling of dsh's sessions/ tree.
    Not inside sessions/<key>/: dsh treats every entry of a project directory as a session."""
    if env.get("AGENT_ARTIFACTS_DIR"):
        return Path(env["AGENT_ARTIFACTS_DIR"]).expanduser().resolve()
    return (dsh_home(env) / "artifacts").resolve()


def prepare(directory: Path, env: dict | None = None) -> Path:
    """Default: one folder per project under the artifacts root, keyed like dsh keys sessions
    (`~/.dsh/sessions/<key>/` ↔ `~/.dsh/artifacts/<key>/`), outside every repo."""
    out = artifacts_root(os.environ if env is None else env) / project_key(project_path(directory))
    out.mkdir(parents=True, exist_ok=True)
    return out


def prepare_here(directory: Path) -> Path:
    """`prepare --here`: `.artifacts/` under `directory`, git-excluded."""
    out = (directory / ".artifacts").resolve()
    out.mkdir(parents=True, exist_ok=True)
    exclude = exclude_path(directory)
    if exclude is not None:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text() if exclude.exists() else ""
        if ".artifacts/" not in existing.splitlines():
            with exclude.open("a") as f:
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write(".artifacts/\n")
    return out


def is_display_available(env: dict, platform: str) -> bool:
    return platform == "darwin" or bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


def open_file(path: Path) -> None:
    platform = os.environ.get("ARTIFACTCTL_PLATFORM", sys.platform)
    print(path)
    if not is_display_available(os.environ, platform):
        return
    opener = "open" if platform == "darwin" else "xdg-open"
    if shutil.which(opener) is None:
        return
    try:  # both openers hand off and return at once; the timeout only guards a stuck desktop
        subprocess.run([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _file_arg(arg: str | None) -> Path:
    if not arg:
        print("artifactctl: a file path is required", file=sys.stderr)
        raise SystemExit(2)
    p = Path(arg).expanduser().resolve()
    if not p.is_file():
        print(f"artifactctl: {p} is not a file", file=sys.stderr)
        raise SystemExit(2)
    return p


CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
DARWIN_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
_CONSOLE = re.compile(r':CONSOLE:[^\]]*\]\s*(.*)')
_CONSOLE_MSG = re.compile(r'^"(.*)", source: ')


def find_chrome(env, which, platform, exists=os.path.exists) -> str | None:
    """ARTIFACTS_CHROME wins as-is (the caller reports a missing path); else first Chrome on PATH."""
    if env.get("ARTIFACTS_CHROME"):
        return env["ARTIFACTS_CHROME"]
    for name in CHROME_NAMES:
        found = which(name)
        if found:
            return found
    if platform == "darwin" and exists(DARWIN_CHROME):
        return DARWIN_CHROME
    return None


def parse_console(stderr: str) -> tuple[list[str], list[str]]:
    """(fails, warns) from Chrome's --enable-logging=stderr console lines; uncaught exceptions fail."""
    fails: list[str] = []
    warns: list[str] = []
    for line in stderr.splitlines():
        m = _CONSOLE.search(line)
        if not m:
            continue
        rest = m.group(1)
        mm = _CONSOLE_MSG.match(rest)
        msg = mm.group(1) if mm else rest
        (fails if msg.startswith("Uncaught ") else warns).append(f"console: {msg}")
    return fails, warns


# Console lines from a sandboxed srcdoc frame do not reliably reach stderr, so the inner page reports
# its own uncaught errors to the host, which keeps them in document.title for --dump-dom to read.
_SANDBOX_PROBE = (
    '<script>window.addEventListener("error", e => parent.postMessage({artifactctlError: String(e.message)}, "*"));'
    'window.addEventListener("unhandledrejection", e => parent.postMessage({artifactctlError: "Uncaught (in promise) " + String(e.reason)}, "*"));'
    "</script>")
_SANDBOX_COLLECTOR = (
    '<script>const errs = []; window.addEventListener("message", e => {'
    ' if (e.data && typeof e.data === "object" && "artifactctlError" in e.data) {'
    ' errs.push(String(e.data.artifactctlError)); document.title = "artifactctl-errors:" + JSON.stringify(errs); } });'
    "</script>")
_SANDBOX_ERRORS = "artifactctl-errors:"
_HEAD = re.compile(r"<head\b[^>]*>", re.I)
_HTML_TAG = re.compile(r"<html\b[^>]*>", re.I)
_DOCTYPE_TAG = re.compile(r"<!doctype\b[^>]*>", re.I)


def sandbox_host(inner_html: str) -> str:
    """A host page framing `inner_html` the way dsh does: <iframe sandbox="allow-scripts" srcdoc>."""
    # never ahead of the doctype: a probe there would drop the page into quirks mode
    m = _HEAD.search(inner_html) or _HTML_TAG.search(inner_html) or _DOCTYPE_TAG.search(inner_html)
    at = m.end() if m else 0
    inner = inner_html[:at] + _SANDBOX_PROBE + inner_html[at:]
    return ('<!doctype html><html><head><meta charset="utf-8"><title>sandbox host</title>'
            "<style>html,body{margin:0;height:100%}iframe{border:0;width:100%;height:100%}</style>"
            f'{_SANDBOX_COLLECTOR}</head><body><iframe sandbox="allow-scripts" srcdoc="{html.escape(inner, quote=True)}">'
            "</iframe></body></html>")


def parse_sandbox_dom(dom: str) -> list[str]:
    """FAIL lines from the errors the sandbox probe collected into the dumped host <title>."""
    m = _TITLE.search(dom)
    title = html.unescape(m.group(1)).strip() if m else ""
    if not title.startswith(_SANDBOX_ERRORS):
        return []
    return [f"console: {msg}" for msg in json.loads(title[len(_SANDBOX_ERRORS):])]


def render(path: Path, out: Path, width: int, height: int, sandbox: bool = False) -> int:
    chrome = find_chrome(os.environ, shutil.which, sys.platform)
    if chrome is None:
        print("skipped: no Chrome found; install Chrome or set ARTIFACTS_CHROME")
        return 0
    if os.environ.get("ARTIFACTS_CHROME") and not os.path.exists(chrome):
        print(f"render: ARTIFACTS_CHROME={chrome} does not exist")
        return 2
    tmpdir = tempfile.mkdtemp()
    target = path
    if sandbox:
        target = Path(tmpdir) / "sandbox-host.html"
        target.write_text(sandbox_host(path.read_text(errors="replace")), encoding="utf-8")
    cmd = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
           "--no-default-browser-check", f"--user-data-dir={tmpdir}", f"--window-size={width},{height}",
           f"--screenshot={out}", "--enable-logging=stderr", "--v=0", "--virtual-time-budget=4000",
           # an isolated sandboxed frame runs outside virtual time, so its timers never fire before the dump
           *(["--dump-dom", "--disable-features=IsolateSandboxedIframes"] if sandbox else []), f"file://{target}"]
    if os.geteuid() == 0:  # the sandbox refuses root, which is what containers run as
        cmd.insert(1, "--no-sandbox")
    out.unlink(missing_ok=True)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print("render: chrome failed: timed out after 60s")
        return 2
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    if not out.is_file():
        lines = proc.stderr.strip().splitlines()
        print(f"render: chrome failed: {lines[-1] if lines else f'exit {proc.returncode}'}")
        return 2
    fails, warns = parse_console(proc.stderr)
    if sandbox:  # the same error can arrive by both paths; report it once
        fails = list(dict.fromkeys(fails + parse_sandbox_dom(proc.stdout)))
    print(f"rendered {out}" + (" (sandbox)" if sandbox else ""))
    for w in warns:
        print(f"WARN {w}")
    for f in fails:
        print(f"FAIL {f}")
    print("fail" if fails else "ok")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    if len(argv) < 1 or argv[0] not in ("prepare", "check", "render", "open"):
        print("usage: artifactctl.py prepare [DIR] [--here] | check FILE | render FILE [--out PNG] [--width N] [--height N] [--sandbox] | open FILE",
              file=sys.stderr)
        return 2
    verb, rest = argv[0], argv[1:]
    if verb == "prepare":
        here = "--here" in rest
        rest = [r for r in rest if r != "--here"]
        directory = Path(rest[0]).expanduser() if rest else Path.cwd()
        print(prepare_here(directory) if here else prepare(directory))
        return 0
    if verb == "render":
        import argparse
        ap = argparse.ArgumentParser(prog="artifactctl.py render")
        ap.add_argument("file")
        ap.add_argument("--out")
        ap.add_argument("--width", type=int, default=390)
        ap.add_argument("--height", type=int, default=844)
        ap.add_argument("--sandbox", action="store_true")
        a = ap.parse_args(rest)
        path = _file_arg(a.file)
        out = Path(a.out).expanduser().resolve() if a.out else path.with_suffix(".png")
        return render(path, out, a.width, a.height, a.sandbox)
    path = _file_arg(rest[0] if rest else None)
    if verb == "open":
        open_file(path)
        return 0
    fails, warns = check_html(path.read_text(errors="replace"), path.stat().st_size)
    for w in warns:
        print(f"WARN {w}")
    for f in fails:
        print(f"FAIL {f}")
    if fails:
        return 1
    print(f"ok {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
